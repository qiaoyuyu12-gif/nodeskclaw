"""自动化任务 CRUD — portal 用户级别接口。"""

import json
import logging
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel as PydanticBase
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.security import get_current_user
from app.models.automation_task import AutomationTask
from app.models.base import not_deleted
from app.models.instance import Instance
from app.schemas.common import ApiResponse
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Schema ────────────────────────────────────────────────

class AutomationTaskCreate(PydanticBase):
    instance_id: str
    name: str
    prompt: str
    frequency: str = "daily"          # daily / interval / once
    exec_time: str | None = None       # HH:mm
    interval_minutes: int | None = None
    week_days: list[int] | None = None  # [0,1,2,3,4] 周一=0
    start_date: date | None = None
    end_date: date | None = None
    push_notification: bool = False


class AutomationTaskUpdate(PydanticBase):
    instance_id: str | None = None
    name: str | None = None
    prompt: str | None = None
    frequency: str | None = None
    exec_time: str | None = None
    interval_minutes: int | None = None
    week_days: list[int] | None = None
    start_date: date | None = None
    end_date: date | None = None
    push_notification: bool | None = None
    status: str | None = None


class AutomationTaskInfo(PydanticBase):
    id: str
    instance_id: str
    instance_name: str
    name: str
    prompt: str
    frequency: str
    exec_time: str | None
    interval_minutes: int | None
    week_days: list[int] | None
    start_date: date | None
    end_date: date | None
    push_notification: bool
    status: str
    created_at: str

    class Config:
        from_attributes = True


# ── 内部辅助 ──────────────────────────────────────────────

async def _get_task_or_404(task_id: str, user_id: str, db: AsyncSession) -> AutomationTask:
    result = await db.execute(
        select(AutomationTask).where(
            AutomationTask.id == task_id,
            AutomationTask.user_id == user_id,
            not_deleted(AutomationTask),
        )
    )
    task = result.scalar_one_or_none()
    if not task:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


def _to_info(task: AutomationTask, instance_name: str) -> AutomationTaskInfo:
    """将 ORM 对象转换为响应 Schema。"""
    week_days_parsed: list[int] | None = None
    if task.week_days:
        try:
            week_days_parsed = json.loads(task.week_days)
        except Exception:
            week_days_parsed = None

    return AutomationTaskInfo(
        id=task.id,
        instance_id=task.instance_id,
        instance_name=instance_name,
        name=task.name,
        prompt=task.prompt,
        frequency=task.frequency,
        exec_time=task.exec_time,
        interval_minutes=task.interval_minutes,
        week_days=week_days_parsed,
        start_date=task.start_date,
        end_date=task.end_date,
        push_notification=task.push_notification,
        status=task.status,
        created_at=task.created_at.isoformat(),
    )


# ── 路由 ──────────────────────────────────────────────────

@router.get("", response_model=ApiResponse[list[AutomationTaskInfo]])
async def list_automation_tasks(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前用户的所有自动化任务（含 AI 员工名称）。"""
    result = await db.execute(
        select(AutomationTask)
        .where(AutomationTask.user_id == current_user.id, not_deleted(AutomationTask))
        .order_by(AutomationTask.created_at.desc())
    )
    tasks = result.scalars().all()

    # 批量查实例名称，避免 N+1
    instance_ids = list({t.instance_id for t in tasks})
    instance_map: dict[str, str] = {}
    if instance_ids:
        inst_result = await db.execute(
            select(Instance.id, Instance.name).where(
                Instance.id.in_(instance_ids),
                not_deleted(Instance),
            )
        )
        instance_map = {row.id: row.name for row in inst_result}

    items = [_to_info(t, instance_map.get(t.instance_id, "")) for t in tasks]
    return ApiResponse(data=items)


@router.post("", response_model=ApiResponse[AutomationTaskInfo])
async def create_automation_task(
    body: AutomationTaskCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """新建自动化任务。"""
    # 验证实例存在且属于用户可见范围（user_id 对应已有 instance_member 记录由前端保证，这里只做基本存在检查）
    inst_result = await db.execute(
        select(Instance).where(Instance.id == body.instance_id, not_deleted(Instance))
    )
    instance = inst_result.scalar_one_or_none()
    if not instance:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="AI 员工不存在")

    task = AutomationTask(
        user_id=current_user.id,
        instance_id=body.instance_id,
        name=body.name.strip(),
        prompt=body.prompt.strip(),
        frequency=body.frequency,
        exec_time=body.exec_time,
        interval_minutes=body.interval_minutes,
        week_days=json.dumps(body.week_days) if body.week_days is not None else None,
        start_date=body.start_date,
        end_date=body.end_date,
        push_notification=body.push_notification,
        status="active",
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return ApiResponse(data=_to_info(task, instance.name))


@router.patch("/{task_id}", response_model=ApiResponse[AutomationTaskInfo])
async def update_automation_task(
    task_id: str,
    body: AutomationTaskUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新自动化任务（仅限任务所有者）。"""
    task = await _get_task_or_404(task_id, current_user.id, db)

    instance_name = ""
    if body.instance_id is not None:
        inst_result = await db.execute(
            select(Instance).where(Instance.id == body.instance_id, not_deleted(Instance))
        )
        instance = inst_result.scalar_one_or_none()
        if not instance:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="AI 员工不存在")
        task.instance_id = body.instance_id
        instance_name = instance.name
    else:
        inst_result = await db.execute(
            select(Instance.name).where(Instance.id == task.instance_id, not_deleted(Instance))
        )
        row = inst_result.first()
        instance_name = row[0] if row else ""

    if body.name is not None:
        task.name = body.name.strip()
    if body.prompt is not None:
        task.prompt = body.prompt.strip()
    if body.frequency is not None:
        task.frequency = body.frequency
    if body.exec_time is not None:
        task.exec_time = body.exec_time
    if body.interval_minutes is not None:
        task.interval_minutes = body.interval_minutes
    if body.week_days is not None:
        task.week_days = json.dumps(body.week_days)
    if body.start_date is not None:
        task.start_date = body.start_date
    if body.end_date is not None:
        task.end_date = body.end_date
    if body.push_notification is not None:
        task.push_notification = body.push_notification
    if body.status is not None:
        task.status = body.status

    await db.commit()
    await db.refresh(task)
    return ApiResponse(data=_to_info(task, instance_name))


@router.delete("/{task_id}", response_model=ApiResponse)
async def delete_automation_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """软删除自动化任务。"""
    task = await _get_task_or_404(task_id, current_user.id, db)
    task.soft_delete()
    await db.commit()
    return ApiResponse(message="任务已删除")
