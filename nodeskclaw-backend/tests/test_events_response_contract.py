from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.security import get_current_user
from app.main import app
from app.models import Base
from app.models.admin_membership import AdminMembership
from app.models.organization import Organization
from app.models.user import User

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


@pytest.fixture
async def admin_user(setup_db):
    if not setup_db:
        pytest.skip("test database unavailable")

    suffix = uuid4().hex[:8]
    org = Organization(id=f"org-events-{suffix}", name="Events Org", slug=f"events-org-{suffix}")
    user = User(
        id=f"user-events-{suffix}",
        name="Events Admin",
        email=f"events-{suffix}@example.com",
        username=f"events-{suffix}",
        password_hash="x",
        current_org_id=org.id,
    )
    membership = AdminMembership(
        id=f"admin-events-{suffix}",
        user_id=user.id,
        org_id=org.id,
        role="member",
    )
    async with TestSessionLocal() as db:
        db.add_all([org, user, membership])
        await db.commit()
    return user, org


@pytest.mark.asyncio
async def test_admin_events_recent_returns_api_response_for_non_k8s_cluster(client, admin_user):
    user, _org = admin_user
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        with patch(
            "app.api.events.cluster_service.get_cluster",
            new=AsyncMock(return_value=SimpleNamespace(is_k8s=False)),
        ):
            response = await client.get("/api/v1/admin/events/recent", params={"cluster_id": "cluster-1"})
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200
    assert response.json() == {
        "code": 0,
        "error_code": None,
        "message_key": None,
        "message": "success",
        "data": [],
    }


@pytest.mark.asyncio
async def test_portal_events_recent_returns_api_response_for_non_k8s_cluster(client):
    user = SimpleNamespace(id="user-portal")
    org = SimpleNamespace(id="org-portal")
    from app.core.deps import get_current_org

    app.dependency_overrides[get_current_org] = lambda: (user, org)
    try:
        with patch(
            "app.api.portal.events.cluster_service.get_cluster",
            new=AsyncMock(return_value=SimpleNamespace(is_k8s=False)),
        ):
            response = await client.get("/api/v1/events/recent", params={"cluster_id": "cluster-1"})
    finally:
        app.dependency_overrides.pop(get_current_org, None)

    assert response.status_code == 200
    assert response.json() == {
        "code": 0,
        "error_code": None,
        "message_key": None,
        "message": "success",
        "data": [],
    }
