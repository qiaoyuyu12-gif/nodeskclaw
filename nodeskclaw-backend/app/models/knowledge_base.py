"""KnowledgeBase model for RAGFlow integration."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class KnowledgeBase(BaseModel):
    __tablename__ = "knowledge_bases"

    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    ragflow_kb_id: Mapped[str] = mapped_column(String(256), nullable=False)
    ragflow_endpoint: Mapped[str] = mapped_column(String(512), nullable=False)
    # AES-256-GCM encrypted, stored as base64(nonce + ciphertext)
    api_key_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="doc", server_default="doc"
    )
    # 由 /sync 端点写入，标记 RAGFlow 连接是否可达
    is_reachable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
