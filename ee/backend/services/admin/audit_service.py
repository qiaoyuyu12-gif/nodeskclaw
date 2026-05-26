"""审计服务 — 统一封装 with_audit 异步上下文管理器与查询函数。

设计目标：
  1. 所有超管动作走 with_audit，禁止 service 直接 db.add(OperationAuditLog)
  2. 失败抛异常时仍写一条 "失败" 审计，details.status="failed"
  3. action 参数仅接受 AdminAction enum，运行时校验拦截裸字符串
"""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_action import AdminAction
from app.models.operation_audit_log import OperationAuditLog
from app.models.user import User

logger = logging.getLogger(__name__)


@asynccontextmanager
async def with_audit(
    db: AsyncSession,
    *,
    action: AdminAction,
    actor: User | None,
    target_type: str,
    target_id: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
    org_id: str | None = None,
    actor_ip: str | None = None,
    actor_user_agent: str | None = None,
) -> AsyncIterator[None]:
    """包裹 service 方法体；成功写入成功审计，异常写入失败审计后重新抛出。

    Args:
        db: 当前事务 session
        action: AdminAction enum（运行时校验，拒绝裸字符串）
        actor: 操作人；登录失败等 anonymous 路径传 None
        target_type: 目标资源类型（如 "org"、"user"）
        target_id: 目标资源 ID
        before: 变更前状态快照（reset_password 不可写明文）
        after: 变更后状态快照
        details: 附加字段，合并入 details JSON
        org_id: 所属组织 ID（可选）
        actor_ip: 操作人 IP（可选）
        actor_user_agent: 操作人 UA（可选）
    """
    # 运行时类型校验：拒绝裸字符串，仅接受 AdminAction enum
    if not isinstance(action, AdminAction):
        raise TypeError(
            f"with_audit 仅接受 AdminAction enum；收到 {type(action).__name__}={action!r}"
        )

    # 构建 details payload
    payload: dict[str, Any] = {
        "before": before,
        "after": after,
    }
    if details:
        # 将调用方附加字段合并进来（before/after 优先，不被 details 覆盖）
        for k, v in details.items():
            if k not in ("before", "after"):
                payload[k] = v

    try:
        yield
    except Exception as exc:  # noqa: BLE001
        # 失败路径：补写 status/error 字段后仍写审计行，再重新 raise
        payload["status"] = "failed"
        payload["error"] = str(exc)[:500]
        await _write(
            db,
            action=action,
            actor=actor,
            target_type=target_type,
            target_id=target_id,
            details=payload,
            org_id=org_id,
            actor_ip=actor_ip,
            actor_user_agent=actor_user_agent,
        )
        raise
    else:
        # 成功路径：写入 success 审计行
        payload.setdefault("status", "success")
        await _write(
            db,
            action=action,
            actor=actor,
            target_type=target_type,
            target_id=target_id,
            details=payload,
            org_id=org_id,
            actor_ip=actor_ip,
            actor_user_agent=actor_user_agent,
        )


async def _write(
    db: AsyncSession,
    *,
    action: AdminAction,
    actor: User | None,
    target_type: str,
    target_id: str,
    details: dict[str, Any],
    org_id: str | None,
    actor_ip: str | None,
    actor_user_agent: str | None,
) -> None:
    """实际写入审计行的内部函数，不负责 commit（由外层事务统一提交）。

    anonymous 路径（如登录失败）actor 为 None，actor_id 使用 "anonymous" 占位。
    """
    # 登录失败等匿名路径：actor_id 用 "anonymous" 占位（NOT NULL 列要求）
    actor_id = actor.id if actor else "anonymous"
    actor_type = "user" if actor else "anonymous"
    actor_name = actor.email if actor else None

    # 将网络信息附加到 details
    if actor_ip:
        details["ip"] = actor_ip
    if actor_user_agent:
        details["user_agent"] = actor_user_agent

    row = OperationAuditLog(
        id=str(uuid.uuid4()),
        org_id=org_id,
        action=action.value,          # 存储 enum.value（"org.create" 等字符串）
        target_type=target_type,
        target_id=target_id,
        actor_type=actor_type,
        actor_id=actor_id,
        actor_name=actor_name,
        details=details,
    )
    db.add(row)
    # flush 写入当前事务；不 commit，让外层事务与业务变更保持原子性
    await db.flush()


async def query_audit_logs(
    db: AsyncSession,
    *,
    actor_id: str | None = None,
    action: AdminAction | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[OperationAuditLog], int]:
    """审计日志查询，支持多条件过滤与分页。

    Returns:
        (rows, total): 当前页记录列表与符合条件的总数
    """
    from sqlalchemy import func as sa_func  # 延迟导入，避免循环依赖风险

    # 构建主查询与计数查询
    stmt = select(OperationAuditLog)
    count_stmt = select(sa_func.count(OperationAuditLog.id))

    # 动态拼接过滤条件
    if actor_id:
        stmt = stmt.where(OperationAuditLog.actor_id == actor_id)
        count_stmt = count_stmt.where(OperationAuditLog.actor_id == actor_id)
    if action is not None:
        stmt = stmt.where(OperationAuditLog.action == action.value)
        count_stmt = count_stmt.where(OperationAuditLog.action == action.value)
    if from_dt:
        stmt = stmt.where(OperationAuditLog.created_at >= from_dt)
        count_stmt = count_stmt.where(OperationAuditLog.created_at >= from_dt)
    if to_dt:
        stmt = stmt.where(OperationAuditLog.created_at <= to_dt)
        count_stmt = count_stmt.where(OperationAuditLog.created_at <= to_dt)

    # 先查总数，再取分页数据（按创建时间倒序）
    total = (await db.execute(count_stmt)).scalar_one()
    rows = (
        await db.execute(
            stmt.order_by(OperationAuditLog.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    return list(rows), total
