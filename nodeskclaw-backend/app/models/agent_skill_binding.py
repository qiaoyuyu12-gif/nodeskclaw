"""AgentSkillBinding model for agent-skill relationships."""

from sqlalchemy import Boolean, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class AgentSkillBinding(BaseModel):
    __tablename__ = "agent_skill_bindings"
    __table_args__ = (
        Index(
            "uq_agent_skill_bindings_instance_skill",
            "instance_id",
            "skill_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    instance_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("instances.id"), nullable=False, index=True
    )
    skill_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("skill_definitions.id"), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
