"""AutomationTask — 用户配置的自动化定时任务。"""

from datetime import datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class AutomationTask(BaseModel):
    __tablename__ = "automation_tasks"

    # 所属用户
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    # 关联的 AI 员工（Instance）
    instance_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("instances.id"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)

    # 执行频率：daily / interval / once
    frequency: Mapped[str] = mapped_column(String(16), nullable=False, default="daily")
    # HH:mm，daily/once 使用
    exec_time: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # 按间隔模式的分钟数
    interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # JSON 数组，如 "[0,1,2,3,4]"，daily 模式的星期选择（0=周一）
    week_days: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 生效日期区间（均可为空，表示不限）
    start_date: Mapped[str | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[str | None] = mapped_column(Date, nullable=True)

    # 执行完成后是否发送通知
    push_notification: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    # 任务状态：active / paused / completed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")

    # 最近一次触发时间（用于防重复触发和 interval 计时）
    last_fired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
