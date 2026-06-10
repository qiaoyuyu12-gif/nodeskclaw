"""add_is_manual_to_conversation

Revision ID: 45dc29a6fe76
Revises: a5e8077aa974
Create Date: 2026-06-09 17:17:51.082155

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '45dc29a6fe76'
down_revision: Union[str, Sequence[str], None] = 'a5e8077aa974'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('conversations', sa.Column(
        'is_manual', sa.Boolean(), server_default='false', nullable=False,
    ))


def downgrade() -> None:
    op.drop_column('conversations', 'is_manual')
