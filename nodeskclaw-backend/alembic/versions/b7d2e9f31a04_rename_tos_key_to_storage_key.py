"""rename tos_key to storage_key

Revision ID: b7d2e9f31a04
Revises: a1b2c3d4e5f6
Create Date: 2026-03-25 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7d2e9f31a04'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('workspace_files', 'tos_key',
                    new_column_name='storage_key',
                    existing_type=sa.String(512))
    op.alter_column('blackboard_files', 'tos_key',
                    new_column_name='storage_key',
                    existing_type=sa.String(512))


def downgrade() -> None:
    op.alter_column('workspace_files', 'storage_key',
                    new_column_name='tos_key',
                    existing_type=sa.String(512))
    op.alter_column('blackboard_files', 'storage_key',
                    new_column_name='tos_key',
                    existing_type=sa.String(512))
