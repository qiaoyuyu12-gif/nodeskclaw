"""RBAC 双写适配器 grant_role / revoke_role / replace_role 幂等行为。"""

import pytest
from sqlalchemy import func, select

from app.core.rbac.cache import get_cached_grants, set_cached_grants
from app.models.organization import Organization
from app.models.rbac.subject_role import SubjectRole
from app.models.user import User
from app.services.rbac_sync import grant_role, replace_role, revoke_role
from app.startup.seed_rbac import seed_rbac

from tests.rbac.conftest import TestSessionLocal


@pytest.mark.asyncio
async def test_grant_role_idempotent(require_test_db, session_factory):
    """连续 3 次 grant_role 只产生 1 条 subject_roles。"""
    await seed_rbac(session_factory)
    async with TestSessionLocal() as db:
        org = Organization(id="org-grant", name="Grant Org", slug="org-grant")
        user = User(id="user-grant", name="Grant", username="grant-test")
        db.add_all([org, user])
        await db.flush()

        for _ in range(3):
            await grant_role(
                db, subject_type="user", subject_id="user-grant",
                role_key="org_admin", scope_type="org", scope_id="org-grant",
                granted_reason="test_idempotent",
            )
        await db.commit()

        count = (await db.execute(
            select(func.count()).select_from(SubjectRole).where(
                SubjectRole.subject_id == "user-grant",
                SubjectRole.deleted_at.is_(None),
            )
        )).scalar_one()
        assert count == 1


@pytest.mark.asyncio
async def test_grant_role_invalidates_cache(require_test_db, session_factory):
    """grant_role 后该 subject 的缓存被失效。"""
    await seed_rbac(session_factory)
    async with TestSessionLocal() as db:
        org = Organization(
            id="org-grant-cache", name="Cache Org", slug="org-grant-cache",
        )
        user = User(
            id="user-grant-cache", name="C", username="grant-cache-test",
        )
        db.add_all([org, user])
        await db.flush()

        # 预先写入虚假缓存
        set_cached_grants(
            "user", "user-grant-cache", [("stale_role", "org", "org-grant-cache")],
        )
        assert get_cached_grants("user", "user-grant-cache") is not None

        await grant_role(
            db, subject_type="user", subject_id="user-grant-cache",
            role_key="org_member", scope_type="org", scope_id="org-grant-cache",
            granted_reason="test_cache_invalidate",
        )
        # 缓存被 invalidate_subject 清掉
        assert get_cached_grants("user", "user-grant-cache") is None


@pytest.mark.asyncio
async def test_revoke_role_soft_deletes(require_test_db, session_factory):
    """revoke_role 软删 SubjectRole，再 grant 同一角色应重新创建一条。"""
    await seed_rbac(session_factory)
    async with TestSessionLocal() as db:
        org = Organization(
            id="org-revoke", name="Revoke Org", slug="org-revoke",
        )
        user = User(id="user-revoke", name="R", username="revoke-test")
        db.add_all([org, user])
        await db.flush()

        await grant_role(
            db, subject_type="user", subject_id="user-revoke",
            role_key="org_member", scope_type="org", scope_id="org-revoke",
            granted_reason="test_revoke",
        )
        await db.commit()

        await revoke_role(
            db, subject_type="user", subject_id="user-revoke",
            role_key="org_member", scope_type="org", scope_id="org-revoke",
        )
        await db.commit()

        active = (await db.execute(
            select(func.count()).select_from(SubjectRole).where(
                SubjectRole.subject_id == "user-revoke",
                SubjectRole.deleted_at.is_(None),
            )
        )).scalar_one()
        assert active == 0


@pytest.mark.asyncio
async def test_revoke_unknown_grant_no_error(require_test_db, session_factory):
    """revoke 找不到对应授权时不应抛错。"""
    await seed_rbac(session_factory)
    async with TestSessionLocal() as db:
        await revoke_role(
            db, subject_type="user", subject_id="non-existent",
            role_key="org_member", scope_type="org", scope_id="org-fake",
        )
        await db.commit()


@pytest.mark.asyncio
async def test_replace_role_atomic(require_test_db, session_factory):
    """replace_role 从 org_member → org_admin。"""
    await seed_rbac(session_factory)
    async with TestSessionLocal() as db:
        org = Organization(
            id="org-replace", name="Replace Org", slug="org-replace",
        )
        user = User(id="user-replace", name="R", username="replace-test")
        db.add_all([org, user])
        await db.flush()

        await grant_role(
            db, subject_type="user", subject_id="user-replace",
            role_key="org_member", scope_type="org", scope_id="org-replace",
            granted_reason="initial",
        )
        await db.commit()

        await replace_role(
            db, subject_type="user", subject_id="user-replace",
            old_role_key="org_member", new_role_key="org_admin",
            scope_type="org", scope_id="org-replace",
            granted_reason="upgrade",
        )
        await db.commit()

        # 旧角色软删，新角色未删
        rows = (await db.execute(
            select(SubjectRole).where(
                SubjectRole.subject_id == "user-replace",
                SubjectRole.deleted_at.is_(None),
            )
        )).scalars().all()
        assert len(rows) == 1
        # 通过 join role 表确认是 org_admin
        from app.models.rbac.role import Role
        new_role_key = (await db.execute(
            select(Role.role_key).where(Role.id == rows[0].role_id)
        )).scalar_one()
        assert new_role_key == "org_admin"
