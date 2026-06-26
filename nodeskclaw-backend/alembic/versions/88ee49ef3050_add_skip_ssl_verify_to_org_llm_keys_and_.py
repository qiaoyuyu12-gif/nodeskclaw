"""add skip_ssl_verify to org_llm_keys and user_llm_keys

Revision ID: 88ee49ef3050
Revises: 542c7c16ed71
Create Date: 2026-04-10 16:38:18.966839

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '88ee49ef3050'
down_revision: Union[str, Sequence[str], None] = '542c7c16ed71'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('org_llm_keys', sa.Column('skip_ssl_verify', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('user_llm_keys', sa.Column('skip_ssl_verify', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('user_llm_keys', 'skip_ssl_verify')
    op.drop_column('org_llm_keys', 'skip_ssl_verify')
