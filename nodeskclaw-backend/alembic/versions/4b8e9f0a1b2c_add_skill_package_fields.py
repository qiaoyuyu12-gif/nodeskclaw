"""add_skill_package_fields

Revision ID: 4b8e9f0a1b2c
Revises: 3a7b8c9d0e1f
Create Date: 2026-05-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4b8e9f0a1b2c"
down_revision: Union[str, Sequence[str], None] = "3a7b8c9d0e1f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "skill_definitions",
        sa.Column("description", sa.Text(), nullable=True),
    )
    op.add_column(
        "skill_definitions",
        sa.Column("package_path", sa.String(512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("skill_definitions", "package_path")
    op.drop_column("skill_definitions", "description")
