"""add_instance_knowledge_bases

Revision ID: 01a1d5aab1de
Revises: 45dc29a6fe76
Create Date: 2026-06-10 11:01:08.456369

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '01a1d5aab1de'
down_revision: Union[str, Sequence[str], None] = '45dc29a6fe76'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 新建 instance_knowledge_bases 关联表
    op.create_table(
        'instance_knowledge_bases',
        sa.Column('instance_id', sa.String(length=36), nullable=False),
        sa.Column('kb_id', sa.String(length=36), nullable=False),
        sa.Column('enabled', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_by', sa.String(length=36), nullable=False),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.ForeignKeyConstraint(['instance_id'], ['instances.id']),
        sa.ForeignKeyConstraint(['kb_id'], ['knowledge_bases.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_instance_knowledge_bases_deleted_at'),
        'instance_knowledge_bases', ['deleted_at'], unique=False,
    )
    op.create_index(
        op.f('ix_instance_knowledge_bases_instance_id'),
        'instance_knowledge_bases', ['instance_id'], unique=False,
    )
    op.create_index(
        'uq_instance_knowledge_bases_instance_kb',
        'instance_knowledge_bases', ['instance_id', 'kb_id'],
        unique=True, postgresql_where=sa.text('deleted_at IS NULL'),
    )
    # knowledge_bases 新增 sync 状态字段
    op.add_column('knowledge_bases', sa.Column('is_reachable', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('knowledge_bases', sa.Column('last_checked_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('knowledge_bases', 'last_checked_at')
    op.drop_column('knowledge_bases', 'is_reachable')
    op.drop_index('uq_instance_knowledge_bases_instance_kb', table_name='instance_knowledge_bases', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_index(op.f('ix_instance_knowledge_bases_instance_id'), table_name='instance_knowledge_bases')
    op.drop_index(op.f('ix_instance_knowledge_bases_deleted_at'), table_name='instance_knowledge_bases')
    op.drop_table('instance_knowledge_bases')
