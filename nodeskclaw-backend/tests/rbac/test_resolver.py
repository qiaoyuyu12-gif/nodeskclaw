"""RBAC 解析器 has_perms 全场景覆盖。"""

import pytest

from app.core.rbac.resolver import has_perms
from app.core.rbac.scope import RbacScope
from app.models.organization import Organization
from app.models.user import User
from app.services.rbac_sync import grant_role
from app.startup.seed_rbac import seed_rbac

from tests.rbac.conftest import TestSessionLocal


async def _prepare_user_with_org(db, user_id: str, org_id: str):
    """创建一个用户和一个 org，便于后续 grant_role 测试。"""
    org = Organization(id=org_id, name=f"Org {org_id}", slug=org_id)
    user = User(id=user_id, name=f"User {user_id}", username=user_id)
    db.add_all([org, user])
    await db.flush()


@pytest.mark.asyncio
async def test_platform_super_allows_any_perms(require_test_db, session_factory):
    """platform_super 持有人对任意 scope 任意 perms 都 allow。"""
    await seed_rbac(session_factory)
    async with TestSessionLocal() as db:
        await _prepare_user_with_org(db, "user-super-1", "org-super-1")
        await grant_role(
            db, subject_type="user", subject_id="user-super-1",
            role_key="platform_super",
            scope_type="platform", scope_id=None,
            granted_reason="test_super",
        )
        await db.commit()

        # 对 workspace / instance / org / platform 任一 scope 都 allow
        for scope in [
            RbacScope.platform(),
            RbacScope.org("org-super-1"),
            RbacScope.workspace("ws-x", org_id="org-super-1"),
            RbacScope.instance("inst-x", org_id="org-super-1"),
        ]:
            allowed, matched = await has_perms(
                db, subject_type="user", subject_id="user-super-1",
                perms_code="platform:cluster:manage", scope=scope,
            )
            assert allowed, f"scope={scope} 未放行"
            assert matched == "platform_super"


@pytest.mark.asyncio
async def test_org_admin_covers_workspace_with_parent_org(
    require_test_db, session_factory,
):
    """org_admin 在 workspace scope 检查时，提供 parent_org_id 即跨级覆盖。"""
    await seed_rbac(session_factory)
    async with TestSessionLocal() as db:
        await _prepare_user_with_org(db, "user-org-admin", "org-a")
        await grant_role(
            db, subject_type="user", subject_id="user-org-admin",
            role_key="org_admin",
            scope_type="org", scope_id="org-a",
            granted_reason="test_org_admin",
        )
        await db.commit()

        # 1) 带 parent_org_id → 跨级覆盖，workspace:delete allow
        scope_with_parent = RbacScope.workspace("ws-1", org_id="org-a")
        allowed, matched = await has_perms(
            db, subject_type="user", subject_id="user-org-admin",
            perms_code="workspace:delete", scope=scope_with_parent,
        )
        assert allowed is True
        assert matched == "org_admin"


@pytest.mark.asyncio
async def test_workspace_scope_without_parent_org_no_cross_level(
    require_test_db, session_factory,
):
    """未提供 parent_org_id 时，org_admin 不应跨级覆盖 workspace。"""
    await seed_rbac(session_factory)
    async with TestSessionLocal() as db:
        await _prepare_user_with_org(db, "user-org-admin-2", "org-b")
        await grant_role(
            db, subject_type="user", subject_id="user-org-admin-2",
            role_key="org_admin",
            scope_type="org", scope_id="org-b",
            granted_reason="test_no_parent",
        )
        await db.commit()

        # 不提供 parent_org_id → 严格匹配，应 deny
        scope_no_parent = RbacScope.workspace("ws-1")  # 无 org_id
        allowed, matched = await has_perms(
            db, subject_type="user", subject_id="user-org-admin-2",
            perms_code="workspace:delete", scope=scope_no_parent,
        )
        assert allowed is False
        assert matched is None


@pytest.mark.asyncio
async def test_workspace_role_strict_match(require_test_db, session_factory):
    """workspace_owner 仅对自己的 workspace 生效，对其他 workspace deny。"""
    await seed_rbac(session_factory)
    async with TestSessionLocal() as db:
        await _prepare_user_with_org(db, "user-ws-owner", "org-c")
        await grant_role(
            db, subject_type="user", subject_id="user-ws-owner",
            role_key="workspace_owner",
            scope_type="workspace", scope_id="ws-mine",
            granted_reason="test_ws_owner",
        )
        await db.commit()

        allowed, matched = await has_perms(
            db, subject_type="user", subject_id="user-ws-owner",
            perms_code="workspace:delete",
            scope=RbacScope.workspace("ws-mine"),
        )
        assert allowed is True
        assert matched == "workspace_owner"

        # 对其他 workspace 应拒绝
        allowed_other, _ = await has_perms(
            db, subject_type="user", subject_id="user-ws-owner",
            perms_code="workspace:delete",
            scope=RbacScope.workspace("ws-not-mine"),
        )
        assert allowed_other is False


@pytest.mark.asyncio
async def test_no_grants_returns_false(require_test_db, session_factory):
    """完全未授权的用户对任意 perms 都 deny。"""
    await seed_rbac(session_factory)
    async with TestSessionLocal() as db:
        await _prepare_user_with_org(db, "user-empty", "org-empty")
        await db.commit()

        allowed, matched = await has_perms(
            db, subject_type="user", subject_id="user-empty",
            perms_code="org:read",
            scope=RbacScope.org("org-empty"),
        )
        assert allowed is False
        assert matched is None


@pytest.mark.asyncio
async def test_perms_not_in_role_returns_false(require_test_db, session_factory):
    """有角色但角色不含该 perms → deny。"""
    await seed_rbac(session_factory)
    async with TestSessionLocal() as db:
        await _prepare_user_with_org(db, "user-viewer", "org-viewer")
        await grant_role(
            db, subject_type="user", subject_id="user-viewer",
            role_key="workspace_viewer",
            scope_type="workspace", scope_id="ws-v",
            granted_reason="test_viewer",
        )
        await db.commit()

        # workspace_viewer 不含 workspace:delete
        allowed, matched = await has_perms(
            db, subject_type="user", subject_id="user-viewer",
            perms_code="workspace:delete",
            scope=RbacScope.workspace("ws-v"),
        )
        assert allowed is False
        assert matched is None

        # 但 workspace:read 应 allow
        allowed_read, matched_read = await has_perms(
            db, subject_type="user", subject_id="user-viewer",
            perms_code="workspace:read",
            scope=RbacScope.workspace("ws-v"),
        )
        assert allowed_read is True
        assert matched_read == "workspace_viewer"
