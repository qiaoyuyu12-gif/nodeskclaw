from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base
from app.models.cluster import Cluster
from app.models.organization import Organization
from app.models.user import User
from app.models.workspace_schedule import WorkspaceSchedule
from app.schemas.workspace import WorkspaceCreate
from app.services.workspace_defaults import (
    DEFAULT_WORKSPACE_SCHEDULE_MESSAGE,
    DEFAULT_WORKSPACE_SCHEDULE_NAME,
)
from app.services.workspace_service import create_workspace

TEST_DATABASE_URL = "postgresql+asyncpg://nodeskclaw:nodeskclaw123@localhost:5432/nodeskclaw_rbac_test"

engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(scope="module", autouse=True)
async def setup_db():
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception:
        yield False
        return

    yield True

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.mark.asyncio
async def test_create_workspace_uses_neutral_default_schedule_copy(setup_db):
    if not setup_db:
        pytest.skip("test database unavailable")

    suffix = uuid4().hex[:8]
    async with TestSessionLocal() as db:
        org = Organization(id=f"org-workspace-{suffix}", name="Workspace Org", slug=f"workspace-org-{suffix}")
        user = User(
            id=f"user-workspace-{suffix}",
            name="Workspace User",
            email=f"workspace-{suffix}@example.com",
            username=f"workspace-{suffix}",
            password_hash="x",
        )
        cluster = Cluster(
            id=f"cluster-workspace-{suffix}",
            org_id=org.id,
            name="Test Cluster",
            compute_provider="k8s",
            created_by=user.id,
        )
        db.add_all([org, user, cluster])
        await db.commit()

        workspace = await create_workspace(
            db,
            org.id,
            user.id,
            WorkspaceCreate(name="Workspace", description="", color="#000000", icon="bot", cluster_id=cluster.id),
        )

        result = await db.execute(
            select(WorkspaceSchedule).where(
                WorkspaceSchedule.workspace_id == workspace.id,
                WorkspaceSchedule.deleted_at.is_(None),
            )
        )
        schedule = result.scalar_one()

        assert schedule.name == DEFAULT_WORKSPACE_SCHEDULE_NAME
        assert schedule.message_template == DEFAULT_WORKSPACE_SCHEDULE_MESSAGE
