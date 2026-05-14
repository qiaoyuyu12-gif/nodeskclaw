"""SkillDefinition model for agent skills."""

from sqlalchemy import Boolean, ForeignKey, Index, JSON, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class SkillDefinition(BaseModel):
    __tablename__ = "skill_definitions"
    __table_args__ = (
        Index(
            "uq_skill_definitions_org_name",
            "org_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)  # rag_query / gene / composite
    kb_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("knowledge_bases.id"), nullable=True
    )
    config: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'::json")
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
