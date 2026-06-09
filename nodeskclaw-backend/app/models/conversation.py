"""Conversation — a topology-derived group chat in a workspace."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class Conversation(BaseModel):
    __tablename__ = "conversations"
    __table_args__ = (
        Index(
            "uq_conversation_member_hash",
            "workspace_id",
            "member_hash",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    workspace_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_blackboard_group: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
    )
    is_manual: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false",
    )
    member_node_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    member_hash: Mapped[str] = mapped_column(String(16), nullable=False)
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None,
    )
    last_message_preview: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None,
    )

    workspace = relationship("Workspace")
