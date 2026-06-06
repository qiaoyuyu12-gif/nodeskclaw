"""RBAC 测试共享 fixtures。"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = "postgresql+asyncpg://nodeskclaw:nodeskclaw@localhost:5432/nodeskclaw_test"

engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False,
)


@pytest.fixture
async def require_test_db():
    """无 PostgreSQL 测试库时跳过用例。"""
    try:
        async with engine.connect():
            yield
    except Exception:
        pytest.skip("PostgreSQL test database is not available")


@pytest.fixture
def session_factory():
    """复用模块级 TestSessionLocal 作为 session_factory 给 seed 使用。"""
    return TestSessionLocal


@pytest.fixture(autouse=True)
def _clear_rbac_cache():
    """每个用例运行前清空 RBAC 进程缓存，避免上一用例残留状态。"""
    from app.core.rbac.cache import clear_all_caches

    clear_all_caches()
    yield
    clear_all_caches()
