"""add_gene_source_registry

Revision ID: ee3067b5a373
Revises: c4a1f2b89d03
Create Date: 2026-03-20 15:30:59.069134

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'ee3067b5a373'
down_revision: Union[str, Sequence[str], None] = 'c4a1f2b89d03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('genes', sa.Column('source_registry', sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column('genes', 'source_registry')
