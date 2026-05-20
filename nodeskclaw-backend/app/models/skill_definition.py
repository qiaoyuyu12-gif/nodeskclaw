"""SkillDefinition model for agent skills."""

from sqlalchemy import Boolean, ForeignKey, Index, JSON, String, Text, text
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
    # 技能类型：rag_query（知识库问答）/ gene（Gene 能力）/ composite（复合）/ tool（Python 工具）
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    kb_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("knowledge_bases.id"), nullable=True
    )
    # 轻量配置参数（如 rag_query 的 top_k，tool 的 entry / input_schema）
    config: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'::json")
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    package_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # manifest：将文件夹内所有文件内联序列化的 JSON，供 agent 直接命中使用
    # 结构：{entry, scripts: {filename: code}, assets: {path: content}, references: {path: content}}
    manifest: Mapped[dict | None] = mapped_column(JSON, nullable=True)
