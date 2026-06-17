"""ExternalAgent 模型：表示运行在外部服务器上的专用 AI Agent 服务。"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class ExternalAgent(BaseModel):
    __tablename__ = "external_agents"

    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 外部 Agent 服务的基础 URL（如 http://agent.example.com:8000）
    endpoint: Mapped[str] = mapped_column(String(512), nullable=False)
    # AES-256-GCM 加密后的 API Key，base64(nonce + ciphertext)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 通信协议：openai_compatible | custom
    protocol: Mapped[str] = mapped_column(
        String(32), nullable=False, default="openai_compatible", server_default="openai_compatible"
    )
    # JSON 数组，能力标签（如 ["代码审查", "SQL生成"]），供卡片展示
    capabilities: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 卡片装饰
    icon_emoji: Mapped[str | None] = mapped_column(String(8), nullable=True)
    theme_color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # 由 /sync 端点写入，标记外部服务是否可达
    is_reachable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
