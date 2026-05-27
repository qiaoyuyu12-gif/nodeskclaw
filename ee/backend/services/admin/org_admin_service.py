"""组织管理 service：CRUD + 实例校验 + 审计。

职责：
  - create_org: 创建组织（slug 唯一校验 + 审计）
  - update_org: 更新组织字段（前后快照 + 审计）
  - delete_org: 软删除组织（含运行中实例拦截 + 审计）
  - _get_org_or_404: 内部辅助，查 org 不存在时抛 409
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_action import AdminAction
from app.models.instance import Instance, InstanceStatus
from app.models.org_membership import OrgMembership
from app.models.organization import Organization
from app.models.user import User
from ee.backend.services.admin import audit_service
from ee.backend.services.admin.errors import AdminErrorCode, raise_admin_error


async def create_org(
    db: AsyncSession,
    *,
    admin: User,
    name: str,
    slug: str,
    plan: str,
    max_instances: int,
    max_cpu_total: str,
    max_mem_total: str,
    max_storage_total: str,
    max_collaboration_depth: int,
    cluster_id: str | None,
) -> Organization:
    """创建新组织。

    Args:
        db: 当前事务 session
        admin: 执行操作的超管用户（用于审计 actor）
        name: 组织显示名称
        slug: 组织唯一标识符（URL-safe）
        plan: 套餐类型（如 "free"）
        max_instances: 实例数上限
        max_cpu_total: 总 CPU 配额
        max_mem_total: 总内存配额
        max_storage_total: 总存储配额
        max_collaboration_depth: 协作深度上限
        cluster_id: 专属集群 ID（None 表示使用共享集群）

    Returns:
        新创建的 Organization 对象（已 flush，未 commit）

    Raises:
        HTTPException(409): slug 已存在时抛 ORG_SLUG_CONFLICT
    """
    # 检查 slug 是否已被未软删除的组织占用
    dup = (
        await db.execute(
            select(Organization).where(
                Organization.slug == slug,
                Organization.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if dup:
        raise_admin_error(
            AdminErrorCode.ORG_SLUG_CONFLICT,
            message_key="errors.admin.org_slug_conflict",
            message=f"Slug already exists: {slug}",
        )

    # 构建新组织对象并落库
    org = Organization(
        name=name,
        slug=slug,
        plan=plan,
        max_instances=max_instances,
        max_cpu_total=max_cpu_total,
        max_mem_total=max_mem_total,
        max_storage_total=max_storage_total,
        max_collaboration_depth=max_collaboration_depth,
        cluster_id=cluster_id,
        is_active=True,
    )
    db.add(org)
    # flush 获取 org.id（自动生成），但不提交事务
    await db.flush()

    # 写入 org.create 审计记录（成功路径）
    async with audit_service.with_audit(
        db,
        action=AdminAction.ORG_CREATE,
        actor=admin,
        target_type="org",
        target_id=org.id,
        org_id=org.id,
        before=None,
        after={"name": name, "slug": slug, "plan": plan},
    ):
        pass  # 业务逻辑在 flush 前已完成，with_audit 负责写入审计行
    return org


async def update_org(
    db: AsyncSession,
    *,
    admin: User,
    org_id: str,
    patch: dict[str, Any],
) -> Organization:
    """更新组织字段（仅更新 patch 中指定的字段）。

    Args:
        db: 当前事务 session
        admin: 执行操作的超管用户
        org_id: 目标组织 ID
        patch: 要更新的字段字典

    Returns:
        更新后的 Organization 对象

    Raises:
        HTTPException(409): 组织不存在时抛 ORG_NOT_FOUND
    """
    org = await _get_org_or_404(db, org_id)
    # 记录变更前快照（仅记录 patch 中涉及的字段）
    before = {k: getattr(org, k) for k in patch.keys()}

    async with audit_service.with_audit(
        db,
        action=AdminAction.ORG_UPDATE,
        actor=admin,
        target_type="org",
        target_id=org.id,
        org_id=org.id,
        before=before,
        after=patch,
    ):
        # 在 with_audit 上下文内执行字段更新与 flush
        for k, v in patch.items():
            setattr(org, k, v)
        await db.flush()
    return org


async def delete_org(
    db: AsyncSession,
    *,
    admin: User,
    org_id: str,
) -> None:
    """软删除组织（设置 deleted_at）。

    删除前校验：组织不存在 → ORG_NOT_FOUND；含运行中实例 → ORG_HAS_RUNNING_INSTANCES。

    Args:
        db: 当前事务 session
        admin: 执行操作的超管用户
        org_id: 目标组织 ID

    Raises:
        HTTPException(409): 组织不存在或含运行中实例
    """
    org = await _get_org_or_404(db, org_id)

    # 统计该组织下处于 running / deploying 状态的实例数量
    running = (
        await db.execute(
            select(sa_func.count(Instance.id)).where(
                Instance.org_id == org_id,
                Instance.deleted_at.is_(None),
                Instance.status.in_([InstanceStatus.running, InstanceStatus.deploying]),
            )
        )
    ).scalar_one()

    if running:
        raise_admin_error(
            AdminErrorCode.ORG_HAS_RUNNING_INSTANCES,
            message_key="errors.admin.org_has_running_instances",
            message="Cannot delete org with running instances",
        )

    async with audit_service.with_audit(
        db,
        action=AdminAction.ORG_DELETE,
        actor=admin,
        target_type="org",
        target_id=org.id,
        org_id=org.id,
        before={"name": org.name, "slug": org.slug},
        after=None,
    ):
        # 软删除：仅设置 deleted_at，不物理删除行
        org.deleted_at = datetime.utcnow()
        await db.flush()


async def _get_org_or_404(db: AsyncSession, org_id: str) -> Organization:
    """查询未软删除的组织，不存在时抛 ORG_NOT_FOUND（409）。

    Args:
        db: 当前事务 session
        org_id: 目标组织 ID

    Returns:
        Organization 对象

    Raises:
        HTTPException(409): 组织不存在
    """
    org = (
        await db.execute(
            select(Organization).where(
                Organization.id == org_id,
                Organization.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if not org:
        raise_admin_error(
            AdminErrorCode.ORG_NOT_FOUND,
            message_key="errors.admin.org_not_found",
            message="Organization not found",
        )
    return org  # type: ignore[return-value]  # raise_admin_error 已确保此处 org 不为 None


# ────────────────────────────────────────────────────────────────────────────
# 成员管理
# ────────────────────────────────────────────────────────────────────────────


async def list_members(db: AsyncSession, *, org_id: str) -> list[OrgMembership]:
    """列出组织的所有未软删除成员。

    Args:
        db: 当前事务 session
        org_id: 目标组织 ID

    Returns:
        OrgMembership 列表
    """
    return list(
        (
            await db.execute(
                select(OrgMembership).where(
                    OrgMembership.org_id == org_id,
                    OrgMembership.deleted_at.is_(None),
                )
            )
        ).scalars().all()
    )


async def add_member(
    db: AsyncSession, *, admin: User, org_id: str, user_id: str, role: str
) -> OrgMembership:
    """向组织添加成员。

    Args:
        db: 当前事务 session
        admin: 执行操作的超管用户（用于审计 actor）
        org_id: 目标组织 ID
        user_id: 要添加的用户 ID
        role: 成员角色（admin / operator / member）

    Returns:
        新创建的 OrgMembership 对象（已 flush，未 commit）

    Raises:
        HTTPException(409): 组织不存在、用户不存在或用户已是成员
    """
    # 校验组织和用户是否存在
    await _get_org_or_404(db, org_id)
    await _ensure_user_exists(db, user_id)

    # 检查是否已是该 org 的成员（Partial Unique Index 覆盖此场景）
    dup = (
        await db.execute(
            select(OrgMembership).where(
                OrgMembership.org_id == org_id,
                OrgMembership.user_id == user_id,
                OrgMembership.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if dup:
        raise_admin_error(
            AdminErrorCode.ORG_MEMBER_DUPLICATE,
            message_key="errors.admin.org_member_duplicate",
            message="Member already exists",
        )

    # 创建成员关系
    m = OrgMembership(org_id=org_id, user_id=user_id, role=role)
    db.add(m)
    await db.flush()

    # 写入审计记录
    async with audit_service.with_audit(
        db,
        action=AdminAction.ORG_MEMBER_ADD,
        actor=admin,
        target_type="org_member",
        target_id=f"{org_id}:{user_id}",
        org_id=org_id,
        before=None,
        after={"role": role},
    ):
        pass
    return m


async def update_member_role(
    db: AsyncSession, *, admin: User, org_id: str, user_id: str, role: str
) -> OrgMembership:
    """更新组织成员角色。

    若将唯一 admin 降级为非 admin，则拒绝操作。

    Args:
        db: 当前事务 session
        admin: 执行操作的超管用户
        org_id: 目标组织 ID
        user_id: 目标用户 ID
        role: 新角色

    Returns:
        更新后的 OrgMembership 对象

    Raises:
        HTTPException(409): 成员不存在或试图降级最后一个 admin
    """
    m = await _get_member_or_404(db, org_id, user_id)

    # 若当前角色是 admin 且新角色不是 admin，需确保还有其他 admin
    if m.role == "admin" and role != "admin":
        await _ensure_not_last_admin(db, org_id, user_id)

    before = {"role": m.role}
    async with audit_service.with_audit(
        db,
        action=AdminAction.ORG_MEMBER_UPDATE,
        actor=admin,
        target_type="org_member",
        target_id=f"{org_id}:{user_id}",
        org_id=org_id,
        before=before,
        after={"role": role},
    ):
        # 在 with_audit 上下文内执行更新与 flush
        m.role = role
        await db.flush()
    return m


async def remove_member(
    db: AsyncSession, *, admin: User, org_id: str, user_id: str
) -> None:
    """从组织中移除成员（软删除）。

    若该成员是 org 的最后一个 admin，则拒绝操作。

    Args:
        db: 当前事务 session
        admin: 执行操作的超管用户
        org_id: 目标组织 ID
        user_id: 要移除的用户 ID

    Raises:
        HTTPException(409): 成员不存在或试图移除最后一个 admin
    """
    m = await _get_member_or_404(db, org_id, user_id)

    # admin 角色移除时需确保还有其他 admin
    if m.role == "admin":
        await _ensure_not_last_admin(db, org_id, user_id)

    async with audit_service.with_audit(
        db,
        action=AdminAction.ORG_MEMBER_REMOVE,
        actor=admin,
        target_type="org_member",
        target_id=f"{org_id}:{user_id}",
        org_id=org_id,
        before={"role": m.role},
        after=None,
    ):
        # 软删除：仅设置 deleted_at
        m.deleted_at = datetime.utcnow()
        await db.flush()


async def _ensure_user_exists(db: AsyncSession, user_id: str) -> None:
    """确认用户存在且未被软删除，否则抛 USER_NOT_FOUND（409）。

    Args:
        db: 当前事务 session
        user_id: 目标用户 ID

    Raises:
        HTTPException(409): 用户不存在
    """
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


async def _get_member_or_404(db: AsyncSession, org_id: str, user_id: str) -> OrgMembership:
    """查询未软删除的 org 成员，不存在时抛 ORG_MEMBER_NOT_FOUND（409）。

    Args:
        db: 当前事务 session
        org_id: 目标组织 ID
        user_id: 目标用户 ID

    Returns:
        OrgMembership 对象

    Raises:
        HTTPException(409): 成员不存在
    """
    m = (
        await db.execute(
            select(OrgMembership).where(
                OrgMembership.org_id == org_id,
                OrgMembership.user_id == user_id,
                OrgMembership.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if not m:
        raise_admin_error(
            AdminErrorCode.ORG_MEMBER_NOT_FOUND,
            message_key="errors.admin.org_member_not_found",
            message="Org member not found",
        )
    return m  # type: ignore[return-value]  # raise_admin_error 已确保此处 m 不为 None


async def _ensure_not_last_admin(db: AsyncSession, org_id: str, user_id: str) -> None:
    """确认指定用户不是 org 的最后一个 admin，否则抛 ORG_LAST_ADMIN_FORBIDDEN（409）。

    通过排除当前用户后计算剩余 admin 数量来判断。

    Args:
        db: 当前事务 session
        org_id: 目标组织 ID
        user_id: 当前要移除/降级的用户 ID

    Raises:
        HTTPException(409): 该用户是唯一 admin
    """
    # 计算排除 user_id 后的剩余 admin 数量
    count = (
        await db.execute(
            select(sa_func.count(OrgMembership.id)).where(
                OrgMembership.org_id == org_id,
                OrgMembership.role == "admin",
                OrgMembership.deleted_at.is_(None),
                OrgMembership.user_id != user_id,
            )
        )
    ).scalar_one()
    if count == 0:
        raise_admin_error(
            AdminErrorCode.ORG_LAST_ADMIN_FORBIDDEN,
            message_key="errors.admin.org_last_admin_forbidden",
            message="Cannot remove the last admin of org",
        )
