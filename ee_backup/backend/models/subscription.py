"""Subscription model — 租户订阅记录。"""

from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class SubscriptionStatus(str, Enum):
    active = "active"
    cancelled = "cancelled"
    expired = "expired"
    trialing = "trialing"


class Subscription(BaseModel):
    """订阅模型 - 追踪每个组织的当前/历史订阅状态。

    一个组织同一时间只能有一个 active subscription。
    """

    __tablename__ = "subscriptions"

    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True,
    )
    plan_name: Mapped[str] = mapped_column(String(32), nullable=False)

    status: Mapped[str] = mapped_column(
        String(16), default=SubscriptionStatus.active, nullable=False,
    )

    # 时间范围
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 计费相关
    billing_period: Mapped[str] = mapped_column(String(16), default="monthly", nullable=False)  # monthly / yearly
    auto_renew: Mapped[bool] = mapped_column(default=True, nullable=False)

    # 备注
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # relationships
    organization = relationship("Organization")

    created_at: Mapped[datetime] = mapped_column(server_default="now()")
    updated_at: Mapped[datetime] = mapped_column(server_default="now()", onupdate=datetime.utcnow)