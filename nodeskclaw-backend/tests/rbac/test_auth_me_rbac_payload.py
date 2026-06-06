"""/auth/me 响应包含 rbac 子对象。"""

import pytest
from sqlalchemy import select

from app.models.organization import Organization
from app.models.user import User
from app.services.rbac_context_service import get_login_rbac
from app.services.rbac_sync import grant_role
from app.startup.seed_rbac import seed_rbac

from tests.rbac.conftest import TestSessionLocal


@pytest.mark.asyncio
async def test_get_login_rbac_empty_for_new_user(require_test_db, session_factory):
    """新建无授权用户聚合结果为空三元组。"""
    await seed_rbac(session_factory)
    async with TestSessionLocal() as db:
        user = User(id="user-me-empty", name="Empty", username="empty-me")
        db.add(user)
        await db.commit()

        payload = await get_login_rbac(
            db, subject_type="user", subject_id="user-me-empty",
        )
        assert payload == {"role_keys": [], "perms": [], "app_codes": []}


@pytest.mark.asyncio
async def test_get_login_rbac_aggregates_grants(require_test_db, session_factory):
    """有 org_admin + workspace_owner 两个角色的用户应聚合 perms / app_codes。"""
    await seed_rbac(session_factory)
    async with TestSessionLocal() as db:
        org = Organization(id="org-me-1", name="Me Org", slug="org-me-1")
        user = User(id="user-me-1", name="Me", username="me-test-1")
        db.add_all([org, user])
        await db.flush()
        await grant_role(
            db, subject_type="user", subject_id="user-me-1",
            role_key="org_admin",
            scope_type="org", scope_id="org-me-1",
            granted_reason="test_me",
        )
        await grant_role(
            db, subject_type="user", subject_id="user-me-1",
            role_key="workspace_owner",
            scope_type="workspace", scope_id="ws-me-1",
            granted_reason="test_me",
        )
        await db.commit()

        payload = await get_login_rbac(
            db, subject_type="user", subject_id="user-me-1",
        )

        assert set(payload["role_keys"]) == {"org_admin", "workspace_owner"}
        # 关键 perms 必须出现
        assert "gene:publish" in payload["perms"]            # org_admin
        assert "workspace:delete" in payload["perms"]        # workspace_owner / org_admin
        assert "workspace:member:invite" in payload["perms"]
        # app_codes：org_admin 拥有 PORTAL + ADMIN，workspace_owner 拥有 PORTAL
        assert "PORTAL" in payload["app_codes"]
        assert "ADMIN" in payload["app_codes"]
        # 字母序去重
        assert payload["app_codes"] == sorted(set(payload["app_codes"]))
        assert payload["perms"] == sorted(set(payload["perms"]))


@pytest.mark.asyncio
async def test_get_login_rbac_platform_super(require_test_db, session_factory):
    """platform_super 用户应拥有全部应用与全部内置 perms。"""
    await seed_rbac(session_factory)
    async with TestSessionLocal() as db:
        user = User(id="user-me-super", name="Super", username="super-me")
        db.add(user)
        await db.flush()
        await grant_role(
            db, subject_type="user", subject_id="user-me-super",
            role_key="platform_super",
            scope_type="platform", scope_id=None,
            granted_reason="test_super",
        )
        await db.commit()

        payload = await get_login_rbac(
            db, subject_type="user", subject_id="user-me-super",
        )
        # platform_super 拥有的应用：全部 4 个
        assert set(payload["app_codes"]) == {
            "PORTAL", "ADMIN", "OPEN_API", "MCP_GATEWAY",
        }
        # 拥有 platform 专属 perms
        assert "platform:cluster:manage" in payload["perms"]
