"""超管 service 测试 fixtures。

提供 db_session、super_admin_user 与 sample_org，供 T4/T5/T6/T8 等 admin service 测试复用。
每个测试函数使用独立 engine + session，避免跨 event loop 的连接池污染。

设计说明：
  - 每个 db_session fixture 内部独立创建 engine，避免模块级 engine
    在 function-scope event loop 切换时出现 "cannot perform operation" 错误
  - 不使用 drop_all：全量模型存在循环外键依赖，drop_all 会报 CircularDependencyError
    改用 TRUNCATE ... CASCADE 只清关联表，保留 schema
  - 不定义 event_loop fixture：pytest-asyncio 1.3.0+ 已废弃该做法
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# 导入所有 model，确保 metadata 完整（用于 create_all）
import app.models  # noqa: F401
from app.models.base import Base
from app.models.cluster import Cluster
from app.models.instance import Instance, InstanceStatus
from app.models.organization import Organization
from app.models.user import User

# 与 nodeskclaw-backend/tests/conftest.py 使用同一测试库 URL
TEST_DATABASE_URL = "postgresql+asyncpg://nodeskclaw:nodeskclaw@localhost:5432/nodeskclaw_test"

# 需要在每个用例前后清理的表（CASCADE 自动处理外键引用顺序）
# instances 先于 clusters / organizations，防止外键约束报错
_TRUNCATE_TABLES = [
    "organization_feature_overrides",
    "operation_audit_logs",
    "instances",
    "clusters",
    "organizations",
    "users",
]


@pytest_asyncio.fixture(loop_scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """每个测试用例独立创建 engine + session，避免跨 loop 连接池状态残留。

    首次 create_all（幂等），清理用 TRUNCATE CASCADE。
    """
    # 每次 fixture 调用创建独立 engine，绑定到当前 event loop
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)  # noqa: N806

    # 幂等建表（已存在时跳过）
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 每次测试前先清理残留数据，保证隔离
    async with engine.begin() as conn:
        for table in _TRUNCATE_TABLES:
            await conn.execute(text(f'TRUNCATE TABLE "{table}" CASCADE'))  # noqa: S608

    # 提供 session 给测试函数
    async with SessionLocal() as session:
        yield session
        await session.rollback()

    # 关闭 engine，释放连接池（当前 loop 即将结束）
    await engine.dispose()


@pytest_asyncio.fixture(loop_scope="function")
async def super_admin_user(db_session: AsyncSession) -> User:
    """落库一个超管用户，用于审计测试的 actor 参数。

    每次生成随机 email 避免唯一约束冲突。
    """
    user = User(
        id=str(uuid.uuid4()),
        name="Super Admin",
        email=f"superadmin-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="not-a-real-hash",
        is_active=True,
        is_super_admin=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture(loop_scope="function")
async def sample_org(db_session: AsyncSession) -> Organization:
    """落库一个测试组织，用于 feature override 测试。

    每次生成随机 slug 避免唯一约束冲突。
    """
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
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    return org


@pytest_asyncio.fixture(loop_scope="function")
async def sample_org_with_running_instance(
    db_session: AsyncSession,
    super_admin_user: User,
) -> Organization:
    """落库一个含运行中实例的测试组织，用于校验删除拦截逻辑。

    创建步骤：
      1. 创建 Organization
      2. 创建 Cluster（Instance.cluster_id 为 NOT NULL 外键）
      3. 创建 Instance，status=running，关联到 org 与 cluster
    测试结束由 conftest 的 TRUNCATE 统一清理（instances → clusters → organizations）。
    """
    # 1. 组织
    org = Organization(
        name="Org With Running Instance",
        slug=f"org-running-{uuid.uuid4().hex[:8]}",
        plan="free",
        max_instances=5,
        max_cpu_total="16",
        max_mem_total="32Gi",
        max_storage_total="1Ti",
        max_collaboration_depth=3,
        is_active=True,
    )
    db_session.add(org)
    await db_session.flush()  # 获取 org.id，暂不 commit

    # 2. 集群（Instance.cluster_id NOT NULL 外键）
    cluster = Cluster(
        id=str(uuid.uuid4()),
        name=f"test-cluster-{uuid.uuid4().hex[:8]}",
        compute_provider="k8s",
        status="connected",
        created_by=super_admin_user.id,
        provider_config={},
    )
    db_session.add(cluster)
    await db_session.flush()

    # 3. 运行中实例（填充所有 NOT NULL 列）
    instance = Instance(
        id=str(uuid.uuid4()),
        name="running-instance",
        slug=f"running-{uuid.uuid4().hex[:8]}",
        cluster_id=cluster.id,
        namespace="test-ns",
        image_version="latest",
        replicas=1,
        cpu_request="500m",
        cpu_limit="2000m",
        mem_request="2Gi",
        mem_limit="2Gi",
        service_type="ClusterIP",
        quota_cpu="4",
        quota_mem="8Gi",
        quota_max_pods=20,
        storage_size="80Gi",
        available_replicas=1,
        status=InstanceStatus.running,
        health_status="healthy",
        current_revision=1,
        compute_provider="k8s",
        runtime="openclaw",
        created_by=super_admin_user.id,
        org_id=org.id,
    )
    db_session.add(instance)
    await db_session.commit()
    await db_session.refresh(org)
    return org
