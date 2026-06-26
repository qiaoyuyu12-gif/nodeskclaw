"""add started_at to workspace_tasks

Revision ID: 025c79cd9c1a
Revises: 67f282f41597
Create Date: 2026-04-13 20:52:57.464798

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '025c79cd9c1a'
down_revision: Union[str, Sequence[str], None] = '67f282f41597'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('workspace_tasks', sa.Column('started_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('workspace_tasks', 'started_at')
