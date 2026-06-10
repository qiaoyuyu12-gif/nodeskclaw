"""为 /auth/me 提供 RBAC 上下文聚合。

返回当前主体在所有 scope 下被授予的角色，以及角色对应的 perms 集合与可访问的
应用列表。**第一期前端可暂不消费**，但字段一旦上线即可作为第二期动态菜单与
按钮权限渲染的数据源。

设计要点：
- 不过滤 scope_id：把主体被授予的角色全部返回，前端按需决定如何使用
- 三个集合都去重，且按字母序排序，便于前端做差异对比
- 复用 RBAC LRU 缓存（subject → grants），命中时不查 DB
- 加载 role_keys 对应的 perms / apps 时一次 join 完成，无 N+1
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac.cache import get_cached_grants, set_cached_grants
from app.models.rbac.app import App
from app.models.rbac.menu import Menu
from app.models.rbac.role import Role
from app.models.rbac.role_app import RoleApp
from app.models.rbac.role_menu import RoleMenu
from app.models.rbac.subject_role import SubjectRole


async def _load_grants(
    db: AsyncSession, subject_type: str, subject_id: str,
) -> list[tuple[str, str, str | None]]:
    """与 resolver._load_grants 相同语义，共享 LRU 缓存键。"""
    cached = get_cached_grants(subject_type, subject_id)
    if cached is not None:
        return cached
    rows = (await db.execute(
        select(Role.role_key, SubjectRole.scope_type, SubjectRole.scope_id)
        .join(SubjectRole, SubjectRole.role_id == Role.id)
        .where(
            SubjectRole.subject_type == subject_type,
            SubjectRole.subject_id == subject_id,
            SubjectRole.deleted_at.is_(None),
            Role.deleted_at.is_(None),
        )
    )).all()
    grants = [(r.role_key, r.scope_type, r.scope_id) for r in rows]
    set_cached_grants(subject_type, subject_id, grants)
    return grants


async def get_login_rbac(
    db: AsyncSession,
    *,
    subject_type: str = "user",
    subject_id: str,
) -> dict[str, list[str]]:
    """聚合主体的角色 / 权限点 / 应用集合，供 /auth/me 等接口返回前端。

    返回结构：
        {
            "role_keys": ["platform_super", "org_admin", ...],
            "perms":     ["gene:publish", "org:read", ...],
            "app_codes": ["PORTAL", "ADMIN", ...],
        }
    """
    grants = await _load_grants(db, subject_type, subject_id)
    role_keys = sorted({rk for rk, _st, _sid in grants})

    if not role_keys:
        return {"role_keys": [], "perms": [], "app_codes": []}

    # 一次性加载这批角色拥有的全部 perms（type=F/C 凡是带 perms 的均算）
    perms_rows = (await db.execute(
        select(Menu.perms)
        .join(RoleMenu, RoleMenu.menu_id == Menu.id)
        .join(Role, Role.id == RoleMenu.role_id)
        .where(
            Role.role_key.in_(role_keys),
            Role.deleted_at.is_(None),
            RoleMenu.deleted_at.is_(None),
            Menu.deleted_at.is_(None),
            Menu.perms.is_not(None),
        )
    )).all()
    perms = sorted({row.perms for row in perms_rows})

    # 一次性加载这批角色拥有的全部 app_code
    app_rows = (await db.execute(
        select(App.app_code)
        .join(RoleApp, RoleApp.app_id == App.id)
        .join(Role, Role.id == RoleApp.role_id)
        .where(
            Role.role_key.in_(role_keys),
            Role.deleted_at.is_(None),
            RoleApp.deleted_at.is_(None),
            App.deleted_at.is_(None),
        )
    )).all()
    app_codes = sorted({row.app_code for row in app_rows})

    return {
        "role_keys": role_keys,
        "perms": perms,
        "app_codes": app_codes,
    }
