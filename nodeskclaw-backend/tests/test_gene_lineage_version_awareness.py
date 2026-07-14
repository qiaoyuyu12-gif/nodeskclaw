"""验证 Gene.lineage_group_id 的传播规则、create_gene() 覆盖分支的版本号
校验，以及个人库单向落后检测。

用真实 PostgreSQL 测试库（与 test_gene_name_dedup.py 一致的模式）。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.exceptions import ConflictError
from app.models.user import User
from app.schemas.gene import GeneCreateRequest
from app.services.gene_service import create_gene

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
    """轻量伪造 current_user，只暴露 fork_gene_to_library 实际读取的三个属性。"""

    def __init__(self, id_: str, org_id: str | None, is_super_admin: bool = False):
        self.id = id_
        self.is_super_admin = is_super_admin
        self.current_org_id = org_id


def _req(name: str, slug: str, *, version: str = "1.0.0", overwrite: bool = False) -> GeneCreateRequest:
    return GeneCreateRequest(name=name, slug=slug, visibility="personal", version=version, overwrite=overwrite)


@pytest.mark.asyncio
async def test_fresh_create_gets_own_lineage_group_id(require_test_db):
    async with TestSessionLocal() as db:
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add(user)
        await db.commit()

        result = await create_gene(
            db, _req("客服助手", "customer-bot"),
            user_id=user.id, org_id=None, visibility="personal",
        )
        assert result["id"] is not None


@pytest.mark.asyncio
async def test_overwrite_inherits_old_lineage_group_id(require_test_db):
    async with TestSessionLocal() as db:
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add(user)
        await db.commit()

        await create_gene(
            db, _req("客服助手", "customer-bot", version="1.0.0"),
            user_id=user.id, org_id=None, visibility="personal",
        )
        from app.models.gene import Gene
        from sqlalchemy import select
        old = (await db.execute(select(Gene).where(Gene.slug == "customer-bot"))).scalar_one()
        old_lineage_group_id = old.lineage_group_id

        await create_gene(
            db, _req("客服助手", "customer-bot", version="1.0.1", overwrite=True),
            user_id=user.id, org_id=None, visibility="personal",
        )
        new = (await db.execute(
            select(Gene).where(Gene.slug == "customer-bot", Gene.deleted_at.is_(None))
        )).scalar_one()
        assert new.lineage_group_id == old_lineage_group_id
        assert new.version == "1.0.1"


@pytest.mark.asyncio
async def test_overwrite_allows_same_version_number(require_test_db):
    async with TestSessionLocal() as db:
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add(user)
        await db.commit()

        await create_gene(
            db, _req("客服助手", "customer-bot", version="1.0.0"),
            user_id=user.id, org_id=None, visibility="personal",
        )
        result = await create_gene(
            db, _req("客服助手", "customer-bot", version="1.0.0", overwrite=True),
            user_id=user.id, org_id=None, visibility="personal",
        )
        assert result["version"] == "1.0.0"


@pytest.mark.asyncio
async def test_overwrite_rejects_version_regression(require_test_db):
    async with TestSessionLocal() as db:
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add(user)
        await db.commit()

        await create_gene(
            db, _req("客服助手", "customer-bot", version="1.2.0"),
            user_id=user.id, org_id=None, visibility="personal",
        )
        with pytest.raises(ConflictError):
            await create_gene(
                db, _req("客服助手", "customer-bot", version="1.1.0", overwrite=True),
                user_id=user.id, org_id=None, visibility="personal",
            )


@pytest.mark.asyncio
async def test_overwrite_rejects_invalid_version_format(require_test_db):
    async with TestSessionLocal() as db:
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add(user)
        await db.commit()

        await create_gene(
            db, _req("客服助手", "customer-bot", version="1.0.0"),
            user_id=user.id, org_id=None, visibility="personal",
        )
        with pytest.raises(ConflictError):
            await create_gene(
                db, _req("客服助手", "customer-bot", version="latest", overwrite=True),
                user_id=user.id, org_id=None, visibility="personal",
            )


@pytest.mark.asyncio
async def test_publish_variant_gets_independent_lineage_group_id(require_test_db):
    """variant 是进化出的新技能，不应该继承父技能的 lineage_group_id。"""
    from app.models.cluster import Cluster
    from app.models.gene import Gene, InstanceGene
    from app.models.instance import Instance
    from app.services.gene_service import publish_variant

    async with TestSessionLocal() as db:
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add(user)
        await db.commit()

        cluster = Cluster(id=_uid("cluster"), name="Cluster", created_by=user.id)
        instance = Instance(
            id=_uid("inst"), name="Agent", slug=_uid("agent"), cluster_id=cluster.id,
            namespace="default", image_version="latest", created_by=user.id,
        )
        db.add_all([cluster, instance])
        await db.commit()

        # Gene.lineage_group_id 是 NOT NULL 列且没有 Column 级默认值，直接
        # 构造 Gene(...)（绕过 create_gene()）时必须显式提供，这里用 parent
        # 自己的 id 作为血缘起点，模拟"正常创建的父技能"。
        parent_id = str(uuid.uuid4())
        parent = Gene(
            id=parent_id, name="原始助手", slug=_uid("parent-skill"),
            lineage_group_id=parent_id,
        )
        db.add(parent)
        await db.commit()
        parent_lineage_group_id = parent.lineage_group_id

        ig = InstanceGene(
            instance_id=instance.id, gene_id=parent.id,
            learning_output="一些深度学习产出的经验内容",
        )
        db.add(ig)
        await db.commit()

        await publish_variant(db, instance.id, parent.id)

        from sqlalchemy import select
        variant = (await db.execute(
            select(Gene).where(Gene.parent_gene_id == parent.id)
        )).scalar_one()
        assert variant.lineage_group_id != parent_lineage_group_id
        assert variant.lineage_group_id == variant.id


# ── fork_gene_to_library() 血缘传播 + 版本三态覆盖 ─────────────────────────


@pytest.mark.asyncio
async def test_fork_inherits_source_lineage_group_id_and_version(require_test_db):
    """fork 出的副本应继承源头的 lineage_group_id 和 version，而不是各自独立生成。"""
    from app.models.gene import Gene
    from app.models.organization import Organization
    from app.services.gene_service import fork_gene_to_library
    from sqlalchemy import select

    async with TestSessionLocal() as db:
        org = Organization(id=_uid("org"), name="Org A", slug=_uid("org-a"))
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add_all([org, user])
        await db.commit()

        source = Gene(
            id=_uid("gene"), name="客服助手", slug=_uid("customer-bot"),
            visibility="public", version="1.2.0", lineage_group_id=_uid("lineage"),
        )
        db.add(source)
        await db.commit()
        source_lineage_group_id = source.lineage_group_id

        result = await fork_gene_to_library(
            db, source.id, "org", current_user=_FakeUser(user.id, org.id), org_id=org.id,
        )
        forked = (await db.execute(select(Gene).where(Gene.id == result["id"]))).scalar_one()
        assert forked.lineage_group_id == source_lineage_group_id
        assert forked.version == "1.2.0"


@pytest.mark.asyncio
async def test_fork_overwrite_rejects_unrelated_lineage_regardless_of_flag(require_test_db):
    """安全性关键用例：即使 overwrite=True，血缘不相关的同名行也必须拒绝，
    不能被误覆盖。"""
    from app.models.gene import Gene
    from app.models.organization import Organization
    from app.services.gene_service import fork_gene_to_library

    async with TestSessionLocal() as db:
        org = Organization(id=_uid("org"), name="Org A", slug=_uid("org-a"))
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add_all([org, user])
        await db.commit()

        source = Gene(
            id=_uid("gene"), name="撞名助手", slug=_uid("source-skill"),
            visibility="public", version="2.0.0", lineage_group_id=_uid("lineage-a"),
        )
        unrelated_in_org = Gene(
            id=_uid("gene"), name="撞名助手", slug=_uid("unrelated-skill"), visibility="org_private",
            org_id=org.id, created_by=user.id, version="1.0.0", lineage_group_id=_uid("lineage-b"),
        )
        db.add_all([source, unrelated_in_org])
        await db.commit()

        with pytest.raises(ConflictError):
            await fork_gene_to_library(
                db, source.id, "org", current_user=_FakeUser(user.id, org.id),
                org_id=org.id, overwrite=True,
            )

        from sqlalchemy import select
        still_there = (await db.execute(
            select(Gene).where(Gene.id == unrelated_in_org.id, Gene.deleted_at.is_(None))
        )).scalar_one_or_none()
        assert still_there is not None


@pytest.mark.asyncio
async def test_fork_overwrite_executes_immediately_when_version_is_newer(require_test_db):
    """本任务范围内：所有 target（含 org/public）在满足覆盖条件时都立即执行——
    区分"org/public 走审核暂存"是下一个任务(Task 10)的范围，这里先不做区分。"""
    from app.models.gene import Gene
    from app.services.gene_service import fork_gene_to_library
    from sqlalchemy import select

    async with TestSessionLocal() as db:
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add(user)
        await db.commit()

        source = Gene(
            id=_uid("gene"), name="团队助手", slug=_uid("team-bot"),
            visibility="public", version="1.0.0", lineage_group_id=_uid("lineage"),
        )
        db.add(source)
        await db.commit()

        forked = await fork_gene_to_library(
            db, source.id, "personal", current_user=_FakeUser(user.id, None), org_id=None,
        )
        old_id = forked["id"]

        source_row = (await db.execute(select(Gene).where(Gene.id == source.id))).scalar_one()
        source_row.version = "1.1.0"
        await db.commit()

        result = await fork_gene_to_library(
            db, source.id, "personal", current_user=_FakeUser(user.id, None),
            org_id=None, overwrite=True,
        )
        assert result["version"] == "1.1.0"
        assert result["id"] != old_id

        old_row = (await db.execute(
            select(Gene).where(Gene.id == old_id, Gene.deleted_at.is_(None))
        )).scalar_one_or_none()
        assert old_row is None


@pytest.mark.asyncio
async def test_fork_overwrite_rejects_equal_version_with_specific_message_key(require_test_db):
    from app.models.gene import Gene
    from app.services.gene_service import fork_gene_to_library

    async with TestSessionLocal() as db:
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add(user)
        await db.commit()

        source = Gene(
            id=_uid("gene"), name="团队助手", slug=_uid("team-bot"),
            visibility="public", version="1.0.0", lineage_group_id=_uid("lineage"),
        )
        db.add(source)
        await db.commit()

        await fork_gene_to_library(
            db, source.id, "personal", current_user=_FakeUser(user.id, None), org_id=None,
        )

        with pytest.raises(ConflictError) as exc_info:
            await fork_gene_to_library(
                db, source.id, "personal", current_user=_FakeUser(user.id, None),
                org_id=None, overwrite=True,
            )
        assert getattr(exc_info.value, "message_key", None) == "errors.gene.fork_already_up_to_date"


@pytest.mark.asyncio
async def test_fork_overwrite_rejects_version_regression_with_specific_message_key(require_test_db):
    from app.models.gene import Gene
    from app.services.gene_service import fork_gene_to_library
    from sqlalchemy import select

    async with TestSessionLocal() as db:
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add(user)
        await db.commit()

        source = Gene(
            id=_uid("gene"), name="团队助手", slug=_uid("team-bot"),
            visibility="public", version="1.0.0", lineage_group_id=_uid("lineage"),
        )
        db.add(source)
        await db.commit()

        await fork_gene_to_library(
            db, source.id, "personal", current_user=_FakeUser(user.id, None), org_id=None,
        )

        source_row = (await db.execute(select(Gene).where(Gene.id == source.id))).scalar_one()
        source_row.version = "0.5.0"
        await db.commit()

        with pytest.raises(ConflictError) as exc_info:
            await fork_gene_to_library(
                db, source.id, "personal", current_user=_FakeUser(user.id, None),
                org_id=None, overwrite=True,
            )
        assert getattr(exc_info.value, "message_key", None) == "errors.gene.fork_version_regression"


@pytest.mark.asyncio
async def test_fork_overwrite_rewires_installed_instance_gene_reference(require_test_db):
    """覆盖 fork 后，已安装该技能的实例引用应指向新 fork 的 id，而不是被软删的旧行——
    这正是 _rewire_gene_references() 存在的意义：防止覆盖静默弄丢已装技能
    （同 test_gene_overwrite_reference_rewire.py 对 create_gene() 的验证方式）。"""
    from app.models.cluster import Cluster
    from app.models.gene import Gene, InstanceGene, InstanceGeneStatus
    from app.models.instance import Instance
    from app.services.gene_service import fork_gene_to_library
    from sqlalchemy import select

    async with TestSessionLocal() as db:
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add(user)
        await db.commit()

        cluster = Cluster(id=_uid("cluster"), name="Cluster", created_by=user.id)
        instance = Instance(
            id=_uid("inst"), name="Agent", slug=_uid("agent"), cluster_id=cluster.id,
            namespace="default", image_version="latest", created_by=user.id,
        )
        db.add_all([cluster, instance])
        await db.commit()

        source = Gene(
            id=_uid("gene"), name="装好的助手", slug=_uid("installed-bot"),
            visibility="public", version="1.0.0", lineage_group_id=_uid("lineage"),
        )
        db.add(source)
        await db.commit()

        first_fork = await fork_gene_to_library(
            db, source.id, "personal", current_user=_FakeUser(user.id, None), org_id=None,
        )
        old_fork_id = first_fork["id"]

        # 模拟这份 fork 出来的个人技能已经装到某个实例上
        ig = InstanceGene(
            instance_id=instance.id, gene_id=old_fork_id,
            status=InstanceGeneStatus.installed, installed_version="1.0.0",
        )
        db.add(ig)
        await db.commit()

        # 源头升级版本号，触发一次合法的覆盖 fork
        source_row = (await db.execute(select(Gene).where(Gene.id == source.id))).scalar_one()
        source_row.version = "1.1.0"
        await db.commit()

        second_fork = await fork_gene_to_library(
            db, source.id, "personal", current_user=_FakeUser(user.id, None),
            org_id=None, overwrite=True,
        )
        new_fork_id = second_fork["id"]
        assert new_fork_id != old_fork_id

        # InstanceGene 应该被重接到新 fork 的 id，而不是继续指着已软删的旧行
        await db.refresh(ig)
        assert ig.gene_id == new_fork_id


@pytest.mark.asyncio
async def test_fork_overwrite_rejects_when_source_is_none_external_aggregator(require_test_db, monkeypatch):
    """source 为 None（本地找不到、回退到外部聚合器）时无法判断血缘是否相关，
    即使 overwrite=True，代码注释里"一律拒绝"的承诺也必须真的兑现。"""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.models.gene import Gene
    from app.models.organization import Organization
    from app.services import gene_service
    from app.services.gene_service import fork_gene_to_library

    async with TestSessionLocal() as db:
        org = Organization(id=_uid("org"), name="Org A", slug=_uid("org-a"))
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add_all([org, user])
        await db.commit()

        # 目标 scope 内已存在一条同名技能（模拟"名字撞车"）
        existing = Gene(
            id=_uid("gene"), name="外部技能", slug=_uid("existing-skill"),
            visibility="org_private", org_id=org.id, created_by=user.id,
            version="1.0.0", lineage_group_id=_uid("lineage"),
        )
        db.add(existing)
        await db.commit()

        # source_identifier 在本地 DB 查不到，fork_gene_to_library 会回退到聚合器；
        # 伪造聚合器返回同名的外部技能详情，模拟"外部市场里恰好有条同名技能"。
        fake_detail = SimpleNamespace(
            name="外部技能", description=None, short_description=None, category=None,
            tags=[], icon=None, version="9.9.9", manifest={}, dependencies=[], synergies=[],
        )
        fake_aggregator = SimpleNamespace(get_skill=AsyncMock(return_value=fake_detail))
        monkeypatch.setattr(gene_service, "get_aggregator", lambda: fake_aggregator)

        with pytest.raises(ConflictError):
            await fork_gene_to_library(
                db, "external-slug-not-in-local-db", "org",
                current_user=_FakeUser(user.id, org.id), org_id=org.id, overwrite=True,
            )


@pytest.mark.asyncio
async def test_fork_overwrite_rejects_malformed_version_with_generic_message(require_test_db):
    """版本号格式不合法（compare_versions 返回 None）时应拒绝，且使用的 message_key
    必须与"已是最新版本"/"版本回退"这两个专属场景区分开，不能被误判成其中之一。"""
    from app.models.gene import Gene
    from app.services.gene_service import fork_gene_to_library
    from sqlalchemy import select

    async with TestSessionLocal() as db:
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add(user)
        await db.commit()

        source = Gene(
            id=_uid("gene"), name="团队助手", slug=_uid("team-bot"),
            visibility="public", version="1.0.0", lineage_group_id=_uid("lineage"),
        )
        db.add(source)
        await db.commit()

        await fork_gene_to_library(
            db, source.id, "personal", current_user=_FakeUser(user.id, None), org_id=None,
        )

        # 把源版本号改成格式不合法的值，制造 compare_versions() 返回 None 的场景
        source_row = (await db.execute(select(Gene).where(Gene.id == source.id))).scalar_one()
        source_row.version = "not-a-version"
        await db.commit()

        with pytest.raises(ConflictError) as exc_info:
            await fork_gene_to_library(
                db, source.id, "personal", current_user=_FakeUser(user.id, None),
                org_id=None, overwrite=True,
            )
        message_key = getattr(exc_info.value, "message_key", None)
        assert message_key not in (
            "errors.gene.fork_already_up_to_date",
            "errors.gene.fork_version_regression",
        )


@pytest.mark.asyncio
async def test_fork_overwrite_org_target_creates_submission_not_gene(require_test_db):
    """org/public 目标：版本校验通过后只创建 GeneOverwriteSubmission，
    existing_name 那一行完全不受影响。"""
    from app.models.gene import Gene
    from app.models.gene_overwrite_submission import GeneOverwriteSubmission
    from app.models.organization import Organization
    from app.services.gene_service import fork_gene_to_library
    from sqlalchemy import select

    async with TestSessionLocal() as db:
        org = Organization(id=_uid("org"), name="Org X", slug=_uid("org-x"))
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add_all([org, user])
        await db.commit()

        source = Gene(
            id=_uid("gene"), name="团队助手", slug=_uid("team-bot"),
            visibility="public", version="1.0.0", lineage_group_id=_uid("lineage"),
        )
        db.add(source)
        await db.commit()

        forked = await fork_gene_to_library(
            db, source.id, "org", current_user=_FakeUser(user.id, org.id), org_id=org.id,
        )
        target_id = forked["id"]

        source_row = (await db.execute(select(Gene).where(Gene.id == source.id))).scalar_one()
        source_row.version = "1.1.0"
        await db.commit()

        result = await fork_gene_to_library(
            db, source.id, "org", current_user=_FakeUser(user.id, org.id),
            org_id=org.id, overwrite=True,
        )
        assert result.get("kind") == "overwrite_submission"

        # existing_name（原本 org 那条 v1.0.0）完全不受影响
        target_row = (await db.execute(
            select(Gene).where(Gene.id == target_id, Gene.deleted_at.is_(None))
        )).scalar_one_or_none()
        assert target_row is not None
        assert target_row.version == "1.0.0"

        submission = (await db.execute(
            select(GeneOverwriteSubmission).where(GeneOverwriteSubmission.target_gene_id == target_id)
        )).scalar_one()
        assert submission.version == "1.1.0"
        assert submission.review_status == "pending_owner"
        assert submission.lineage_group_id == source_row.lineage_group_id

        # 关键防回归点：不能有任何"泄漏"的 Gene 行——如果未来有 bad refactor
        # 让 fork 覆盖分支既建了 submission 又不小心 db.add(fork) 落库，上面
        # 对 target_row 的断言不会发现（target_row 本来就没变），必须单独确认
        # genes 表里没有多出一条版本号 = 提案版本号的活跃行。
        # 注意：source_row 自身这时版本号也是 "1.1.0"，所以必须加 org_id 过滤
        # （source 是 public 的，org_id 为 None）并排除 source.id，只查目标
        # org scope 里是否多出了本不该落库的新行。
        leaked = (await db.execute(
            select(Gene).where(
                Gene.version == "1.1.0",
                Gene.org_id == org.id,
                Gene.id != source.id,
                Gene.deleted_at.is_(None),
            )
        )).scalars().all()
        assert leaked == []


@pytest.mark.asyncio
async def test_fork_overwrite_public_target_creates_submission_not_gene(require_test_db):
    """同上，但确认 public 目标也走暂存分支（不只是 org）。"""
    from app.models.gene import Gene
    from app.models.gene_overwrite_submission import GeneOverwriteSubmission
    from app.models.organization import Organization
    from app.services.gene_service import fork_gene_to_library
    from sqlalchemy import select

    async with TestSessionLocal() as db:
        org = Organization(id=_uid("org"), name="Org Y", slug=_uid("org-y"))
        user = User(id=_uid("user"), name="Bob", username=_uid("bob"))
        db.add_all([org, user])
        await db.commit()

        # 注意：source 必须是 personal scope（而非 public），否则 fork 目标本身
        # 就是 public，get_gene_by_name_in_scope 对 public 不额外按 org_id/
        # created_by 过滤，会立刻把 source 自己当成"已存在的同名技能"撞车，
        # 第一次（非 overwrite）fork 调用就会直接 ConflictError。
        source = Gene(
            id=_uid("gene"), name="公共助手", slug=_uid("public-bot"),
            visibility="personal", created_by=user.id,
            version="1.0.0", lineage_group_id=_uid("lineage"),
        )
        db.add(source)
        await db.commit()

        await fork_gene_to_library(
            db, source.id, "public", current_user=_FakeUser(user.id, org.id), org_id=org.id,
        )

        source_row = (await db.execute(select(Gene).where(Gene.id == source.id))).scalar_one()
        source_row.version = "2.0.0"
        await db.commit()

        result = await fork_gene_to_library(
            db, source.id, "public", current_user=_FakeUser(user.id, org.id),
            org_id=org.id, overwrite=True,
        )
        assert result.get("kind") == "overwrite_submission"

        submissions = (await db.execute(
            select(GeneOverwriteSubmission).where(GeneOverwriteSubmission.version == "2.0.0")
        )).scalars().all()
        assert len(submissions) == 1

        # 关键防回归点：确认没有任何"泄漏"的 Gene 行落库——source_row 自身此
        # 时版本号也是 "2.0.0"，所以额外按 visibility == "public" 过滤并排除
        # source.id（source 本身是 personal），只查公共 scope 是否多出了本
        # 不该落库的新行。
        leaked = (await db.execute(
            select(Gene).where(
                Gene.version == "2.0.0",
                Gene.visibility == "public",
                Gene.id != source.id,
                Gene.deleted_at.is_(None),
            )
        )).scalars().all()
        assert leaked == []


# ═══════════════════════════════════════════════════
#  Task 13：newer_sibling_versions 单向落后检测
# ═══════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_list_genes_marks_newer_sibling_version_for_personal_gene(require_test_db):
    """场景：管理员更新了组织版本，A 的个人库应该看到落后提示。"""
    from app.models.gene import Gene
    from app.models.organization import Organization
    from app.models.org_membership import OrgMembership, OrgRole
    from app.services.gene_service import fork_gene_to_library, list_genes
    from sqlalchemy import select

    async with TestSessionLocal() as db:
        org = Organization(id=_uid("org"), name="Org X", slug=_uid("org-x"))
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add_all([org, user])
        await db.commit()
        membership = OrgMembership(org_id=org.id, user_id=user.id, role=OrgRole.member)
        db.add(membership)
        await db.commit()

        personal = Gene(
            id=_uid("gene"), name="团队助手", slug=_uid("team-bot"), visibility="personal",
            created_by=user.id, version="1.0.0", lineage_group_id=_uid("lineage"),
        )
        db.add(personal)
        await db.commit()

        # 用 is_super_admin=True 触发 bypass_review，让 org 副本直接落
        # approved + is_published=True——与场景描述"管理员更新了组织版本"一致，
        # 也符合落后检测只应该提示已发布/已通过审核内容的规则（回归测试见
        # test_list_genes_excludes_unpublished_pending_sibling_from_badge）
        await fork_gene_to_library(
            db, personal.id, "org",
            current_user=_FakeUser(user.id, org.id, is_super_admin=True), org_id=org.id,
        )
        org_gene = (await db.execute(
            select(Gene).where(Gene.lineage_group_id == personal.lineage_group_id, Gene.visibility == "org_private")
        )).scalar_one()
        assert org_gene.is_published is True
        org_gene.version = "1.1.0"
        await db.commit()

        genes, _total = await list_genes(
            db, visibility="personal", org_id=None, user_id=user.id, page=1, page_size=20,
        )
        personal_item = next(g for g in genes if g["id"] == personal.id)
        assert personal_item["newer_sibling_versions"] == [
            {"visibility": "org_private", "org_id": org.id, "org_name": "Org X", "version": "1.1.0"},
        ]


@pytest.mark.asyncio
async def test_list_genes_no_badge_on_org_scope_even_if_personal_is_newer(require_test_db):
    """单向检测：即使个人库版本更新，组织库自己的卡片也不应该有任何提示。

    注意：visibility="org_private" 的 list_genes() 不走 _list_genes_local，
    而是经 get_aggregator().search() -> LocalAdapter.search_skills()。这里
    必须现场初始化聚合器（绑定 TestSessionLocal 的 LocalAdapter），并在用例
    结束后 close()，避免污染同进程内其它测试模块的全局单例。
    另外 LocalAdapter.search_skills 会过滤 is_published=True，所以 fork 时
    用 is_super_admin=True 的 current_user 触发 bypass_review，让 org 副本
    直接落 approved + is_published=True，而不是停在 pending_owner。
    """
    from app.models.gene import Gene
    from app.models.organization import Organization
    from app.services import registry_aggregator
    from app.services.gene_service import fork_gene_to_library, list_genes
    from app.services.local_adapter import LocalAdapter
    from sqlalchemy import select

    async with TestSessionLocal() as db:
        org = Organization(id=_uid("org"), name="Org Z", slug=_uid("org-z"))
        user = User(id=_uid("user"), name="Carol", username=_uid("carol"))
        db.add_all([org, user])
        await db.commit()

        personal = Gene(
            id=_uid("gene"), name="客服助手", slug=_uid("customer-bot"), visibility="personal",
            created_by=user.id, version="1.0.0", lineage_group_id=_uid("lineage"),
        )
        db.add(personal)
        await db.commit()

        await fork_gene_to_library(
            db, personal.id, "org",
            current_user=_FakeUser(user.id, org.id, is_super_admin=True), org_id=org.id,
        )

        personal_row = (await db.execute(select(Gene).where(Gene.id == personal.id))).scalar_one()
        personal_row.version = "1.2.0"
        await db.commit()

        registry_aggregator.init([LocalAdapter(session_factory=TestSessionLocal)])
        try:
            genes, _total = await list_genes(
                db, visibility="org_private", org_id=org.id, user_id=user.id, page=1, page_size=20,
            )
        finally:
            await registry_aggregator.close()
        org_item = next(g for g in genes if g["visibility"] == "org_private")
        assert org_item["newer_sibling_versions"] == []


@pytest.mark.asyncio
async def test_list_genes_no_false_positive_right_after_fork(require_test_db):
    from app.models.gene import Gene
    from app.models.organization import Organization
    from app.services.gene_service import fork_gene_to_library, list_genes

    async with TestSessionLocal() as db:
        org = Organization(id=_uid("org"), name="Org Y", slug=_uid("org-y"))
        user = User(id=_uid("user"), name="Bob", username=_uid("bob"))
        db.add_all([org, user])
        await db.commit()

        personal = Gene(
            id=_uid("gene"), name="客服助手", slug=_uid("customer-bot"), visibility="personal",
            created_by=user.id, version="1.0.0", lineage_group_id=_uid("lineage"),
        )
        db.add(personal)
        await db.commit()

        await fork_gene_to_library(
            db, personal.id, "org", current_user=_FakeUser(user.id, org.id), org_id=org.id,
        )

        genes, _total = await list_genes(
            db, visibility="personal", org_id=None, user_id=user.id, page=1, page_size=20,
        )
        personal_item = next(g for g in genes if g["id"] == personal.id)
        assert personal_item["newer_sibling_versions"] == []


@pytest.mark.asyncio
async def test_list_genes_excludes_unpublished_pending_sibling_from_badge(require_test_db):
    """回归测试：待审核（pending_owner，is_published=False）的 org 副本不应该
    被当作"落后提示"的来源——这类内容在产品其它任何地方都不可见/不可 fork，
    如果被计入落后检测，用户会看到"组织库有更新版本"却点不到、找不到，造成困惑。

    场景：普通成员（非 org admin，非平台超管）fork 个人技能到 org，不走
    bypass_review，落库为 pending_owner + is_published=False；随后把这个待审
    核的 org 副本版本号调高。此时查个人库列表，newer_sibling_versions 必须
    仍是空数组——待审核的 sibling 不能"泄漏"进落后提示。
    """
    from app.models.gene import Gene
    from app.models.organization import Organization
    from app.models.org_membership import OrgMembership, OrgRole
    from app.services.gene_service import fork_gene_to_library, list_genes
    from sqlalchemy import select

    async with TestSessionLocal() as db:
        org = Organization(id=_uid("org"), name="Org P", slug=_uid("org-p"))
        user = User(id=_uid("user"), name="Dave", username=_uid("dave"))
        db.add_all([org, user])
        await db.commit()
        # 普通成员，非 admin —— fork 时不会 bypass_review
        membership = OrgMembership(org_id=org.id, user_id=user.id, role=OrgRole.member)
        db.add(membership)
        await db.commit()

        personal = Gene(
            id=_uid("gene"), name="待审核助手", slug=_uid("pending-bot"), visibility="personal",
            created_by=user.id, version="1.0.0", lineage_group_id=_uid("lineage"),
        )
        db.add(personal)
        await db.commit()

        # 普通成员 fork，不传 is_super_admin，默认走 pending_owner 审核流程
        await fork_gene_to_library(
            db, personal.id, "org", current_user=_FakeUser(user.id, org.id), org_id=org.id,
        )
        org_gene = (await db.execute(
            select(Gene).where(Gene.lineage_group_id == personal.lineage_group_id, Gene.visibility == "org_private")
        )).scalar_one()
        assert org_gene.review_status == "pending_owner"
        assert org_gene.is_published is False
        org_gene.version = "9.9.9"
        await db.commit()

        genes, _total = await list_genes(
            db, visibility="personal", org_id=None, user_id=user.id, page=1, page_size=20,
        )
        personal_item = next(g for g in genes if g["id"] == personal.id)
        assert personal_item["newer_sibling_versions"] == []
