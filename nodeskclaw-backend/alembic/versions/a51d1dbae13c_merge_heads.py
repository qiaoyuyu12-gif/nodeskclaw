"""merge_heads

Revision ID: a51d1dbae13c
Revises: dcd8e2e3e6ad, f2a8c1d4e5b6
Create Date: 2026-04-08 19:34:22.339989

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a51d1dbae13c'
down_revision: Union[str, Sequence[str], None] = ('dcd8e2e3e6ad', 'f2a8c1d4e5b6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
