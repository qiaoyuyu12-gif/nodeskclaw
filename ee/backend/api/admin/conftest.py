"""Admin API 测试共用 fixtures。

提供 async_client（挂载 FastAPI app + override get_db）、
super_admin_token、normal_user_token。
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio

# 将 nodeskclaw-backend 插入 sys.path，使 'app' 包可被 import
_BACKEND_DIR = Path(__file__).resolve().parents[4] / "nodeskclaw-backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import uuid

from app.core.deps import get_db
from app.core.security import create_access_token
from app.main import app
from app.models import Base
from app.models.organization import Organization
from app.models.user import User

TEST_DATABASE_URL = "postgresql+asyncpg://nodeskclaw:nodeskclaw@localhost:5432/nodeskclaw_test"

# NullPool：每次操作独立连接，避免 asyncpg 连接状态冲突
engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
TestSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(scope="session")
def event_loop():
    """全局共享事件循环，避免 session-scoped fixture 冲突。"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def create_tables():
    """session 级别：只建一次表，结束时删除。"""
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception:
        pass
    yield
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    except Exception:
        pass


@pytest_asyncio.fixture(autouse=True)
async def truncate_tables():
    """每个测试后 TRUNCATE 所有表（CASCADE 处理循环外键），保证隔离。"""
    yield
    try:
        async with engine.begin() as conn:
            # 一次性列出所有表名 + CASCADE，PostgreSQL 自动处理依赖顺序
            table_names = ", ".join(
                f'"{t.name}"' for t in Base.metadata.tables.values()
            )
            if table_names:
                await conn.execute(text(f"TRUNCATE {table_names} CASCADE"))
    except Exception:
        pass


async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
    """将 FastAPI get_db 替换为测试 session。"""
    async with TestSessionLocal() as session:
        yield session


# 覆盖 FastAPI app 的 get_db 依赖
app.dependency_overrides[get_db] = _override_get_db


@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """挂载 ASGI app 的异步 HTTP 客户端。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def super_admin_user() -> User:
    """创建并持久化一个超管用户。"""
    async with TestSessionLocal() as session:
        user = User(
            name="Super Admin",
            email="super@example.com",
            username="superadmin",
            is_super_admin=True,
            is_active=True,
            role="admin",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest_asyncio.fixture
async def normal_user() -> User:
    """创建并持久化一个普通用户。"""
    async with TestSessionLocal() as session:
        user = User(
            name="Normal User",
            email="normal@example.com",
            username="normaluser",
            is_super_admin=False,
            is_active=True,
            role="user",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest.fixture
def super_admin_token(super_admin_user: User) -> str:
    """超管 JWT token。"""
    return create_access_token(user_id=super_admin_user.id)


@pytest.fixture
def normal_user_token(normal_user: User) -> str:
    """普通用户 JWT token。"""
    return create_access_token(user_id=normal_user.id)


@pytest_asyncio.fixture
async def sample_org() -> Organization:
    """创建并持久化一个测试组织，供成员管理 endpoint 测试使用。"""
    async with TestSessionLocal() as session:
        org = Organization(
            name="Test Org",
            slug=f"test-org-{uuid.uuid4().hex[:8]}",
            plan="free",
            max_instances=1,
            max_cpu_total="4",
            max_mem_total="8Gi",
            max_storage_total="500Gi",
            max_collaboration_depth=3,
            is_active=True,
        )
        session.add(org)
        await session.commit()
        await session.refresh(org)
        return org


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """提供直接访问测试数据库的 AsyncSession（独立 session，不走 app 依赖注入）。"""
    async with TestSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def sample_user() -> User:
    """创建并持久化一个普通用户，供成员管理 endpoint 测试使用。"""
    async with TestSessionLocal() as session:
        user = User(
            id=str(uuid.uuid4()),
            name="Sample User",
            email=f"user-{uuid.uuid4().hex[:8]}@example.com",
            password_hash="not-a-real-hash",
            is_active=True,
            is_super_admin=False,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user
