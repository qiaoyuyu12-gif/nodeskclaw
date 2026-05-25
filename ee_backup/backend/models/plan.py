"""Plan model — 套餐/订阅方案定义。"""

from datetime import datetime
from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class Plan(BaseModel):
    """套餐模型 - 定义不同订阅层级的资源配额和功能限制。

    Organization.plan 字段关联到 Plan.name，
    一个组织同一时间只能有一个 active subscription。
    """

    __tablename__ = "plans"

    name: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 资源配额
    max_instances: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    max_cpu_per_instance: Mapped[str] = mapped_column(String(16), default="2", nullable=False)
    max_mem_per_instance: Mapped[str] = mapped_column(String(16), default="4Gi", nullable=False)
    max_storage_per_instance: Mapped[str] = mapped_column(String(16), default="100Gi", nullable=False)
    max_total_cpu: Mapped[str] = mapped_column(String(16), default="8", nullable=False)
    max_total_mem: Mapped[str] = mapped_column(String(16), default="16Gi", nullable=False)
    max_total_storage: Mapped[str] = mapped_column(String(16), default="500Gi", nullable=False)

    # 允许的实例规格列表（JSON 数组）
    allowed_specs: Mapped[list] = mapped_column(
        JSONB, default=list, server_default="[]", nullable=False,
    )

    # 功能开关（JSON 对象）
    features: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False,
    )

    # 集群配置
    dedicated_cluster: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # 计费
    price_monthly: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 分
    price_yearly: Mapped[int] = mapped_column(Integer, nullable=True)  # 分

    # 状态
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(server_default="now()")
    updated_at: Mapped[datetime] = mapped_column(server_default="now()", onupdate=datetime.utcnow)