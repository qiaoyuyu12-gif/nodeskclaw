"""RBAC 权限决策审计：异步落库 permission_audit_logs。

第一期 **默认关闭**（settings.RBAC_AUDIT_ENABLED=False），仅当显式打开时
每次 require_perms 决策都会异步入库一条记录。

为避免阻塞主请求路径，采用 fire-and-forget 模式：
- 启动新 task 写入独立 session，失败仅打日志
- 不参与请求事务，不影响业务回滚
- 单条写入相对廉价；高 QPS 场景建议上线后用批量缓冲或下沉到日志管道

permission_audit_logs 表本身不软删，依赖外部 TTL 策略清理过期记录。
"""

import asyncio
import logging
import uuid
from typing import Final

from app.core.config import settings
from app.core.deps import async_session_factory
from app.core.rbac.scope import RbacScope
from app.models.rbac.permission_audit_log import PermissionAuditLog

logger = logging.getLogger(__name__)

# 截断 reason 字段以匹配 DB 长度
_REASON_MAX_LEN: Final[int] = 255


async def _persist(payload: dict) -> None:
    """实际入库逻辑：独立 session，不参与外部事务。"""
    try:
        async with async_session_factory() as db:
            db.add(PermissionAuditLog(**payload))
            await db.commit()
    except Exception:
        # 审计失败不可影响主请求路径，仅记日志
        logger.exception("RBAC 决策审计入库失败 payload=%s", payload)


async def log_decision_async(
    *,
    subject_type: str,
    subject_id: str,
    perms_code: str,
    scope: RbacScope,
    decision: str,
    reason: str | None,
    request_id: str | None,
) -> None:
    """异步落一条权限决策日志；RBAC_AUDIT_ENABLED=False 时直接 no-op。"""
    if not getattr(settings, "RBAC_AUDIT_ENABLED", False):
        return

    payload = {
        "id": str(uuid.uuid4()),
        "subject_type": subject_type,
        "subject_id": subject_id,
        "perms_code": perms_code,
        "scope_type": scope.type,
        "scope_id": scope.id,
        "decision": decision,
        "reason": (reason or "")[:_REASON_MAX_LEN],
        "request_id": request_id,
    }

    # fire-and-forget：不 await，不阻塞主请求；任何异常仅日志
    try:
        asyncio.create_task(_persist(payload))
    except RuntimeError:
        # 当前线程无运行中的事件循环（极少见），降级为直接落库
        logger.exception("RBAC 决策审计无法启动 task，降级同步执行")
        await _persist(payload)
