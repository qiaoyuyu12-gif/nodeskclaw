"""RBAC seed 综合测试：apps / roles / menus / role_menus / role_apps / backfill 全幂等。"""

import pytest
from sqlalchemy import func, select

from app.models.admin_membership import AdminMembership
from app.models.org_membership import OrgMembership, OrgRole
from app.models.organization import Organization
from app.models.rbac.app import App
from app.models.rbac.menu import Menu
from app.models.rbac.role import Role
from app.models.rbac.role_app import RoleApp
from app.models.rbac.role_menu import RoleMenu
from app.models.rbac.subject_role import SubjectRole
from app.models.user import User
from app.startup.seed_rbac import (
    BUILTIN_APPS,
    BUILTIN_BUTTON_MENUS,
    BUILTIN_ROLES,
    ROLE_APP_BINDINGS,
    ROLE_MENU_BINDINGS,
    seed_rbac,
)

from tests.rbac.conftest import TestSessionLocal


@pytest.mark.asyncio
async def test_seed_rbac_idempotent_three_runs(require_test_db, session_factory):
    """连续 3 次 seed 后，主表行数稳定。"""
    for _ in range(3):
        await seed_rbac(session_factory)

    async with TestSessionLocal() as db:
        apps_count = (await db.execute(
            select(func.count()).select_from(App).where(App.deleted_at.is_(None))
        )).scalar_one()
        roles_count = (await db.execute(
            select(func.count()).select_from(Role).where(Role.deleted_at.is_(None))
        )).scalar_one()
        menus_count = (await db.execute(
            select(func.count()).select_from(Menu).where(
                Menu.deleted_at.is_(None),
                Menu.menu_type == "F",
            )
        )).scalar_one()
        role_menus_count = (await db.execute(
            select(func.count()).select_from(RoleMenu)
        )).scalar_one()
        role_apps_count = (await db.execute(
            select(func.count()).select_from(RoleApp)
        )).scalar_one()

    # 主表数字与 BUILTIN_* 长度一致
    assert apps_count == len(BUILTIN_APPS)
    assert roles_count == len(BUILTIN_ROLES)
    assert menus_count == len(BUILTIN_BUTTON_MENUS)
    # 角色 × 按钮 总绑定数 = 各 perms 对应 role_keys 集合大小之和
    expected_role_menus = sum(len(v) for v in ROLE_MENU_BINDINGS.values())
    assert role_menus_count == expected_role_menus
    # 角色 × 应用 总绑定数 = 各 role 对应 app_codes 集合大小之和
    expected_role_apps = sum(len(v) for v in ROLE_APP_BINDINGS.values())
    assert role_apps_count == expected_role_apps


@pytest.mark.asyncio
async def test_backfill_creates_subject_roles_from_legacy(
    require_test_db, session_factory,
):
    """is_super_admin / OrgMembership / AdminMembership / WorkspaceMember 全量回填。"""
    async with TestSessionLocal() as db:
        # 准备：1 个超管 + 2 个 org 成员 + 1 个 AdminMembership
        org = Organization(id="org-backfill", name="Backfill Org", slug="org-backfill")
        super_admin = User(
            id="user-super", name="Super", username="super-backfill",
            is_super_admin=True,
        )
        normal = User(id="user-normal", name="Normal", username="normal-backfill")
        db.add_all([org, super_admin, normal])
        await db.flush()

        # OrgMembership：super 是 admin，normal 是 member
        db.add(OrgMembership(
            user_id=super_admin.id, org_id=org.id, role=OrgRole.admin,
        ))
        db.add(OrgMembership(
            user_id=normal.id, org_id=org.id, role=OrgRole.member,
        ))
        # AdminMembership：normal 也有平台 admin 权
        db.add(AdminMembership(user_id=normal.id, org_id=org.id, role="admin"))
        await db.commit()

    # 执行 seed（含 backfill）
    await seed_rbac(session_factory)

    async with TestSessionLocal() as db:
        # super_admin 应有 platform_super
        super_grants = (await db.execute(
            select(Role.role_key, SubjectRole.scope_type, SubjectRole.scope_id)
            .join(SubjectRole, SubjectRole.role_id == Role.id)
            .where(
                SubjectRole.subject_id == "user-super",
                SubjectRole.deleted_at.is_(None),
            )
        )).all()
        super_keys = {row.role_key for row in super_grants}
        assert "platform_super" in super_keys
        assert "org_admin" in super_keys

        # normal 应有 org_member + platform_admin
        normal_grants = (await db.execute(
            select(Role.role_key, SubjectRole.scope_type, SubjectRole.scope_id)
            .join(SubjectRole, SubjectRole.role_id == Role.id)
            .where(
                SubjectRole.subject_id == "user-normal",
                SubjectRole.deleted_at.is_(None),
            )
        )).all()
        normal_keys = {row.role_key for row in normal_grants}
        assert normal_keys == {"org_member", "platform_admin"}

    # 第二次 backfill 不应造成重复
    await seed_rbac(session_factory)

    async with TestSessionLocal() as db:
        super_count = (await db.execute(
            select(func.count()).select_from(SubjectRole).where(
                SubjectRole.subject_id == "user-super",
                SubjectRole.deleted_at.is_(None),
            )
        )).scalar_one()
        normal_count = (await db.execute(
            select(func.count()).select_from(SubjectRole).where(
                SubjectRole.subject_id == "user-normal",
                SubjectRole.deleted_at.is_(None),
            )
        )).scalar_one()
        # 幂等：行数与第一次相同
        assert super_count == 2
        assert normal_count == 2


@pytest.mark.asyncio
async def test_seed_menus_check_constraints(require_test_db, session_factory):
    """按钮权限点的 CHECK 约束（menu_type='F' 必须有 perms）。"""
    await seed_rbac(session_factory)
    async with TestSessionLocal() as db:
        rows = (await db.execute(
            select(Menu.menu_type, Menu.perms).where(
                Menu.deleted_at.is_(None),
                Menu.perms.is_not(None),
            )
        )).all()
        # 所有 seed 写入的都是 type=F
        assert all(r.menu_type == "F" for r in rows)
        # 所有 type=F 都有 perms（CHECK 约束已经强制，这里再验一次）
        assert all(r.perms for r in rows)
