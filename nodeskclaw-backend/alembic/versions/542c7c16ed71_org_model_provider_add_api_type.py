"""org_model_provider_add_api_type

Revision ID: 542c7c16ed71
Revises: a51d1dbae13c
Create Date: 2026-04-08 19:34:37.513206

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '542c7c16ed71'
down_revision: Union[str, Sequence[str], None] = 'a51d1dbae13c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('org_llm_keys', sa.Column('api_type', sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column('org_llm_keys', 'api_type')
