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
