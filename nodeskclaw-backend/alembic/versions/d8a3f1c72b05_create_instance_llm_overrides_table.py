"""create instance_llm_overrides table

Revision ID: d8a3f1c72b05
Revises: b7d2e9f31a04
Create Date: 2026-03-27 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd8a3f1c72b05'
down_revision: Union[str, Sequence[str], None] = 'b7d2e9f31a04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'instance_llm_overrides',
        sa.Column('instance_id', sa.String(length=36), sa.ForeignKey('instances.id'), nullable=False),
        sa.Column('provider', sa.String(length=32), nullable=False),
        sa.Column('base_url', sa.String(length=512), nullable=True),
        sa.Column('api_type', sa.String(length=32), nullable=True),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_instance_llm_overrides_deleted_at'), 'instance_llm_overrides', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_instance_llm_overrides_instance_id'), 'instance_llm_overrides', ['instance_id'], unique=False)
    op.create_index(
        'uq_instance_llm_overrides_inst_provider',
        'instance_llm_overrides',
        ['instance_id', 'provider'],
        unique=True,
        postgresql_where='deleted_at IS NULL',
    )


def downgrade() -> None:
    op.drop_index('uq_instance_llm_overrides_inst_provider', table_name='instance_llm_overrides', postgresql_where='deleted_at IS NULL')
    op.drop_index(op.f('ix_instance_llm_overrides_instance_id'), table_name='instance_llm_overrides')
    op.drop_index(op.f('ix_instance_llm_overrides_deleted_at'), table_name='instance_llm_overrides')
    op.drop_table('instance_llm_overrides')
