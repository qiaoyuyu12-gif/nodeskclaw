"""add_thinking_to_external_agent_messages

Revision ID: a3f9b2c1d8e0
Revises: 0e84015e8bd6
Create Date: 2026-06-30 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a3f9b2c1d8e0'
down_revision: Union[str, Sequence[str], None] = '0e84015e8bd6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'external_agent_messages',
        sa.Column('thinking', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('external_agent_messages', 'thinking')
