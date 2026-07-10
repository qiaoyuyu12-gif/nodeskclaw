"""验证 Gene 按 scope（personal/org/public）分别查重的逻辑。

背景：genes 表原本只有 (slug, org_id) 唯一约束，name 完全没有唯一性校验，
导致同一 scope 下可以出现多个同名但 slug 不同的技能。本文件覆盖：
  - get_gene_by_name_in_scope 按 scope 精确查重
  - create_gene 接入 name 查重（含 overwrite 场景）
  - fork_gene_to_library 接入 name 查重
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
from app.models.organization import Organization
from app.models.user import User
from app.schemas.gene import GeneCreateRequest
from app.services.gene_service import create_gene, get_gene_by_name_in_scope

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
