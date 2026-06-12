"""AutomationRunner — 定时检查 automation_tasks，按配置规则触发 AI 员工执行 prompt。

触发规则：
  daily    — 当前时间匹配 exec_time（HH:mm）且当天星期在 week_days 中；
             以 last_fired_at 防止同分钟重复触发。
  interval — 距 last_fired_at 超过 interval_minutes 分钟（首次立即触发）。
  once     — last_fired_at 为空时触发一次，触发后将 status 改为 completed。

投递通路：
  通过 WorkspaceAgent 找到实例所在的第一个活跃 workspace，
  再调用 send_system_message_to_agents 将 prompt 注入消息总线。
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.automation_task import AutomationTask
from app.models.base import not_deleted
from app.models.instance import Instance
from app.models.workspace_agent import WorkspaceAgent

logger = logging.getLogger(__name__)

# ── 获取当前时间工具函数 ──────────────────────────────────────────

def get_current_time_utc() -> datetime:
    """返回当前 UTC 时间（带时区信息）。"""
    return datetime.now(timezone.utc)


def get_local_time(tz_offset_hours: float = 8.0) -> datetime:
    """返回指定时区偏移的当前本地时间，默认 UTC+8（北京时间）。"""
    tz = timezone(timedelta(hours=tz_offset_hours))
    return datetime.now(tz)


# ── 触发条件判断 ──────────────────────────────────────────────────

def _parse_exec_time(exec_time: str | None) -> tuple[int, int] | None:
    """将 'HH:mm' 解析为 (hour, minute)，解析失败返回 None。"""
    if not exec_time:
        return None
    try:
        h, m = exec_time.split(":")
        return int(h), int(m)
    except Exception:
        return None


def _in_date_range(task: AutomationTask, today: date) -> bool:
    """检查 today 是否在任务的生效日期区间内（None 表示不限）。"""
    if task.start_date and today < task.start_date:
        return False
    if task.end_date and today > task.end_date:
        return False
    return True


def should_fire(task: AutomationTask, now: datetime) -> bool:
    """判断任务是否应在 now 触发。now 须为带时区的 UTC 时间。"""
    # 转换为 UTC+8 本地时间做时刻比较
    local = now.astimezone(timezone(timedelta(hours=8)))
    today = local.date()

    if not _in_date_range(task, today):
        return False

    if task.frequency == "daily":
        time_parsed = _parse_exec_time(task.exec_time)
        if not time_parsed:
            return False
        target_h, target_m = time_parsed
        if local.hour != target_h or local.minute != target_m:
            return False

        # 检查星期（0=周一，与 Python weekday() 一致）
        if task.week_days:
            try:
                wd_list: list[int] = json.loads(task.week_days)
                if local.weekday() not in wd_list:
                    return False
            except Exception:
                pass  # 解析失败则不过滤星期

        # 防止同分钟重复触发（last_fired_at 距今 < 58s）
        if task.last_fired_at:
            elapsed = (now - task.last_fired_at.replace(tzinfo=timezone.utc)).total_seconds()
            if elapsed < 58:
                return False
        return True

    elif task.frequency == "interval":
        minutes = task.interval_minutes or 60
        if task.last_fired_at is None:
            return True
        elapsed = (now - task.last_fired_at.replace(tzinfo=timezone.utc)).total_seconds()
        return elapsed >= minutes * 60

    elif task.frequency == "once":
        if task.last_fired_at is not None:
            return False  # 已触发过
        # 若设了 exec_time，当天必须到达该时刻才触发
        time_parsed = _parse_exec_time(task.exec_time)
        if time_parsed:
            target_h, target_m = time_parsed
            if (local.hour, local.minute) < (target_h, target_m):
                return False
        return True

    return False


# ── Runner 主体 ───────────────────────────────────────────────────

class AutomationRunner:
    """每 check_interval 秒检查一次 automation_tasks，按规则触发 AI 员工执行任务。"""

    def __init__(self, session_factory, check_interval: int = 60):
        self._session_factory = session_factory
        self._interval = check_interval
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())
        logger.info("AutomationRunner started (interval=%ds)", self._interval)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("AutomationRunner stopped")

    async def _loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._interval)
                await self._check()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("AutomationRunner loop error")
                await asyncio.sleep(30)

    async def _check(self) -> None:
        now = get_current_time_utc()
        async with self._session_factory() as db:
            result = await db.execute(
                select(AutomationTask).where(
                    AutomationTask.status == "active",
                    not_deleted(AutomationTask),
                )
            )
            tasks = result.scalars().all()

            for task in tasks:
                try:
                    if should_fire(task, now):
                        await self._fire(db, task, now)
                except Exception:
                    logger.exception(
                        "AutomationRunner: fire error for task %s", task.id
                    )

    async def _fire(self, db: AsyncSession, task: AutomationTask, now: datetime) -> None:
        """投递 prompt 到对应 AI 员工，并更新 last_fired_at。"""
        # 1. 查找实例所在的活跃 workspace
        wa_result = await db.execute(
            select(WorkspaceAgent.workspace_id)
            .join(Instance, Instance.id == WorkspaceAgent.instance_id)
            .where(
                WorkspaceAgent.instance_id == task.instance_id,
                not_deleted(WorkspaceAgent),
                not_deleted(Instance),
            )
            .limit(1)
        )
        row = wa_result.first()
        if not row:
            logger.warning(
                "AutomationRunner: instance %s not found in any workspace, skipping task %s",
                task.instance_id, task.id,
            )
            return

        workspace_id: str = row[0]

        # 2. 通过消息总线将 prompt 发给 AI 员工
        from app.services.collaboration_service import send_system_message_to_agents
        await send_system_message_to_agents(
            workspace_id=workspace_id,
            agent_ids=[task.instance_id],
            message=task.prompt,
            db=db,
            mention_targets=[task.instance_id],
        )

        # 3. 更新触发记录
        task.last_fired_at = now
        if task.frequency == "once":
            task.status = "completed"

        await db.commit()

        logger.info(
            "AutomationRunner: fired task '%s' (id=%s) → instance %s @ workspace %s",
            task.name, task.id, task.instance_id, workspace_id,
        )
