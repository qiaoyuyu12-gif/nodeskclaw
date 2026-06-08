"""RBAC 测试共享 fixtures。"""

import os

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# 优先读 TEST_DATABASE_URL 环境变量（兼容 docker compose 自定义密码）；
# 否则回退到与项目顶层 conftest 一致的硬编码默认值
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://nodeskclaw:nodeskclaw@localhost:5432/nodeskclaw_test",
)

# 用 NullPool 避免连接跨事件循环复用（pytest-asyncio 每个用例一个新 loop，
# 复用的 asyncpg 连接会触发 'cannot perform operation: another operation
# in progress' 错误）。每个用例的 fixture 入口都会新建 engine。
_TEST_ENGINE = None
TestSessionLocal: async_sessionmaker[AsyncSession] | None = None


def _make_engine():
    """生成新 engine + session_factory，绑定到当前事件循环。"""
    global _TEST_ENGINE, TestSessionLocal
    _TEST_ENGINE = create_async_engine(
        TEST_DATABASE_URL, echo=False, poolclass=NullPool,
    )
    TestSessionLocal = async_sessionmaker(
        _TEST_ENGINE, class_=AsyncSession, expire_on_commit=False,
    )
    return _TEST_ENGINE


# 占位：模块导入时先建一个，让测试代码可以 `from tests.rbac.conftest import TestSessionLocal`
_make_engine()


@pytest.fixture
async def require_test_db():
    """无 PostgreSQL 测试库时跳过用例；可用时为当前用例重建 schema + engine。

    用 raw SQL DROP SCHEMA public CASCADE 绕开 SQLAlchemy 因循环 FK 排序问题。
    每个用例独立新建 engine 避免 pytest-asyncio 跨 loop 复用 asyncpg 连接。
    """
    from sqlalchemy import text

    from app.models import Base

    engine = _make_engine()
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"PostgreSQL test database is not available: {exc}")

    try:
        yield
    finally:
        try:
            async with engine.begin() as conn:
                await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
                await conn.execute(text("CREATE SCHEMA public"))
        except Exception:
            pass
        await engine.dispose()


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
