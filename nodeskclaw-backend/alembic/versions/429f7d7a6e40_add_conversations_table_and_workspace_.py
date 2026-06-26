"""add_conversations_table_and_workspace_message_conversation_id

Revision ID: 429f7d7a6e40
Revises: 6d9c9b0c2481
Create Date: 2026-04-23 20:18:11.573841

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '429f7d7a6e40'
down_revision: Union[str, Sequence[str], None] = '6d9c9b0c2481'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("is_blackboard_group", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("member_node_ids", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("member_hash", sa.String(16), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_message_preview", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_conversations_workspace_id", "conversations", ["workspace_id"])
    op.create_index("ix_conversations_deleted_at", "conversations", ["deleted_at"])
    op.create_index(
        "uq_conversation_member_hash",
        "conversations",
        ["workspace_id", "member_hash"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.add_column(
        "workspace_messages",
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_workspace_messages_conversation_id", "workspace_messages", ["conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_workspace_messages_conversation_id", table_name="workspace_messages")
    op.drop_column("workspace_messages", "conversation_id")
    op.drop_index("uq_conversation_member_hash", table_name="conversations")
    op.drop_index("ix_conversations_deleted_at", table_name="conversations")
    op.drop_index("ix_conversations_workspace_id", table_name="conversations")
    op.drop_table("conversations")
