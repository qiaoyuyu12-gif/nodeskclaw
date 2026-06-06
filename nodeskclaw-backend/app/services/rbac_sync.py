"""RBAC 双写适配器：把 legacy 字段（is_super_admin / OrgMembership.role /
AdminMembership.role / WorkspaceMember.role）的变更同步反映到 subject_roles。

第一期由 seed 阶段的 _backfill_subject_roles_from_legacy 完成一次性全量回填，
运行时业务写入 legacy 字段时通过本模块的 grant_role / revoke_role 保持增量同步。

接入策略（第一期）：
- 创建 legacy 成员关系 → grant_role
- 更新 legacy 角色字符串 → 先 revoke_role(旧)，再 grant_role(新)
- 软删 legacy 成员关系 → revoke_role
- User.is_super_admin True/False 切换 → grant/revoke `platform_super`

幂等保证：grant_role 命中唯一索引时跳过；revoke_role 找不到时跳过。
所有写入都会主动 invalidate_subject 失效 RBAC 缓存，避免 TTL 内权限不刷新。
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac.cache import invalidate_subject
from app.models.rbac.role import Role
from app.models.rbac.subject_role import SubjectRole

logger = logging.getLogger(__name__)


async def _get_role_by_key(db: AsyncSession, role_key: str) -> Role | None:
    """按 role_key 加载未软删的角色。"""
    return (await db.execute(
        select(Role).where(
            Role.role_key == role_key,
            Role.deleted_at.is_(None),
        )
    )).scalar_one_or_none()


async def grant_role(
    db: AsyncSession,
    *,
    subject_type: str,
    subject_id: str,
    role_key: str,
    scope_type: str,
    scope_id: str | None,
    granted_by: str | None = None,
    granted_reason: str | None = None,
) -> None:
    """幂等授予角色：命中唯一索引时跳过，否则追加一条 subject_roles。

    参数：
        subject_type: user / agent
        subject_id: user.id 或 instance.id
        role_key: 角色权限标识，必须与 roles 表中已存在的内置或自定义角色对齐
        scope_type: platform / org / workspace / instance
        scope_id: scope 具体 ID；platform 时为 None
        granted_by: 授权人 user.id（seed 写入时为 None）
        granted_reason: 授权来源标签，例如 seed:org_membership / manual_grant
    """
    role = await _get_role_by_key(db, role_key)
    if role is None:
        # 角色不存在通常意味着 seed 漏了或拼写错误，严重问题应快速暴露
        raise RuntimeError(
            f"RBAC grant_role 失败：角色 role_key={role_key!r} 不存在",
        )

    # 五元组幂等查询：subject + role + scope 已存在则跳过
    exists = (await db.execute(
        select(SubjectRole).where(
            SubjectRole.subject_type == subject_type,
            SubjectRole.subject_id == subject_id,
            SubjectRole.role_id == role.id,
            SubjectRole.scope_type == scope_type,
            SubjectRole.scope_id == scope_id,
            SubjectRole.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if exists is not None:
        return

    db.add(SubjectRole(
        subject_type=subject_type,
        subject_id=subject_id,
        role_id=role.id,
        scope_type=scope_type,
        scope_id=scope_id,
        granted_by=granted_by,
        granted_reason=granted_reason,
    ))
    # 失效该 subject 的 LRU 缓存，确保下次请求重新加载授权
    invalidate_subject(subject_type, subject_id)


async def revoke_role(
    db: AsyncSession,
    *,
    subject_type: str,
    subject_id: str,
    role_key: str,
    scope_type: str,
    scope_id: str | None,
) -> None:
    """幂等撤销角色：找不到对应授权时静默跳过。

    撤销采用软删（设置 deleted_at），保留历史授权审计能力。
    """
    role = await _get_role_by_key(db, role_key)
    if role is None:
        logger.warning(
            "RBAC revoke_role 跳过：未找到角色 role_key=%s（subject=%s/%s）",
            role_key, subject_type, subject_id,
        )
        return

    row = (await db.execute(
        select(SubjectRole).where(
            SubjectRole.subject_type == subject_type,
            SubjectRole.subject_id == subject_id,
            SubjectRole.role_id == role.id,
            SubjectRole.scope_type == scope_type,
            SubjectRole.scope_id == scope_id,
            SubjectRole.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if row is None:
        return

    # 标记软删，BaseModel.soft_delete 写入 deleted_at
    row.soft_delete()
    invalidate_subject(subject_type, subject_id)


async def replace_role(
    db: AsyncSession,
    *,
    subject_type: str,
    subject_id: str,
    old_role_key: str,
    new_role_key: str,
    scope_type: str,
    scope_id: str | None,
    granted_by: str | None = None,
    granted_reason: str | None = None,
) -> None:
    """便捷方法：legacy 角色字符串变更场景的 revoke + grant 组合。

    例如 OrgMembership.role 从 member 改为 admin：
        await replace_role(db, subject_type='user', subject_id=user_id,
                           old_role_key='org_member', new_role_key='org_admin',
                           scope_type='org', scope_id=org_id,
                           granted_reason='org_membership_update')
    """
    if old_role_key == new_role_key:
        return
    await revoke_role(
        db,
        subject_type=subject_type, subject_id=subject_id,
        role_key=old_role_key, scope_type=scope_type, scope_id=scope_id,
    )
    await grant_role(
        db,
        subject_type=subject_type, subject_id=subject_id,
        role_key=new_role_key, scope_type=scope_type, scope_id=scope_id,
        granted_by=granted_by, granted_reason=granted_reason,
    )
