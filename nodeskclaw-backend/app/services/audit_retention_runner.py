"""审计日志保留期清理 — 默认 90 天物理删除，沿用 ScheduleRunner 异步轮询模式。

设计参考 docs/superpowers/specs/2026-05-26-super-admin-features-design.md §7.3。
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.operation_audit_log import OperationAuditLog

logger = logging.getLogger(__name__)

# 从环境变量读取配置，模块加载时固定
_DEFAULT_RETENTION_DAYS = int(os.getenv("AUDIT_RETENTION_DAYS", "90"))
_ENABLED = os.getenv("AUDIT_RETENTION_ENABLED", "true").lower() == "true"
_RUN_HOUR_LOCAL = 3  # 每天 03:00 本地时间触发


async def purge_expired_audit_logs(
    db: AsyncSession,
    *,
    retention_days: int = _DEFAULT_RETENTION_DAYS,
    batch_limit: int = 100_000,
) -> int:
    """单次清理超期审计日志；返回删除行数。分批删除避免长时间锁表。"""
    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    total_deleted = 0
    while True:
        # 先 SELECT 出待删 id，再 DELETE IN (ids)，兼容不支持 LIMIT 的 DELETE 语法
        ids = (
            await db.execute(
                select(OperationAuditLog.id)
                .where(OperationAuditLog.created_at < cutoff)
                .limit(batch_limit)
            )
        ).scalars().all()
        if not ids:
            break
        result = await db.execute(
            delete(OperationAuditLog).where(OperationAuditLog.id.in_(ids))
        )
        total_deleted += result.rowcount or 0
        await db.flush()
        # 取出行数小于 batch_limit 说明已无更多数据
        if len(ids) < batch_limit:
            break
    logger.info("[audit_retention] deleted %d rows older than %dd", total_deleted, retention_days)
    return total_deleted


class AuditRetentionRunner:
    """每天 03:00 本地时间触发审计日志清理；通过 asyncio 异步任务驱动，与 ScheduleRunner 保持相同模式。"""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()

    async def _loop(self) -> None:
        """等待到下一个 03:00，执行清理，循环直到收到停止信号。"""
        while not self._stopping.is_set():
            now = datetime.now()
            target = now.replace(hour=_RUN_HOUR_LOCAL, minute=0, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            try:
                # 等待至目标时间或停止信号，超时后执行清理
                await asyncio.wait_for(
                    self._stopping.wait(),
                    timeout=(target - now).total_seconds(),
                )
                return  # 收到停止信号
            except asyncio.TimeoutError:
                pass  # 超时即到达目标时间，执行清理

            # 延迟 import 避免启动期循环依赖
            from app.core.deps import async_session_factory
            async with async_session_factory() as db:
                try:
                    await purge_expired_audit_logs(db)
                    await db.commit()
                except Exception as exc:  # noqa: BLE001
                    logger.exception("[audit_retention] purge failed: %s", exc)
                    await db.rollback()

    def start(self) -> None:
        """启动后台清理任务（幂等：重复调用不会创建多个 task）。"""
        if not _ENABLED:
            logger.info("[audit_retention] disabled via env (AUDIT_RETENTION_ENABLED=false)")
            return
        if self._task and not self._task.done():
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "[audit_retention] started (retention=%dd, run_hour=%02d:00)",
            _DEFAULT_RETENTION_DAYS,
            _RUN_HOUR_LOCAL,
        )

    async def stop(self) -> None:
        """通知后台任务停止并等待其退出。"""
        self._stopping.set()
        if self._task:
            await self._task


# 模块级单例，供 lifespan 调用
audit_retention_runner = AuditRetentionRunner()
