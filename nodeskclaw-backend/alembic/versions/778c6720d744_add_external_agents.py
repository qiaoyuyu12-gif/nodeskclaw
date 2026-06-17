"""add_external_agents

Revision ID: 778c6720d744
Revises: 8e5ee799a109
Create Date: 2026-06-17 12:09:28.812783

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '778c6720d744'
down_revision: Union[str, Sequence[str], None] = '8e5ee799a109'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """新增 external_agents 表，存储外部专用 Agent 的连接配置。"""
    op.create_table(
        'external_agents',
        sa.Column('org_id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('endpoint', sa.String(length=512), nullable=False),
        sa.Column('api_key_encrypted', sa.Text(), nullable=True),
        sa.Column('protocol', sa.String(length=32), server_default='openai_compatible', nullable=False),
        sa.Column('capabilities', sa.Text(), nullable=True),
        sa.Column('icon_emoji', sa.String(length=8), nullable=True),
        sa.Column('theme_color', sa.String(length=16), nullable=True),
        sa.Column('is_reachable', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('last_checked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_external_agents_deleted_at'), 'external_agents', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_external_agents_org_id'), 'external_agents', ['org_id'], unique=False)


def downgrade() -> None:
    """回滚：删除 external_agents 表。"""
    op.drop_index(op.f('ix_external_agents_org_id'), table_name='external_agents')
    op.drop_index(op.f('ix_external_agents_deleted_at'), table_name='external_agents')
    op.drop_table('external_agents')
