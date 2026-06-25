"""add username and must_change_password

Revision ID: a349ffaba48f
Revises: 8d465624ee1f
Create Date: 2026-03-10 22:22:32.625440

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a349ffaba48f'
down_revision: Union[str, Sequence[str], None] = '8d465624ee1f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('username', sa.String(length=128), nullable=True))
    op.add_column('users', sa.Column('must_change_password', sa.Boolean(), server_default='false', nullable=False))
    op.create_index('uq_users_username', 'users', ['username'], unique=True, postgresql_where=sa.text('deleted_at IS NULL'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_users_username', table_name='users', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_column('users', 'must_change_password')
    op.drop_column('users', 'username')
