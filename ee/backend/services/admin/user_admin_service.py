"""用户管理 service：标志切换、密码重置、级联软删；含自我保护 + 最后超管守卫。"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime
from typing import Any

from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_action import AdminAction
from app.models.admin_membership import AdminMembership
from app.models.org_membership import OrgMembership
from app.models.user import User
from app.models.user_llm_config import UserLlmConfig
from app.models.user_llm_key import UserLlmKey
from app.core.password import hash_password
from ee.backend.services.admin import audit_service
from ee.backend.services.admin.errors import AdminErrorCode, raise_admin_error

logger = logging.getLogger(__name__)


async def update_user(
    db: AsyncSession, *, admin: User, user_id: str, patch: dict[str, Any]
) -> User:
    """更新用户字段，含自我保护与最后超管守卫，并写入审计记录。"""
    user = await _get_user_or_404(db, user_id)
    _enforce_self_protection(admin, user, patch)
    # 仅当要撤销超管权限时才检查最后超管守卫
    if patch.get("is_super_admin") is False and user.is_super_admin:
        await _ensure_not_last_super_admin(db, user.id)

    before = {k: getattr(user, k) for k in patch.keys()}
    async with audit_service.with_audit(
        db,
        action=AdminAction.USER_UPDATE,
        actor=admin,
        target_type="user",
        target_id=user.id,
        before=before,
        after=patch,
    ):
        for k, v in patch.items():
            setattr(user, k, v)
        await db.flush()
    return user


async def reset_password(
    db: AsyncSession, *, admin: User, user_id: str
) -> str:
    """重置用户密码并强制下次登录时修改；返回明文临时密码（不写入审计详情）。"""
    user = await _get_user_or_404(db, user_id)
    temp = secrets.token_urlsafe(12)
    user.password_hash = hash_password(temp)
    user.must_change_password = True
    async with audit_service.with_audit(
        db,
        action=AdminAction.USER_RESET_PASSWORD,
        actor=admin,
        target_type="user",
        target_id=user.id,
        before=None,
        after=None,
        details={"note": "password reset; plaintext intentionally excluded"},
    ):
        await db.flush()
    return temp


async def delete_user(
    db: AsyncSession, *, admin: User, user_id: str
) -> None:
    """软删除用户并级联软删 OrgMembership / AdminMembership / UserLlmKey / UserLlmConfig。"""
    user = await _get_user_or_404(db, user_id)
    if user.id == admin.id:
        raise_admin_error(
            AdminErrorCode.SELF_DELETE_FORBIDDEN,
            message_key="errors.admin.self_delete_forbidden",
            message="Cannot delete yourself",
        )
    if user.is_super_admin:
        await _ensure_not_last_super_admin(db, user.id)

    now = datetime.utcnow()
    async with audit_service.with_audit(
        db,
        action=AdminAction.USER_DELETE,
        actor=admin,
        target_type="user",
        target_id=user.id,
        before={"email": user.email, "is_super_admin": user.is_super_admin},
        after=None,
        details={"cascade": ["org_membership", "admin_membership", "user_llm_key", "user_llm_config"]},
    ):
        user.deleted_at = now
        user.deleted_by = admin.id
        # 级联软删关联数据（按设计 §4.3）
        for table in (OrgMembership, AdminMembership, UserLlmKey, UserLlmConfig):
            rows = (
                await db.execute(
                    select(table).where(
                        table.user_id == user.id,
                        table.deleted_at.is_(None),
                    )
                )
            ).scalars().all()
            for r in rows:
                r.deleted_at = now
        await db.flush()


def _enforce_self_protection(admin: User, target: User, patch: dict[str, Any]) -> None:
    """拦截管理员对自身账号的危险操作（停用 / 撤超管）。"""
    if target.id != admin.id:
        return
    if patch.get("is_active") is False:
        raise_admin_error(
            AdminErrorCode.SELF_DEACTIVATE_FORBIDDEN,
            message_key="errors.admin.self_deactivate_forbidden",
            message="Cannot deactivate yourself",
        )
    if patch.get("is_super_admin") is False:
        raise_admin_error(
            AdminErrorCode.SELF_DEMOTE_SUPER_ADMIN_FORBIDDEN,
            message_key="errors.admin.self_demote_super_admin_forbidden",
            message="Cannot revoke your own super admin",
        )


async def _ensure_not_last_super_admin(db: AsyncSession, exclude_user_id: str) -> None:
    """确保撤销后还有至少 1 个超管存在，否则抛错。"""
    count = (
        await db.execute(
            select(sa_func.count(User.id)).where(
                User.is_super_admin.is_(True),
                User.deleted_at.is_(None),
                User.id != exclude_user_id,
            )
        )
    ).scalar_one()
    if count == 0:
        raise_admin_error(
            AdminErrorCode.LAST_SUPER_ADMIN_FORBIDDEN,
            message_key="errors.admin.last_super_admin_forbidden",
            message="Cannot remove the last super admin",
        )


async def _get_user_or_404(db: AsyncSession, user_id: str) -> User:
    """查询用户，不存在或已软删则抛 404 错误。"""
    u = (
        await db.execute(
            select(User).where(User.id == user_id, User.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if not u:
        raise_admin_error(
            AdminErrorCode.USER_NOT_FOUND,
            message_key="errors.admin.user_not_found",
            message="User not found",
        )
    return u
