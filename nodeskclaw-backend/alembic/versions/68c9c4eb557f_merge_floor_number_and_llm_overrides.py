"""merge_floor_number_and_llm_overrides

Revision ID: 68c9c4eb557f
Revises: 7c6a5b4d3e2f, d8a3f1c72b05
Create Date: 2026-03-27 17:17:12.365674

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '68c9c4eb557f'
down_revision: Union[str, Sequence[str], None] = ('7c6a5b4d3e2f', 'd8a3f1c72b05')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
