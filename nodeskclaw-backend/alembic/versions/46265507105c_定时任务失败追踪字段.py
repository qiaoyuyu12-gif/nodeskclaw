"""定时任务失败追踪字段

Revision ID: 46265507105c
Revises: 025c79cd9c1a
Create Date: 2026-04-15 02:15:03.256888

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '46265507105c'
down_revision: Union[str, Sequence[str], None] = '025c79cd9c1a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('workspace_schedules', sa.Column('consecutive_failures', sa.Integer(), server_default='0', nullable=False))
    op.add_column('workspace_schedules', sa.Column('last_succeeded_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('workspace_tasks', sa.Column('failure_reason', sa.String(length=30), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('workspace_tasks', 'failure_reason')
    op.drop_column('workspace_schedules', 'last_succeeded_at')
    op.drop_column('workspace_schedules', 'consecutive_failures')
