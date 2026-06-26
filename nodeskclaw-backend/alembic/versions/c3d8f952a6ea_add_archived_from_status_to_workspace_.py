"""add_archived_from_status_to_workspace_tasks

Revision ID: c3d8f952a6ea
Revises: 68c9c4eb557f
Create Date: 2026-04-02 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d8f952a6ea'
down_revision: Union[str, Sequence[str], None] = '68c9c4eb557f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'workspace_tasks',
        sa.Column('archived_from_status', sa.String(20), nullable=True),
    )
    op.execute(
        "UPDATE workspace_tasks "
        "SET archived_from_status = 'done' "
        "WHERE status = 'archived' AND archived_from_status IS NULL"
    )


def downgrade() -> None:
    op.drop_column('workspace_tasks', 'archived_from_status')
