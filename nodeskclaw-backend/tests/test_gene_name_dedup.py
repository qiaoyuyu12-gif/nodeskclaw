"""验证 Gene 按 scope（personal/org/public）分别查重的逻辑。

背景：genes 表原本只有 (slug, org_id) 唯一约束，name 完全没有唯一性校验，
导致同一 scope 下可以出现多个同名但 slug 不同的技能。本文件覆盖：
  - get_gene_by_name_in_scope 按 scope 精确查重
  - create_gene 接入 name 查重（含 overwrite 场景、overwrite 误删无关行的修复）
  - fork_gene_to_library 接入 name 查重
  - publish_variant / handle_creation_callback 接入 name 查重（均默认落 public scope）
  - 并发竞态下 IntegrityError 被正确转换成 ConflictError

用真实 PostgreSQL 测试库（与 test_org_member_soft_delete.py 一致的模式），
因为要验证的是数据库唯一索引的真实约束行为，mock 掉 db 无法覆盖这一点。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.exceptions import ConflictError
from app.models.cluster import Cluster
from app.models.gene import Gene, InstanceGene
from app.models.instance import Instance
from app.models.organization import Organization
from app.models.user import User
from app.schemas.gene import GeneCreateRequest, LearningCallbackPayload
from app.services.gene_service import (
    create_gene,
    get_gene_by_name_in_scope,
    handle_creation_callback,
    publish_variant,
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


def _bare_gene(name: str, slug: str) -> Gene:
    """构造未经 create_gene() 的裸 Gene 行（测试夹具专用）。

    Gene.lineage_group_id 是 NOT NULL 列且没有 Column 级默认值，正常创建
    路径（create_gene()）会显式生成并写入；这里绕过该路径直接插入夹具数据，
    所以要自己生成 id 并把它同时用作 lineage_group_id（对这些测试而言，
    只是"占位的已存在技能"，具体取值无关紧要，只要满足 NOT NULL 即可）。
    """
    gene_id = str(uuid.uuid4())
    return Gene(id=gene_id, name=name, slug=slug, lineage_group_id=gene_id)


@pytest.mark.asyncio
async def test_get_gene_by_name_in_scope_returns_none_when_absent(require_test_db):
    async with TestSessionLocal() as db:
        result = await get_gene_by_name_in_scope(
            db, "不存在的技能", visibility="public",
        )
        assert result is None


def _minimal_req(name: str, slug: str, *, visibility: str = "public", overwrite: bool = False) -> GeneCreateRequest:
    return GeneCreateRequest(name=name, slug=slug, visibility=visibility, overwrite=overwrite)


@pytest.mark.asyncio
async def test_create_gene_rejects_duplicate_name_in_same_personal_scope(require_test_db):
    async with TestSessionLocal() as db:
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add(user)
        await db.commit()

        await create_gene(
            db, _minimal_req("客服助手", "customer-bot-1", visibility="personal"),
            user_id=user.id, org_id=None, visibility="personal",
        )

        with pytest.raises(ConflictError):
            await create_gene(
                db, _minimal_req(" 客服助手 ", "customer-bot-2", visibility="personal"),
                user_id=user.id, org_id=None, visibility="personal",
            )


@pytest.mark.asyncio
async def test_create_gene_allows_same_name_for_different_users_in_personal_scope(require_test_db):
    async with TestSessionLocal() as db:
        user_a = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        user_b = User(id=_uid("user"), name="Bob", username=_uid("bob"))
        db.add_all([user_a, user_b])
        await db.commit()

        await create_gene(
            db, _minimal_req("客服助手", "a-customer-bot", visibility="personal"),
            user_id=user_a.id, org_id=None, visibility="personal",
        )
        result = await create_gene(
            db, _minimal_req("客服助手", "b-customer-bot", visibility="personal"),
            user_id=user_b.id, org_id=None, visibility="personal",
        )
        assert result["name"] == "客服助手"


@pytest.mark.asyncio
async def test_create_gene_rejects_duplicate_name_in_same_org(require_test_db):
    async with TestSessionLocal() as db:
        org = Organization(id=_uid("org"), name="Org A", slug=_uid("org-a"))
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add_all([org, user])
        await db.commit()

        await create_gene(
            db, _minimal_req("团队助手", "team-bot-1", visibility="org_private"),
            user_id=user.id, org_id=org.id, visibility="org_private",
        )
        with pytest.raises(ConflictError):
            await create_gene(
                db, _minimal_req("团队助手", "team-bot-2", visibility="org_private"),
                user_id=user.id, org_id=org.id, visibility="org_private",
            )


@pytest.mark.asyncio
async def test_create_gene_allows_same_name_in_different_orgs(require_test_db):
    async with TestSessionLocal() as db:
        org_a = Organization(id=_uid("org"), name="Org A", slug=_uid("org-a"))
        org_b = Organization(id=_uid("org"), name="Org B", slug=_uid("org-b"))
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add_all([org_a, org_b, user])
        await db.commit()

        await create_gene(
            db, _minimal_req("团队助手", "a-team-bot", visibility="org_private"),
            user_id=user.id, org_id=org_a.id, visibility="org_private",
        )
        result = await create_gene(
            db, _minimal_req("团队助手", "b-team-bot", visibility="org_private"),
            user_id=user.id, org_id=org_b.id, visibility="org_private",
        )
        assert result["name"] == "团队助手"


@pytest.mark.asyncio
async def test_create_gene_rejects_duplicate_name_in_public_market(require_test_db):
    async with TestSessionLocal() as db:
        org = Organization(id=_uid("org"), name="Org A", slug=_uid("org-a"))
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add_all([org, user])
        await db.commit()

        await create_gene(
            db, _minimal_req("公开助手", "public-bot-1", visibility="public"),
            user_id=user.id, org_id=org.id, visibility="public",
        )
        with pytest.raises(ConflictError):
            await create_gene(
                db, _minimal_req("公开助手", "public-bot-2", visibility="public"),
                user_id=user.id, org_id=org.id, visibility="public",
            )


@pytest.mark.asyncio
async def test_create_gene_overwrite_allows_same_name(require_test_db):
    async with TestSessionLocal() as db:
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add(user)
        await db.commit()

        await create_gene(
            db, _minimal_req("客服助手", "customer-bot", visibility="personal"),
            user_id=user.id, org_id=None, visibility="personal",
        )
        result = await create_gene(
            db, _minimal_req("客服助手", "customer-bot", visibility="personal", overwrite=True),
            user_id=user.id, org_id=None, visibility="personal",
        )
        assert result["name"] == "客服助手"


@pytest.mark.asyncio
async def test_create_gene_integrity_error_on_commit_becomes_conflict_error(require_test_db, monkeypatch):
    """模拟并发竞态：预检查都通过后，commit 阶段才因唯一索引冲突而失败。"""
    from app.services import gene_service

    async with TestSessionLocal() as db:
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add(user)
        await db.commit()

        async def _boom():
            from sqlalchemy.exc import IntegrityError
            raise IntegrityError("INSERT", {}, Exception("uq_genes_name_personal_active"))

        monkeypatch.setattr(db, "commit", _boom)

        with pytest.raises(ConflictError):
            await create_gene(
                db, _minimal_req("竞态助手", "race-bot", visibility="personal"),
                user_id=user.id, org_id=None, visibility="personal",
            )


@pytest.mark.asyncio
async def test_create_gene_overwrite_rejects_when_name_hits_unrelated_row(require_test_db):
    """overwrite 分支修复验证：slug 命中行 A、name 命中另一条完全无关的行 B 时，

    即使 overwrite=True 也应该直接 ConflictError，而不能把 B 也顺带软删——
    覆盖的语义只是"允许覆盖 slug 命中的那一条"，不是"允许清空所有名字冲突"。
    """
    async with TestSessionLocal() as db:
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add(user)
        await db.commit()

        # 行 A：本次覆盖请求的 slug 命中目标
        await create_gene(
            db, _minimal_req("原名助手", "row-a", visibility="personal"),
            user_id=user.id, org_id=None, visibility="personal",
        )
        # 行 B：与本次请求的 name 撞车，但 slug 完全不同，与覆盖目标无关
        await create_gene(
            db, _minimal_req("撞车助手", "row-b", visibility="personal"),
            user_id=user.id, org_id=None, visibility="personal",
        )

        with pytest.raises(ConflictError):
            await create_gene(
                db, _minimal_req("撞车助手", "row-a", visibility="personal", overwrite=True),
                user_id=user.id, org_id=None, visibility="personal",
            )

        # 行 B 没有被误删：按 name 查重仍能命中该行（未软删）
        still_there = await get_gene_by_name_in_scope(
            db, "撞车助手", visibility="personal", created_by=user.id,
        )
        assert still_there is not None


@pytest.mark.asyncio
async def test_create_gene_overwrite_succeeds_when_only_name_hits_no_slug_match(require_test_db):
    """真实场景复现：旧记录的 slug 是通过别的入口（如手动创建）生成的，与本次

    上传按名称推导出的 slug 对不上——slug 查不到任何行（existing=None），
    但按 name 能精确命中这条旧记录（existing_name 非空）。此时 existing_name
    就是唯一需要覆盖的目标，不是"无关行"，overwrite=True 应该成功软删旧行
    并插入新行，而不是报 ConflictError（此前的回归 bug：见用户反馈"点击同意
    覆盖后仍然提示同名已存在，拒绝上传"）。
    """
    async with TestSessionLocal() as db:
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add(user)
        await db.commit()

        # 旧记录：slug 是手动指定的，与后续按 name 生成的 slug 不同
        await create_gene(
            db, _minimal_req("客服助手", "manual-custom-slug", visibility="personal"),
            user_id=user.id, org_id=None, visibility="personal",
        )

        # 重新上传：slug 按名称重新生成，和旧记录的 slug 对不上，但 name 相同
        result = await create_gene(
            db, _minimal_req("客服助手", "customer-bot-regenerated", visibility="personal", overwrite=True),
            user_id=user.id, org_id=None, visibility="personal",
        )
        assert result["name"] == "客服助手"
        assert result["slug"] == "customer-bot-regenerated"

        # 旧记录已被软删，不再能通过 name 查重命中（新记录才是唯一存活的一条）
        current = await get_gene_by_name_in_scope(
            db, "客服助手", visibility="personal", created_by=user.id,
        )
        assert current is not None
        assert current.slug == "customer-bot-regenerated"


async def _create_instance(db: AsyncSession, user: User) -> Instance:
    """构造 publish_variant / handle_creation_callback 测试所需的最小可用 Instance。

    两个函数都只依赖 instance_id 做外键校验和日志记录，不依赖 Instance 的业务
    字段，因此这里只填满 DB 层非空约束要求的最小字段集。
    """
    cluster = Cluster(id=_uid("cluster"), name="Cluster", created_by=user.id)
    instance = Instance(
        id=_uid("inst"),
        name="Agent",
        slug=_uid("agent"),
        cluster_id=cluster.id,
        namespace="default",
        image_version="latest",
        created_by=user.id,
    )
    db.add_all([cluster, instance])
    await db.commit()
    return instance


@pytest.mark.asyncio
async def test_publish_variant_rejects_duplicate_name_in_public_scope(require_test_db):
    """publish_variant 插入的变体未显式传 visibility，落在默认 public scope，

    若目标名称与 public scope 内已有的技能重名，应直接 ConflictError，
    而不是静默创建出一条重名记录（Task 6 Step 1 补齐的遗漏入口）。
    """
    async with TestSessionLocal() as db:
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add(user)
        await db.commit()
        instance = await _create_instance(db, user)

        # 已存在的公共基因，占用了即将发布的变体名称
        occupied_name = f"进化助手-{_uid('n')}"
        existing_public = _bare_gene(occupied_name, _uid("existing-public"))
        db.add(existing_public)
        await db.commit()

        # 待发布变体所属的父基因
        parent = _bare_gene(f"原始助手-{_uid('n')}", _uid("parent-skill"))
        db.add(parent)
        await db.commit()

        ig = InstanceGene(
            instance_id=instance.id,
            gene_id=parent.id,
            learning_output="一些深度学习产出的经验内容",
        )
        db.add(ig)
        await db.commit()

        with pytest.raises(ConflictError):
            await publish_variant(
                db, instance.id, parent.id, variant_name=occupied_name,
            )


@pytest.mark.asyncio
async def test_creation_callback_rejects_duplicate_name_in_public_scope(require_test_db):
    """handle_creation_callback 插入的 gene 同样未显式传 visibility，落在默认

    public scope，命中已有同名技能时应直接 ConflictError（Task 6 Step 2
    补齐的遗漏入口）。
    """
    async with TestSessionLocal() as db:
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add(user)
        await db.commit()
        instance = await _create_instance(db, user)

        occupied_name = f"智能助理-{_uid('n')}"
        existing_public = _bare_gene(occupied_name, _uid("existing-public"))
        db.add(existing_public)
        await db.commit()

        payload = LearningCallbackPayload(
            task_id=_uid("task"),
            instance_id=instance.id,
            mode="create",
            decision="created",
            content="正文内容",
            meta={
                "gene_name": occupied_name,
                "gene_slug": _uid("new-gene-slug"),
                "gene_description": "一段用于满足元数据校验的描述",
            },
        )

        with pytest.raises(ConflictError):
            await handle_creation_callback(db, payload)


@pytest.mark.asyncio
async def test_publish_variant_integrity_error_on_commit_becomes_conflict_error(require_test_db, monkeypatch):
    """模拟并发竞态：publish_variant 的名称预检查通过后，commit 阶段才因唯一

    索引冲突而失败，验证 Task 6 Step 1 补齐的 IntegrityError 兜底生效
    （对比 create_gene 已有的同类竞态测试）。
    """
    async with TestSessionLocal() as db:
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add(user)
        await db.commit()
        instance = await _create_instance(db, user)

        parent = _bare_gene(f"原始助手-{_uid('n')}", _uid("parent-skill"))
        db.add(parent)
        await db.commit()

        ig = InstanceGene(
            instance_id=instance.id,
            gene_id=parent.id,
            learning_output="一些深度学习产出的经验内容",
        )
        db.add(ig)
        await db.commit()

        async def _boom():
            from sqlalchemy.exc import IntegrityError
            raise IntegrityError("INSERT", {}, Exception("uq_genes_name_public_active"))

        monkeypatch.setattr(db, "commit", _boom)

        with pytest.raises(ConflictError):
            await publish_variant(db, instance.id, parent.id)
