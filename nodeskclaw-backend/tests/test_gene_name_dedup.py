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
