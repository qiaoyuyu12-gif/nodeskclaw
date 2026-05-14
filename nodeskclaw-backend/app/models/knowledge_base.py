"""KnowledgeBase model for RAGFlow integration."""

from sqlalchemy import ForeignKey, String, Text
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
