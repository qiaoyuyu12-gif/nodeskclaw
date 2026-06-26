"""storage_class_nullable

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-03-25 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('instances', 'storage_class',
                    existing_type=sa.String(64),
                    nullable=True,
                    server_default=None)


def downgrade() -> None:
    op.execute("UPDATE instances SET storage_class = 'nas-subpath' WHERE storage_class IS NULL")
    op.alter_column('instances', 'storage_class',
                    existing_type=sa.String(64),
                    nullable=False,
                    server_default='nas-subpath')
