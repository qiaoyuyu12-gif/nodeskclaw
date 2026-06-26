"""add_floor_number_to_blackboard_replies

Revision ID: 7c6a5b4d3e2f
Revises: b7d2e9f31a04
Create Date: 2026-03-27 14:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c6a5b4d3e2f'
down_revision: Union[str, Sequence[str], None] = 'b7d2e9f31a04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'blackboard_replies',
        sa.Column('floor_number', sa.Integer(), nullable=True),
    )

    op.execute("""
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY post_id
                    ORDER BY created_at, id
                ) AS floor_number
            FROM blackboard_replies
            WHERE deleted_at IS NULL
        )
        UPDATE blackboard_replies AS replies
        SET floor_number = ranked.floor_number
        FROM ranked
        WHERE replies.id = ranked.id
    """)

    op.execute("""
        UPDATE blackboard_replies
        SET floor_number = 1
        WHERE floor_number IS NULL
    """)

    op.alter_column('blackboard_replies', 'floor_number', nullable=False)
    op.create_index(
        'uq_blackboard_reply_post_floor_active',
        'blackboard_replies',
        ['post_id', 'floor_number'],
        unique=True,
        postgresql_where=sa.text('deleted_at IS NULL'),
    )


def downgrade() -> None:
    op.drop_index(
        'uq_blackboard_reply_post_floor_active',
        table_name='blackboard_replies',
        postgresql_where=sa.text('deleted_at IS NULL'),
    )
    op.drop_column('blackboard_replies', 'floor_number')
