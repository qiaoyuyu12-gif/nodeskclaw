"""外部 Agent 聊天会话与消息模型。"""

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class ExternalAgentChatSession(BaseModel):
    """外部 Agent 聊天会话（用户与单个 Agent 可开多个独立对话）。"""

    __tablename__ = "external_agent_chat_sessions"

    org_id: Mapped[str] = mapped_column(String(36), nullable=False)
    agent_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("external_agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)


class ExternalAgentMessage(BaseModel):
    """外部 Agent 聊天消息（user / assistant 两种角色）。

    attachments 仅存 storage_key，不存 URL（URL 按需生成以防失效）。
    跟随 session 级联删除，自身不做软删除。
    """

    __tablename__ = "external_agent_messages"

    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("external_agent_chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    attachments: Mapped[list | None] = mapped_column(JSONB, nullable=True)
