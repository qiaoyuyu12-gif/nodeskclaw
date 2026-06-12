"""AutomationRunner — 定时检查 automation_tasks，按配置规则触发 AI 员工执行 prompt。

触发规则：
  daily    — 在 (prev_check, now] 窗口内，exec_time 所对应的时刻是否存在
             且当天星期在 week_days 中，通过 last_fired_at 防止同窗口重复触发。
  interval — 距 last_fired_at 超过 interval_minutes 分钟（首次立即触发）。
  once     — last_fired_at 为空时触发一次，触发后将 status 改为 completed。

核心修复：
  使用与 ScheduleRunner 相同的窗口检测模式，避免 asyncio.sleep 的
  微小延迟导致整分钟被跳过。时区统一用 .astimezone() 转换，
  不再使用 .replace() 覆盖已有时区。
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

_LOCAL_TZ = timezone(timedelta(hours=8))  # UTC+8 北京时间


# ── 时间工具 ──────────────────────────────────────────────────────

def get_current_time_utc() -> datetime:
    """返回当前 UTC 时间（带时区信息）。"""
    return datetime.now(timezone.utc)


def get_local_time(tz_offset_hours: float = 8.0) -> datetime:
    """返回指定时区偏移的当前本地时间，默认 UTC+8（北京时间）。"""
    return datetime.now(timezone(timedelta(hours=tz_offset_hours)))


# ── 内部工具 ──────────────────────────────────────────────────────

def _parse_exec_time(exec_time: str | None) -> tuple[int, int] | None:
    """'HH:mm' → (hour, minute)，失败返回 None。"""
    if not exec_time:
        return None
    try:
        h, m = exec_time.split(":")
        return int(h), int(m)
    except Exception:
        return None


def _in_date_range(task: AutomationTask, day: date) -> bool:
    if task.start_date and day < task.start_date:
        return False
    if task.end_date and day > task.end_date:
        return False
    return True


def _as_utc(dt: datetime) -> datetime:
    """将任意 datetime 统一转换为 UTC（兼容 tz-aware 和 tz-naive）。"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ── 触发判断（窗口模式）──────────────────────────────────────────

def should_fire(task: AutomationTask, prev_utc: datetime, now_utc: datetime) -> bool:
    """
    判断 task 是否在 (prev_utc, now_utc] 窗口内应当触发。

    - daily   : 检查窗口内是否包含 exec_time（允许跨天搜索前后 1 天）
    - interval: 距 last_fired_at 是否超过 interval_minutes
    - once    : 还未触发 && 当前时间 >= exec_time（或无 exec_time 则立即触发）
    """
    if task.frequency == "daily":
        return _should_fire_daily(task, prev_utc, now_utc)
    elif task.frequency == "interval":
        return _should_fire_interval(task, now_utc)
    elif task.frequency == "once":
        return _should_fire_once(task, now_utc)
    return False


def _should_fire_daily(task: AutomationTask, prev_utc: datetime, now_utc: datetime) -> bool:
    parsed = _parse_exec_time(task.exec_time)
    if not parsed:
        return False
    target_h, target_m = parsed

    week_days: list[int] | None = None
    if task.week_days:
        try:
            week_days = json.loads(task.week_days)
        except Exception:
            pass

    prev_local = prev_utc.astimezone(_LOCAL_TZ)
    now_local = now_utc.astimezone(_LOCAL_TZ)

    # 检查窗口最多跨 2 个日历天（通常只有 1 天）
    for offset in range(-1, 2):
        check_date = now_local.date() + timedelta(days=offset)
        if not _in_date_range(task, check_date):
            continue
        fire_local = datetime(
            check_date.year, check_date.month, check_date.day,
            target_h, target_m, 0,
            tzinfo=_LOCAL_TZ,
        )
        # 落在 (prev, now] 窗口内
        if not (prev_local < fire_local <= now_local):
            continue
        # 检查星期（Python weekday() 0=周一，与前端约定一致）
        if week_days is not None and fire_local.weekday() not in week_days:
            continue
        # 防止同一触发时刻重复触发（last_fired_at 距 fire_local < 55s）
        if task.last_fired_at is not None:
            lf_utc = _as_utc(task.last_fired_at)
            if abs((lf_utc - fire_local.astimezone(timezone.utc)).total_seconds()) < 55:
                continue
        return True

    return False


def _should_fire_interval(task: AutomationTask, now_utc: datetime) -> bool:
    minutes = task.interval_minutes or 60
    if task.last_fired_at is None:
        return True
    lf_utc = _as_utc(task.last_fired_at)
    return (now_utc - lf_utc).total_seconds() >= minutes * 60


def _should_fire_once(task: AutomationTask, now_utc: datetime) -> bool:
    if task.last_fired_at is not None:
        return False  # 已触发

    now_local = now_utc.astimezone(_LOCAL_TZ)
    today = now_local.date()
    if not _in_date_range(task, today):
        return False

    parsed = _parse_exec_time(task.exec_time)
    if parsed:
        target_h, target_m = parsed
        if (now_local.hour, now_local.minute) < (target_h, target_m):
            return False
    return True


# ── Runner 主体 ───────────────────────────────────────────────────

class AutomationRunner:
    """每 check_interval 秒检查一次 automation_tasks，窗口模式决策触发。"""

    def __init__(self, session_factory, check_interval: int = 60):
        self._session_factory = session_factory
        self._interval = check_interval
        self._task: asyncio.Task | None = None
        self._last_check: datetime | None = None

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
        # prev 取上次检查时间；首次以 (now - interval) 兜底，覆盖刚好到点的任务
        prev = self._last_check or (now - timedelta(seconds=self._interval + 5))
        self._last_check = now

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
                    if should_fire(task, prev, now):
                        await self._fire(db, task, now)
                except Exception:
                    logger.exception("AutomationRunner: fire error for task %s", task.id)

    async def _fire(self, db: AsyncSession, task: AutomationTask, now: datetime) -> None:
        """将 prompt 写入 PG 队列，QueueConsumer 负责投递到 AI 员工。

        不直接走 MessageBus.publish()：因为 TransportMiddleware 发现实例未通过
        tunnel 连接时会返回 instance_not_connected_locally，该错误属于 NO_RETRY_ERRORS，
        消息直接进死信队列永久丢失。改用 enqueue() 持久化到 PG 队列：
        QueueConsumer 只对已连接实例出队，AI 员工离线时消息等待，重连后自动投递。
        """
        # 1. 找实例所在的活跃 workspace
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
                "AutomationRunner: instance %s not in any workspace, skipping task %s",
                task.instance_id, task.id,
            )
            return

        workspace_id: str = row[0]

        # 2. 构建 cron envelope 并写入 PG 队列
        from app.services.runtime.messaging.envelope import MessageRouting, Priority
        from app.services.runtime.messaging.ingestion.cron import build_cron_envelope
        from app.services.runtime.messaging.queue import enqueue

        envelope = build_cron_envelope(
            workspace_id=workspace_id,
            schedule_id=task.id,
            schedule_name=task.name,
            message_template=task.prompt,
        )
        # 指定 unicast 路由到对应实例
        envelope.data.routing = MessageRouting(
            mode="unicast",
            targets=[task.instance_id],
        )

        await enqueue(
            db,
            target_node_id=task.instance_id,
            workspace_id=workspace_id,
            priority=Priority.NORMAL,
            envelope=envelope.to_dict(),
        )

        # 3. 更新触发记录（enqueue 成功即视为本次触发完成）
        task.last_fired_at = now
        if task.frequency == "once":
            task.status = "completed"
        await db.commit()

        logger.info(
            "AutomationRunner: enqueued task '%s' (id=%s) → instance %s @ workspace %s",
            task.name, task.id, task.instance_id, workspace_id,
        )
