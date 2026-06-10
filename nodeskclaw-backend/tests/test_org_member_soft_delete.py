from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.exceptions import NotFoundError
from app.models.org_membership import OrgMembership, OrgRole
from app.models.organization import Organization
from app.models.user import User
from app.services.org_service import list_members, update_member_role

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


@pytest.mark.asyncio
async def test_list_members_excludes_soft_deleted_users(require_test_db):
    async with TestSessionLocal() as db:
        org = Organization(id="org-soft-delete", name="Soft Delete Org", slug="org-soft-delete")
        active_user = User(id="user-active", name="Active", username="active")
        deleted_user = User(
            id="user-deleted",
            name="Deleted",
            username="deleted",
            deleted_at=datetime.now(timezone.utc),
        )
        active_membership = OrgMembership(
            id="membership-active",
            user_id=active_user.id,
            org_id=org.id,
            role=OrgRole.member,
        )
        deleted_membership = OrgMembership(
            id="membership-deleted",
            user_id=deleted_user.id,
            org_id=org.id,
            role=OrgRole.member,
        )
        db.add_all([org, active_user, deleted_user, active_membership, deleted_membership])
        await db.commit()

        members = await list_members(org.id, db)

        assert [member.user_id for member in members] == ["user-active"]


@pytest.mark.asyncio
async def test_update_member_role_rejects_soft_deleted_user_membership(require_test_db):
    async with TestSessionLocal() as db:
        org = Organization(id="org-soft-delete-role", name="Soft Delete Role", slug="org-soft-delete-role")
        deleted_user = User(
            id="user-deleted-role",
            name="Deleted Role",
            username="deleted-role",
            deleted_at=datetime.now(timezone.utc),
        )
        membership = OrgMembership(
            id="membership-deleted-role",
            user_id=deleted_user.id,
            org_id=org.id,
            role=OrgRole.member,
        )
        db.add_all([org, deleted_user, membership])
        await db.commit()

        with pytest.raises(NotFoundError, match="成员记录不存在"):
            await update_member_role(org.id, membership.id, OrgRole.admin, db)
