"""create_instance_backups_table

Revision ID: 0fd3d44ae8b3
Revises: c3d8f952a6ea
Create Date: 2026-04-03 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0fd3d44ae8b3'
down_revision: Union[str, Sequence[str], None] = 'c3d8f952a6ea'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'instance_backups',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('instance_id', sa.String(36), sa.ForeignKey('instances.id'), nullable=False, index=True),
        sa.Column('type', sa.String(16), nullable=False, server_default='manual'),
        sa.Column('status', sa.String(16), nullable=False, server_default='pending'),
        sa.Column('config_snapshot', sa.Text(), nullable=True),
        sa.Column('storage_key', sa.String(512), nullable=True),
        sa.Column('data_size', sa.BigInteger(), nullable=True),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('triggered_by', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('org_id', sa.String(36), sa.ForeignKey('organizations.id'), nullable=True, index=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True, index=True),
    )


def downgrade() -> None:
    op.drop_table('instance_backups')
