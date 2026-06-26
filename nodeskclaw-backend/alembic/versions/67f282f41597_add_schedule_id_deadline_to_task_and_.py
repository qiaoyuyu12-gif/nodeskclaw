"""add schedule_id deadline to task and timeout to schedule

Revision ID: 67f282f41597
Revises: 88ee49ef3050
Create Date: 2026-04-13 17:54:43.410737

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '67f282f41597'
down_revision: Union[str, Sequence[str], None] = '88ee49ef3050'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('workspace_schedules', sa.Column('timeout_minutes', sa.Integer(), server_default='120', nullable=False))
    op.add_column('workspace_tasks', sa.Column('schedule_id', sa.String(length=36), nullable=True))
    op.add_column('workspace_tasks', sa.Column('deadline', sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f('ix_workspace_tasks_schedule_id'), 'workspace_tasks', ['schedule_id'], unique=False)
    op.create_foreign_key('fk_workspace_tasks_schedule_id', 'workspace_tasks', 'workspace_schedules', ['schedule_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_workspace_tasks_schedule_id', 'workspace_tasks', type_='foreignkey')
    op.drop_index(op.f('ix_workspace_tasks_schedule_id'), table_name='workspace_tasks')
    op.drop_column('workspace_tasks', 'deadline')
    op.drop_column('workspace_tasks', 'schedule_id')
    op.drop_column('workspace_schedules', 'timeout_minutes')
