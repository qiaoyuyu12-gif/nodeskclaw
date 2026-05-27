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
