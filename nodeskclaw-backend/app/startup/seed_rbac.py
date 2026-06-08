"""RBAC 第一期种子数据：apps / roles / menus(F) / role_menus / role_apps + legacy backfill。

幂等设计：每次启动都会跑一遍，确保系统内置数据始终与代码定义一致。
- apps / roles：按 唯一 key（app_code / role_key）upsert
- menus(F)：按 perms upsert
- role_menus / role_apps：对**系统内置角色**采用「先清空再重建」策略，
  避免修改 ROLE_MENU_BINDINGS 后旧绑定残留；自定义角色（is_system=False）不动
- backfill_subject_roles_from_legacy：扫描 4 张 legacy 表 → grant_role（幂等）

参考 docs/rfcs/0001-rbac-phase1.md §5 / §8。
"""

import logging
import uuid
from typing import Final

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.services.rbac_sync import grant_role

logger = logging.getLogger(__name__)


# ── 1. 内置应用 ────────────────────────────────────────────

BUILTIN_APPS: Final[list[dict]] = [
    {
        "app_code": "PORTAL",
        "app_name": "DeskClaw 用户门户",
        "app_url": "/portal/home",
        "app_desc": "面向用户的工作区与赛博办公室入口",
        "sort_order": 10,
    },
    {
        "app_code": "ADMIN",
        "app_name": "DeskClaw 管理后台",
        "app_url": "/admin/home",
        "app_desc": "EE 版管理后台，提供组织、集群、计费管理",
        "sort_order": 20,
    },
    {
        "app_code": "OPEN_API",
        "app_name": "OpenAPI 调用",
        "app_url": "/api/v1",
        "app_desc": "提供给三方系统的 REST API 入口",
        "sort_order": 30,
    },
    {
        "app_code": "MCP_GATEWAY",
        "app_name": "MCP 协议网关",
        "app_url": "/mcp",
        "app_desc": "AI 客户端通过 MCP 协议接入 DeskClaw 的网关",
        "sort_order": 40,
    },
]


# ── 2. 内置角色 ───────────────────────────────────────────

BUILTIN_ROLES: Final[list[dict]] = [
    {"role_key": "platform_super", "role_name": "平台超级管理员",
     "scope": "platform", "role_sort": 0,
     "description": "拥有全平台所有权限，对任意 scope 检查直接放行"},
    {"role_key": "platform_admin", "role_name": "平台管理员",
     "scope": "org", "role_sort": 10,
     "description": "EE 平台管理后台访问者，作用域绑定到具体 org"},
    {"role_key": "org_admin", "role_name": "组织管理员",
     "scope": "org", "role_sort": 20,
     "description": "组织内最高权限，自动覆盖该 org 下所有 workspace/instance"},
    {"role_key": "org_operator", "role_name": "组织操作员",
     "scope": "org", "role_sort": 30,
     "description": "组织内日常操作角色，介于管理员与成员之间"},
    {"role_key": "org_member", "role_name": "组织成员",
     "scope": "org", "role_sort": 40,
     "description": "组织基础成员，可读取组织信息和参与工作区"},
    {"role_key": "workspace_owner", "role_name": "工作区所有者",
     "scope": "workspace", "role_sort": 50,
     "description": "工作区创建者，拥有工作区全部管理权限"},
    {"role_key": "workspace_editor", "role_name": "工作区编辑者",
     "scope": "workspace", "role_sort": 60,
     "description": "可编辑工作区内容、管理 Agent"},
    {"role_key": "workspace_viewer", "role_name": "工作区查看者",
     "scope": "workspace", "role_sort": 70,
     "description": "只读访问工作区，可参与聊天但不能改设置"},
    {"role_key": "agent_workspace_executor", "role_name": "Agent 工作区执行者",
     "scope": "workspace", "role_sort": 80,
     "description": "AI Agent 默认角色，仅能执行 skill 与参与聊天"},
]


# ── 3. 内置按钮权限点（menus type=F） ──────────────────────

# 第一期仅 seed type=F 按钮权限点，type=M/C 菜单树留给第二期前端动态菜单切换。
# app_code 统一设为 None（共享），具体应用归属由前端第二期再细化。
BUILTIN_BUTTON_MENUS: Final[list[dict]] = [
    {"perms": "org:read", "menu_name": "rbac.menu.org_read"},
    {"perms": "org:update", "menu_name": "rbac.menu.org_update"},
    {"perms": "org:member:invite", "menu_name": "rbac.menu.org_invite"},
    {"perms": "org:member:remove", "menu_name": "rbac.menu.org_remove"},
    {"perms": "org:llm_key:manage", "menu_name": "rbac.menu.llm_key"},
    {"perms": "gene:read", "menu_name": "rbac.menu.gene_read"},
    {"perms": "gene:publish", "menu_name": "rbac.menu.gene_publish"},
    {"perms": "gene:review", "menu_name": "rbac.menu.gene_review"},
    {"perms": "workspace:read", "menu_name": "rbac.menu.ws_read"},
    {"perms": "workspace:update", "menu_name": "rbac.menu.ws_update"},
    {"perms": "workspace:delete", "menu_name": "rbac.menu.ws_delete"},
    {"perms": "workspace:member:invite", "menu_name": "rbac.menu.ws_invite"},
    {"perms": "workspace:chat:send", "menu_name": "rbac.menu.ws_chat"},
    {"perms": "instance:read", "menu_name": "rbac.menu.inst_read"},
    {"perms": "instance:deploy", "menu_name": "rbac.menu.inst_deploy"},
    {"perms": "platform:cluster:manage", "menu_name": "rbac.menu.cluster"},
]


# ── 4. 角色 × 权限点 绑定 ────────────────────────────────
# 反向映射：每个 perms 归属哪些 role_key。

ROLE_MENU_BINDINGS: Final[dict[str, set[str]]] = {
    # org 系列
    "org:read": {"org_member", "org_operator", "org_admin", "platform_super"},
    "org:update": {"org_admin", "platform_super"},
    "org:member:invite": {"org_admin", "platform_super"},
    "org:member:remove": {"org_admin", "platform_super"},
    "org:llm_key:manage": {"org_admin", "platform_super"},
    # gene 系列
    "gene:read": {"org_member", "org_operator", "org_admin", "platform_super"},
    "gene:publish": {"org_admin", "platform_super"},
    "gene:review": {"org_admin", "platform_super"},
    # workspace 系列
    "workspace:read": {"workspace_viewer", "workspace_editor", "workspace_owner"},
    "workspace:update": {"workspace_editor", "workspace_owner"},
    "workspace:delete": {"workspace_owner", "org_admin", "platform_super"},
    "workspace:member:invite": {"workspace_owner", "org_admin", "platform_super"},
    "workspace:chat:send": {
        "workspace_viewer", "workspace_editor", "workspace_owner",
        "agent_workspace_executor",
    },
    # instance 系列
    "instance:read": {"org_member", "org_operator", "org_admin", "platform_super"},
    "instance:deploy": {"org_admin", "platform_super"},
    # platform 系列
    "platform:cluster:manage": {"platform_super"},
}


# ── 5. 角色 × 应用 绑定 ──────────────────────────────────

ROLE_APP_BINDINGS: Final[dict[str, set[str]]] = {
    "platform_super": {"PORTAL", "ADMIN", "OPEN_API", "MCP_GATEWAY"},
    "platform_admin": {"PORTAL", "ADMIN"},
    "org_admin": {"PORTAL", "ADMIN"},
    "org_operator": {"PORTAL"},
    "org_member": {"PORTAL"},
    "workspace_owner": {"PORTAL"},
    "workspace_editor": {"PORTAL"},
    "workspace_viewer": {"PORTAL"},
    "agent_workspace_executor": {"OPEN_API", "MCP_GATEWAY"},
}


# ── Seed 入口 ────────────────────────────────────────────

async def seed_rbac(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """RBAC 全量 seed：4 张主表 + 2 张关联表 + legacy 回填，全部幂等。"""
    await _seed_apps(session_factory)
    await _seed_roles(session_factory)
    await _seed_menus_buttons_only(session_factory)
    await _seed_role_menus(session_factory)
    await _seed_role_apps(session_factory)

    if settings.SKIP_RBAC_BACKFILL:
        logger.warning("RBAC seed：SKIP_RBAC_BACKFILL=true，跳过 legacy 回填")
        return
    await _backfill_subject_roles_from_legacy(session_factory)


# ── 子步骤 ────────────────────────────────────────────────

async def _seed_apps(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """按 app_code upsert 4 个内置应用。"""
    from app.models.rbac.app import App

    async with session_factory() as db:
        seeded = 0
        for spec in BUILTIN_APPS:
            row = (await db.execute(
                select(App).where(
                    App.app_code == spec["app_code"],
                    App.deleted_at.is_(None),
                )
            )).scalar_one_or_none()
            if row is None:
                db.add(App(**spec))
                seeded += 1
            else:
                # 名称 / URL / 排序号可能因代码更新而变化，按内置定义同步
                row.app_name = spec["app_name"]
                row.app_url = spec["app_url"]
                row.app_desc = spec.get("app_desc")
                row.sort_order = spec.get("sort_order", 0)
        await db.commit()
        if seeded:
            logger.info("RBAC seed：写入 %d 个新应用", seeded)


async def _seed_roles(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """按 role_key upsert 9 个内置角色（is_system=True）。"""
    from app.models.rbac.role import Role

    async with session_factory() as db:
        seeded = 0
        for spec in BUILTIN_ROLES:
            row = (await db.execute(
                select(Role).where(
                    Role.role_key == spec["role_key"],
                    Role.deleted_at.is_(None),
                )
            )).scalar_one_or_none()
            if row is None:
                db.add(Role(is_system=True, **spec))
                seeded += 1
            else:
                row.role_name = spec["role_name"]
                row.scope = spec["scope"]
                row.role_sort = spec.get("role_sort", 0)
                row.description = spec.get("description")
                row.is_system = True
        await db.commit()
        if seeded:
            logger.info("RBAC seed：写入 %d 个新角色", seeded)


async def _seed_menus_buttons_only(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """按 perms upsert 16 个按钮权限点（menu_type='F'，app_code=None）。"""
    from app.models.rbac.menu import Menu, MenuType

    async with session_factory() as db:
        seeded = 0
        for spec in BUILTIN_BUTTON_MENUS:
            row = (await db.execute(
                select(Menu).where(
                    Menu.perms == spec["perms"],
                    Menu.deleted_at.is_(None),
                )
            )).scalar_one_or_none()
            if row is None:
                db.add(Menu(
                    menu_type=MenuType.BUTTON,
                    perms=spec["perms"],
                    menu_name=spec["menu_name"],
                    # app_code 暂为 None（全应用共享），第二期前端切动态菜单时再细化
                ))
                seeded += 1
            else:
                row.menu_name = spec["menu_name"]
                row.menu_type = MenuType.BUTTON
        await db.commit()
        if seeded:
            logger.info("RBAC seed：写入 %d 个新按钮权限点", seeded)


async def _seed_role_menus(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """重建系统内置角色 × 按钮权限 绑定（is_system 角色清空重建，自定义角色不动）。

    采用「清空 → 重建」策略而非 upsert，避免 ROLE_MENU_BINDINGS 调整后旧绑定残留。
    """
    from app.models.rbac.menu import Menu
    from app.models.rbac.role import Role
    from app.models.rbac.role_menu import RoleMenu

    async with session_factory() as db:
        # 加载所有内置角色与按钮权限点
        role_map = {
            r.role_key: r for r in (await db.execute(
                select(Role).where(
                    Role.is_system.is_(True),
                    Role.deleted_at.is_(None),
                )
            )).scalars()
        }
        menu_map = {
            m.perms: m for m in (await db.execute(
                select(Menu).where(
                    Menu.perms.is_not(None),
                    Menu.deleted_at.is_(None),
                )
            )).scalars()
        }

        # 物理删除内置角色现有的绑定（不软删，因为这是系统数据可重建）
        if role_map:
            await db.execute(
                delete(RoleMenu).where(
                    RoleMenu.role_id.in_([r.id for r in role_map.values()]),
                )
            )

        # 按 ROLE_MENU_BINDINGS 重建
        inserted = 0
        for perms, role_keys in ROLE_MENU_BINDINGS.items():
            menu = menu_map.get(perms)
            if menu is None:
                logger.warning("RBAC seed：按钮权限 %s 不存在，跳过绑定", perms)
                continue
            for role_key in role_keys:
                role = role_map.get(role_key)
                if role is None:
                    logger.warning(
                        "RBAC seed：角色 %s 不存在，跳过绑定 %s", role_key, perms,
                    )
                    continue
                db.add(RoleMenu(role_id=role.id, menu_id=menu.id))
                inserted += 1
        await db.commit()
        logger.info("RBAC seed：重建 %d 条角色 × 按钮权限 绑定", inserted)


async def _seed_role_apps(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """重建系统内置角色 × 应用 绑定（同 _seed_role_menus 策略）。"""
    from app.models.rbac.app import App
    from app.models.rbac.role import Role
    from app.models.rbac.role_app import RoleApp

    async with session_factory() as db:
        role_map = {
            r.role_key: r for r in (await db.execute(
                select(Role).where(
                    Role.is_system.is_(True),
                    Role.deleted_at.is_(None),
                )
            )).scalars()
        }
        app_map = {
            a.app_code: a for a in (await db.execute(
                select(App).where(App.deleted_at.is_(None))
            )).scalars()
        }

        if role_map:
            await db.execute(
                delete(RoleApp).where(
                    RoleApp.role_id.in_([r.id for r in role_map.values()]),
                )
            )

        inserted = 0
        for role_key, app_codes in ROLE_APP_BINDINGS.items():
            role = role_map.get(role_key)
            if role is None:
                continue
            for app_code in app_codes:
                app = app_map.get(app_code)
                if app is None:
                    logger.warning(
                        "RBAC seed：应用 %s 不存在，跳过绑定 %s", app_code, role_key,
                    )
                    continue
                db.add(RoleApp(role_id=role.id, app_id=app.id))
                inserted += 1
        await db.commit()
        logger.info("RBAC seed：重建 %d 条角色 × 应用 绑定", inserted)


async def _backfill_subject_roles_from_legacy(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """把 4 张 legacy 表的现有数据映射到 subject_roles（幂等）。

    映射规则（参考 RFC 0001 v2 §8.6）：
    - User.is_super_admin=True → platform_super (scope=platform)
    - OrgMembership(user, org, role) → org_{role} (scope=org, scope_id=org_id)
    - AdminMembership(user, org, role) → platform_admin (scope=org, scope_id=org_id)
    - WorkspaceMember(user, workspace, role) → workspace_{role}
      (scope=workspace, scope_id=workspace_id)

    grant_role 自身幂等，所以每次启动重复执行不会产生重复授权记录。
    """
    from app.models.admin_membership import AdminMembership
    from app.models.org_membership import OrgMembership
    from app.models.user import User
    from app.models.workspace_member import WorkspaceMember

    async with session_factory() as db:
        # 1) is_super_admin → platform_super
        super_count = 0
        for u in (await db.execute(
            select(User).where(
                User.is_super_admin.is_(True),
                User.deleted_at.is_(None),
            )
        )).scalars():
            await grant_role(
                db,
                subject_type="user", subject_id=u.id,
                role_key="platform_super",
                scope_type="platform", scope_id=None,
                granted_reason="seed:is_super_admin",
            )
            super_count += 1

        # 2) OrgMembership → org_{role}
        org_count = 0
        for om in (await db.execute(
            select(OrgMembership).where(OrgMembership.deleted_at.is_(None))
        )).scalars():
            await grant_role(
                db,
                subject_type="user", subject_id=om.user_id,
                role_key=f"org_{om.role}",
                scope_type="org", scope_id=om.org_id,
                granted_reason="seed:org_membership",
            )
            org_count += 1

        # 3) AdminMembership → platform_admin (scope=org)
        admin_count = 0
        for am in (await db.execute(
            select(AdminMembership).where(AdminMembership.deleted_at.is_(None))
        )).scalars():
            await grant_role(
                db,
                subject_type="user", subject_id=am.user_id,
                role_key="platform_admin",
                scope_type="org", scope_id=am.org_id,
                granted_reason="seed:admin_membership",
            )
            admin_count += 1

        # 4) WorkspaceMember → workspace_{role}
        ws_count = 0
        for wm in (await db.execute(
            select(WorkspaceMember).where(WorkspaceMember.deleted_at.is_(None))
        )).scalars():
            await grant_role(
                db,
                subject_type="user", subject_id=wm.user_id,
                role_key=f"workspace_{wm.role}",
                scope_type="workspace", scope_id=wm.workspace_id,
                granted_reason="seed:workspace_member",
            )
            ws_count += 1

        await db.commit()
        logger.info(
            "RBAC seed：legacy 回填完成 super=%d org_m=%d admin_m=%d ws_m=%d",
            super_count, org_count, admin_count, ws_count,
        )
