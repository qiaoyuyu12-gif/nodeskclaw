"""add_automation_tasks

Revision ID: 91e87ce21726
Revises: 01a1d5aab1de
Create Date: 2026-06-11 17:31:05.647309

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '91e87ce21726'
down_revision: Union[str, Sequence[str], None] = '01a1d5aab1de'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'automation_tasks',
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('instance_id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('prompt', sa.Text(), nullable=False),
        sa.Column('frequency', sa.String(length=16), nullable=False),
        sa.Column('exec_time', sa.String(length=8), nullable=True),
        sa.Column('interval_minutes', sa.Integer(), nullable=True),
        sa.Column('week_days', sa.Text(), nullable=True),
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('push_notification', sa.Boolean(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['instance_id'], ['instances.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_automation_tasks_deleted_at'), 'automation_tasks', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_automation_tasks_instance_id'), 'automation_tasks', ['instance_id'], unique=False)
    op.create_index(op.f('ix_automation_tasks_user_id'), 'automation_tasks', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_automation_tasks_user_id'), table_name='automation_tasks')
    op.drop_index(op.f('ix_automation_tasks_instance_id'), table_name='automation_tasks')
    op.drop_index(op.f('ix_automation_tasks_deleted_at'), table_name='automation_tasks')
    op.drop_table('automation_tasks')
