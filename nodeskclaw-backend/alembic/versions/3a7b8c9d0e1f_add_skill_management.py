"""add_skill_management

Revision ID: 3a7b8c9d0e1f
Revises: b9f5520c1ffb
Create Date: 2026-05-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON


revision: str = "3a7b8c9d0e1f"
down_revision: Union[str, Sequence[str], None] = "b9f5520c1ffb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create knowledge_bases table
    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("ragflow_kb_id", sa.String(256), nullable=False),
        sa.Column("ragflow_endpoint", sa.String(512), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False, server_default="doc"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_bases_org_id", "knowledge_bases", ["org_id"])
    op.create_index("ix_knowledge_bases_deleted_at", "knowledge_bases", ["deleted_at"])

    # Create skill_definitions table
    op.create_table(
        "skill_definitions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("kb_id", sa.String(36), nullable=True),
        sa.Column("config", JSON, nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["kb_id"], ["knowledge_bases.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_skill_definitions_org_id", "skill_definitions", ["org_id"])
    op.create_index("ix_skill_definitions_deleted_at", "skill_definitions", ["deleted_at"])
    op.create_index(
        "uq_skill_definitions_org_name",
        "skill_definitions",
        ["org_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # Create agent_skill_bindings table
    op.create_table(
        "agent_skill_bindings",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("instance_id", sa.String(36), nullable=False),
        sa.Column("skill_id", sa.String(36), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["instance_id"], ["instances.id"]),
        sa.ForeignKeyConstraint(["skill_id"], ["skill_definitions.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_skill_bindings_instance_id", "agent_skill_bindings", ["instance_id"])
    op.create_index("ix_agent_skill_bindings_deleted_at", "agent_skill_bindings", ["deleted_at"])
    op.create_index(
        "uq_agent_skill_bindings_instance_skill",
        "agent_skill_bindings",
        ["instance_id", "skill_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_agent_skill_bindings_instance_skill", table_name="agent_skill_bindings")
    op.drop_index("ix_agent_skill_bindings_deleted_at", table_name="agent_skill_bindings")
    op.drop_index("ix_agent_skill_bindings_instance_id", table_name="agent_skill_bindings")
    op.drop_table("agent_skill_bindings")
    op.drop_index("uq_skill_definitions_org_name", table_name="skill_definitions")
    op.drop_index("ix_skill_definitions_deleted_at", table_name="skill_definitions")
    op.drop_index("ix_skill_definitions_org_id", table_name="skill_definitions")
    op.drop_table("skill_definitions")
    op.drop_index("ix_knowledge_bases_deleted_at", table_name="knowledge_bases")
    op.drop_index("ix_knowledge_bases_org_id", table_name="knowledge_bases")
    op.drop_table("knowledge_bases")
