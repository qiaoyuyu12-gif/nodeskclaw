"""add instance health_status

Revision ID: c4a1f2b89d03
Revises: 7318dfeb7c3f
Create Date: 2026-03-18
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = 'c4a1f2b89d03'
down_revision: Union[str, Sequence[str], None] = '7318dfeb7c3f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('instances', sa.Column(
        'health_status', sa.String(16), nullable=False, server_default='unknown',
    ))


def downgrade() -> None:
    op.drop_column('instances', 'health_status')
