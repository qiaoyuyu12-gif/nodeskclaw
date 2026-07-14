"""nodeskclaw-backend/tests/test_gene_overwrite_submission_review.py

验证覆盖审核暂存的提交/批准/拒绝/过期竞态。
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.models.gene import Gene
from app.models.gene_overwrite_submission import GeneOverwriteSubmission
from app.models.instance import Instance
from app.models.cluster import Cluster
from app.models.gene import InstanceGene
from app.models.organization import Organization
from app.models.org_membership import OrgMembership, OrgRole
from app.models.user import User
from app.services.gene_service import (
    fork_gene_to_library,
    get_instance_genes,
    review_gene_overwrite_submission,
)

TEST_DATABASE_URL = "postgresql+asyncpg://nodeskclaw:nodeskclaw123@localhost:5432/nodeskclaw_rbac_test"
engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def require_test_db():
    try:
        async with engine.connect():
            yield
    except Exception:
        pytest.skip("PostgreSQL test database is not available")


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class _FakeUser:
    def __init__(self, id_: str, org_id: str | None, is_super_admin: bool = False):
        self.id = id_
        self.is_super_admin = is_super_admin
        self.current_org_id = org_id


async def _setup_org_with_admin(db: AsyncSession):
    org = Organization(id=_uid("org"), name="Org X", slug=_uid("org-x"))
    submitter = User(id=_uid("user"), name="Alice", username=_uid("alice"))
    admin = User(id=_uid("admin"), name="Admin", username=_uid("admin"))
    db.add_all([org, submitter, admin])
    await db.commit()
    membership = OrgMembership(org_id=org.id, user_id=admin.id, role=OrgRole.admin)
    db.add(membership)
    await db.commit()
    return org, submitter, admin


@pytest.mark.asyncio
async def test_approve_replaces_target_and_rewires_instance_gene(require_test_db):
    async with TestSessionLocal() as db:
        org, submitter, admin = await _setup_org_with_admin(db)

        # Gene.lineage_group_id 是 NOT NULL 列，必须在构造函数里显式传入
        # （不能构造后再赋值属性），与 Task 7/8/9 已验证的写法保持一致。
        source_id = _uid("gene")
        source = Gene(
            id=source_id, name="团队助手", slug=_uid("team-bot"),
            visibility="public", version="1.0.0", lineage_group_id=_uid("lineage"),
        )
        db.add(source)
        await db.commit()

        forked = await fork_gene_to_library(
            db, source.id, "org", current_user=_FakeUser(submitter.id, org.id), org_id=org.id,
        )
        target_id = forked["id"]

        # 给这个组织的技能装一个实例，验证审核通过后引用会重接
        cluster = Cluster(id=_uid("cluster"), name="Cluster", created_by=submitter.id)
        instance = Instance(
            id=_uid("inst"), name="Agent", slug=_uid("agent"), cluster_id=cluster.id,
            namespace="default", image_version="latest", created_by=submitter.id,
        )
        db.add_all([cluster, instance])
        await db.commit()
        ig = InstanceGene(instance_id=instance.id, gene_id=target_id, status="installed")
        db.add(ig)
        await db.commit()

        source_row = (await db.execute(select(Gene).where(Gene.id == source.id))).scalar_one()
        source_row.version = "1.1.0"
        await db.commit()

        submit_result = await fork_gene_to_library(
            db, source.id, "org", current_user=_FakeUser(submitter.id, org.id),
            org_id=org.id, overwrite=True,
        )
        submission_id = submit_result["submission_id"]

        result = await review_gene_overwrite_submission(
            db, submission_id, "approve", current_user=_FakeUser(admin.id, org.id),
        )
        assert result["review_status"] == "approved"

        old_row = (await db.execute(
            select(Gene).where(Gene.id == target_id, Gene.deleted_at.is_(None))
        )).scalar_one_or_none()
        assert old_row is None  # 旧行已被软删

        # 必须加 deleted_at IS NULL 过滤：旧行软删后仍与新行共享同一个
        # lineage_group_id，不过滤会同时命中两条导致 MultipleResultsFound。
        new_row = (await db.execute(
            select(Gene).where(
                Gene.lineage_group_id == source_row.lineage_group_id,
                Gene.visibility == "org_private",
                Gene.deleted_at.is_(None),
            )
        )).scalar_one()
        assert new_row.version == "1.1.0"

        # InstanceGene 引用应该重接到新行
        items = await get_instance_genes(db, instance.id)
        assert any(item["gene_id"] == new_row.id for item in items)


@pytest.mark.asyncio
async def test_reject_leaves_target_untouched(require_test_db):
    async with TestSessionLocal() as db:
        org, submitter, admin = await _setup_org_with_admin(db)

        source = Gene(
            id=_uid("gene"), name="团队助手", slug=_uid("team-bot"),
            visibility="public", version="1.0.0", lineage_group_id=_uid("lineage"),
        )
        db.add(source)
        await db.commit()

        forked = await fork_gene_to_library(
            db, source.id, "org", current_user=_FakeUser(submitter.id, org.id), org_id=org.id,
        )
        target_id = forked["id"]

        source_row = (await db.execute(select(Gene).where(Gene.id == source.id))).scalar_one()
        source_row.version = "1.1.0"
        await db.commit()

        submit_result = await fork_gene_to_library(
            db, source.id, "org", current_user=_FakeUser(submitter.id, org.id),
            org_id=org.id, overwrite=True,
        )
        submission_id = submit_result["submission_id"]

        result = await review_gene_overwrite_submission(
            db, submission_id, "reject", reason="内容需要修改", current_user=_FakeUser(admin.id, org.id),
        )
        assert result["review_status"] == "rejected"

        target_row = (await db.execute(
            select(Gene).where(Gene.id == target_id, Gene.deleted_at.is_(None))
        )).scalar_one_or_none()
        assert target_row is not None
        assert target_row.version == "1.0.0"


@pytest.mark.asyncio
async def test_approve_stale_submission_auto_rejects(require_test_db):
    """提交后、审核前，target 已经被另一条已批准的提交替换掉——approve 应该
    自动转为 rejected，不报服务器错误，也不误伤已经替换成功的新行。"""
    async with TestSessionLocal() as db:
        org, submitter, admin = await _setup_org_with_admin(db)

        source = Gene(
            id=_uid("gene"), name="团队助手", slug=_uid("team-bot"),
            visibility="public", version="1.0.0", lineage_group_id=_uid("lineage"),
        )
        db.add(source)
        await db.commit()

        forked = await fork_gene_to_library(
            db, source.id, "org", current_user=_FakeUser(submitter.id, org.id), org_id=org.id,
        )

        source_row = (await db.execute(select(Gene).where(Gene.id == source.id))).scalar_one()
        source_row.version = "1.1.0"
        await db.commit()
        submit_1 = await fork_gene_to_library(
            db, source.id, "org", current_user=_FakeUser(submitter.id, org.id),
            org_id=org.id, overwrite=True,
        )

        source_row.version = "1.2.0"
        await db.commit()
        submit_2 = await fork_gene_to_library(
            db, source.id, "org", current_user=_FakeUser(submitter.id, org.id),
            org_id=org.id, overwrite=True,
        )

        # 先批准第二个提交（v1.2.0），target 行被替换
        await review_gene_overwrite_submission(
            db, submit_2["submission_id"], "approve", current_user=_FakeUser(admin.id, org.id),
        )

        # 再批准第一个提交（v1.1.0）：它的 target_gene_id 已经不是活跃行了，应该自动过期拒绝
        result = await review_gene_overwrite_submission(
            db, submit_1["submission_id"], "approve", current_user=_FakeUser(admin.id, org.id),
        )
        assert result["review_status"] == "rejected"
        assert result.get("stale") is True

        # 已经替换成功的新行（v1.2.0）不受影响
        from sqlalchemy import select as sa_select
        current = (await db.execute(
            sa_select(Gene).where(Gene.lineage_group_id == source_row.lineage_group_id, Gene.visibility == "org_private", Gene.deleted_at.is_(None))
        )).scalar_one()
        assert current.version == "1.2.0"


@pytest.mark.asyncio
async def test_approve_does_not_bypass_for_admin_submitter(require_test_db):
    """提交覆盖的人自己就是该组织 admin：submission 依然是 pending_owner，
    不会自动 approved，必须显式调用 approve。"""
    async with TestSessionLocal() as db:
        org = Organization(id=_uid("org"), name="Org Y", slug=_uid("org-y"))
        admin = User(id=_uid("admin"), name="Admin", username=_uid("admin"))
        db.add_all([org, admin])
        await db.commit()
        membership = OrgMembership(org_id=org.id, user_id=admin.id, role=OrgRole.admin)
        db.add(membership)
        await db.commit()

        source = Gene(
            id=_uid("gene"), name="团队助手", slug=_uid("team-bot"),
            visibility="public", version="1.0.0", lineage_group_id=_uid("lineage"),
        )
        db.add(source)
        await db.commit()

        await fork_gene_to_library(
            db, source.id, "org", current_user=_FakeUser(admin.id, org.id), org_id=org.id,
        )

        from sqlalchemy import select as sa_select
        source_row = (await db.execute(sa_select(Gene).where(Gene.id == source.id))).scalar_one()
        source_row.version = "1.1.0"
        await db.commit()

        submit_result = await fork_gene_to_library(
            db, source.id, "org", current_user=_FakeUser(admin.id, org.id),
            org_id=org.id, overwrite=True,
        )
        submission = (await db.execute(
            sa_select(GeneOverwriteSubmission).where(GeneOverwriteSubmission.id == submit_result["submission_id"])
        )).scalar_one()
        assert submission.review_status == "pending_owner"  # 没有因为提交者是 admin 而自动变成 approved
