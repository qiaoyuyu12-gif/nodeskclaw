"""超级管理员保护辅助：照搬 MOM Cloud 的 checkNotSuperAdmin / checkNotAdminRole 思路。

适用场景：
- 用户管理 API 的更新 / 删除 / 改状态 / 重置密码入口
- 角色管理 API 的更新 / 删除 / 分配菜单入口

设计原则：
- 自己是超管 → 直接放行（超管可操作超管）
- 自己不是超管 + 目标是超管 → 抛 ForbiddenError 拒绝
- 目标不是超管 → 不干涉，由调用方自行做其他权限检查

第一期**仅提供工具函数**，不强制接入业务，避免任何行为变化；
第二期由 RFC 0002 接入 user_service / 角色管理 API。
"""

from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError
from app.models.rbac.role import Role
from app.models.rbac.subject_role import SubjectRole

# 平台超级管理员角色 key（与 seed 内置角色对齐）
SUPER_ROLE_KEY: Final[str] = "platform_super"


async def is_super_admin_user(db: AsyncSession, user_id: str) -> bool:
    """判断指定用户是否拥有 platform_super 角色（不限 scope）。"""
    stmt = (
        select(SubjectRole.id)
        .join(Role, Role.id == SubjectRole.role_id)
        .where(
            SubjectRole.subject_type == "user",
            SubjectRole.subject_id == user_id,
            SubjectRole.deleted_at.is_(None),
            Role.role_key == SUPER_ROLE_KEY,
            Role.deleted_at.is_(None),
        )
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none() is not None


async def assert_not_super_admin(
    db: AsyncSession,
    *,
    current_user_id: str,
    target_user_id: str,
) -> None:
    """非超管不允许操作超管用户。

    用法：在用户管理 API 的 update / delete / changeStatus / resetPassword
    入口先调用本函数，目标用户是超管时立即抛错拒绝。

    超管操作超管允许（典型场景：另一个超管修改自己的密码）。
    """
    # 自己就是超管，允许任何操作
    if await is_super_admin_user(db, current_user_id):
        return
    # 自己不是超管，目标是超管 → 拒绝
    if await is_super_admin_user(db, target_user_id):
        raise ForbiddenError(
            message="不允许操作超级管理员用户",
            message_key="errors.rbac.cannot_operate_super_admin",
        )


async def assert_not_admin_role(
    db: AsyncSession,
    *,
    current_user_id: str,
    target_role_id: str,
) -> None:
    """非超管不允许编辑 / 删除 / 分配菜单到超管角色。

    用法：在角色管理 API 的 update / delete / assignMenus 入口先调用本函数，
    目标角色是 `platform_super` 时立即抛错拒绝。
    """
    # 自己就是超管，允许
    if await is_super_admin_user(db, current_user_id):
        return
    # 加载目标角色判断是否为超管角色
    role = (await db.execute(
        select(Role).where(
            Role.id == target_role_id, Role.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if role is not None and role.role_key == SUPER_ROLE_KEY:
        raise ForbiddenError(
            message="不允许操作超级管理员角色",
            message_key="errors.rbac.cannot_operate_super_role",
        )
