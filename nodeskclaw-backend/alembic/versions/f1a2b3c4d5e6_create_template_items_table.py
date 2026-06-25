"""create_template_items_table

Revision ID: f1a2b3c4d5e6
Revises: ee3067b5a373
Create Date: 2026-03-20 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'ee3067b5a373'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'template_items',
        sa.Column('template_id', sa.String(length=36), sa.ForeignKey('instance_templates.id'), nullable=False),
        sa.Column('item_type', sa.String(length=16), nullable=False),
        sa.Column('item_slug', sa.String(length=128), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_template_items_template_id', 'template_items', ['template_id'])
    op.create_index('ix_template_items_deleted_at', 'template_items', ['deleted_at'])
    op.create_index(
        'uq_template_item_active', 'template_items',
        ['template_id', 'item_type', 'item_slug'],
        unique=True, postgresql_where=sa.text('deleted_at IS NULL'),
    )


def downgrade() -> None:
    op.drop_index('uq_template_item_active', table_name='template_items')
    op.drop_index('ix_template_items_deleted_at', table_name='template_items')
    op.drop_index('ix_template_items_template_id', table_name='template_items')
    op.drop_table('template_items')
