"""RBAC 权限解析核心：has_perms。

设计要点：
1. 仅 **2 次 SQL**：第一次按主体捞 subject_roles → roles，第二次按命中角色捞
   role_menus → menus.perms，避免 N+1。
2. 第一次查询命中 LRU 缓存可省去 DB 访问；第二次查询当前不缓存（命中角色子集
   随作用域变化，缓存键空间过大，第二期再优化）。
3. 跨级 bypass 规则（DeskClaw 特色）：org_admin / platform_admin 持有人对所属
   org 下任意 workspace / instance 权限检查直接放行。需要调用方在 RbacScope
   中提供 parent_org_id 才能启用。
4. platform scope 的 grant 覆盖任意目标 scope，典型代表 platform_super。
"""

from collections.abc import Iterable
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac.cache import get_cached_grants, set_cached_grants
from app.core.rbac.scope import RbacScope
from app.models.rbac.menu import Menu
from app.models.rbac.role import Role
from app.models.rbac.role_menu import RoleMenu
from app.models.rbac.subject_role import SubjectRole

# 拥有 org 级跨级 bypass 权限的角色 key（org_admin / platform_admin）
_ORG_ADMIN_ROLE_KEYS: Final[frozenset[str]] = frozenset({"org_admin", "platform_admin"})


async def _load_grants(
    db: AsyncSession, subject_type: str, subject_id: str,
) -> list[tuple[str, str, str | None]]:
    """加载主体所有未软删的授权 (role_key, scope_type, scope_id)，缓存优先。"""
    cached = get_cached_grants(subject_type, subject_id)
    if cached is not None:
        return cached

    stmt = (
        select(Role.role_key, SubjectRole.scope_type, SubjectRole.scope_id)
        .join(SubjectRole, SubjectRole.role_id == Role.id)
        .where(
            SubjectRole.subject_type == subject_type,
            SubjectRole.subject_id == subject_id,
            SubjectRole.deleted_at.is_(None),
            Role.deleted_at.is_(None),
        )
    )
    rows = (await db.execute(stmt)).all()
    grants: list[tuple[str, str, str | None]] = [
        (row.role_key, row.scope_type, row.scope_id) for row in rows
    ]
    set_cached_grants(subject_type, subject_id, grants)
    return grants


async def _load_role_perms(
    db: AsyncSession, role_keys: Iterable[str],
) -> dict[str, set[str]]:
    """加载一批角色的 perms 集合：{role_key: {perms_code, ...}}。"""
    keys = list(set(role_keys))
    if not keys:
        return {}
    stmt = (
        select(Role.role_key, Menu.perms)
        .join(RoleMenu, RoleMenu.role_id == Role.id)
        .join(Menu, Menu.id == RoleMenu.menu_id)
        .where(
            Role.role_key.in_(keys),
            Role.deleted_at.is_(None),
            RoleMenu.deleted_at.is_(None),
            Menu.deleted_at.is_(None),
            # 只关心带 perms 的菜单/按钮；纯目录 type=M 也可能进来但被这条过滤
            Menu.perms.is_not(None),
        )
    )
    rows = (await db.execute(stmt)).all()
    result: dict[str, set[str]] = {k: set() for k in keys}
    for role_key, perms_code in rows:
        result.setdefault(role_key, set()).add(perms_code)
    return result


def _grant_covers_target(
    grant_scope_type: str,
    grant_scope_id: str | None,
    target: RbacScope,
    role_key: str,
) -> bool:
    """判定 grant 作用域是否覆盖目标 scope。

    覆盖规则（自上而下）：
    1. platform grant 覆盖任意目标 scope（适用于 platform_super 等全局角色）
    2. 同类型 + id 严格相等
    3. org grant + (org_admin / platform_admin) + 目标是 workspace/instance
       + 目标提供了 parent_org_id 与 grant 一致 → 跨级覆盖
    """
    if grant_scope_type == "platform":
        return True
    if grant_scope_type == target.type and grant_scope_id == target.id:
        return True
    if (
        grant_scope_type == "org"
        and role_key in _ORG_ADMIN_ROLE_KEYS
        and target.type in ("workspace", "instance")
        and target.parent_org_id is not None
        and grant_scope_id == target.parent_org_id
    ):
        return True
    return False


async def has_perms(
    db: AsyncSession,
    *,
    subject_type: str,
    subject_id: str,
    perms_code: str,
    scope: RbacScope,
) -> tuple[bool, str | None]:
    """判断主体是否拥有权限点。

    返回 (allowed, matched_role_key)：
    - allowed=True 表示放行，matched_role_key 为命中的角色 key（用于审计记录）
    - allowed=False 时 matched_role_key 为 None
    """
    grants = await _load_grants(db, subject_type, subject_id)
    if not grants:
        return False, None

    # 第一步：过滤出 scope 覆盖目标的角色子集
    matching_role_keys: list[str] = [
        role_key for role_key, st, sid in grants
        if _grant_covers_target(st, sid, scope, role_key)
    ]
    if not matching_role_keys:
        return False, None

    # 第二步：检查这些角色的 perms 集合是否包含目标权限点
    role_perms = await _load_role_perms(db, matching_role_keys)
    for role_key in matching_role_keys:
        if perms_code in role_perms.get(role_key, set()):
            return True, role_key
    return False, None
