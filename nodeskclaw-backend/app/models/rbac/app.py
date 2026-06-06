"""RBAC 应用 / 入口表 `apps`（对齐 MOM `sys_app`）。

DeskClaw 第一期 seed 4 个内置应用：
  - PORTAL：用户门户（nodeskclaw-portal）
  - ADMIN：EE 管理后台（ee/nodeskclaw-frontend）
  - OPEN_API：OpenAPI 调用入口（提供给三方接入）
  - MCP_GATEWAY：MCP 协议网关（AI 客户端接入）

角色通过 `role_apps` 关联到应用，决定该角色能进入哪些入口。
"""

from sqlalchemy import (
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class App(BaseModel):
    """RBAC 应用 / 入口定义。"""

    __tablename__ = "apps"
    __table_args__ = (
        # app_code 全局唯一（未软删）
        Index(
            "uq_apps_app_code_active",
            "app_code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_apps_status", "status"),
    )

    # 应用编码，大写下划线，例如 PORTAL / ADMIN / OPEN_API / MCP_GATEWAY
    app_code: Mapped[str] = mapped_column(String(50), nullable=False)
    # 应用显示名
    app_name: Mapped[str] = mapped_column(String(100), nullable=False)
    # 应用图标（Iconify 名或 URL）
    app_icon: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # 入口 URL，例如 /portal/home
    app_url: Mapped[str] = mapped_column(String(500), nullable=False)
    # 应用描述（前端卡片提示）
    app_desc: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 排序号，越小越靠前
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 状态：'0'=正常 / '1'=停用
    status: Mapped[str] = mapped_column(String(1), nullable=False, default="0")
