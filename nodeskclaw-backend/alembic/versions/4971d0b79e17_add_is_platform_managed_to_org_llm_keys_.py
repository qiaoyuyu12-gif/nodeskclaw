"""add is_platform_managed to org_llm_keys and backfill minimax

Revision ID: 4971d0b79e17
Revises: fed0e4f7dfa9
Create Date: 2026-06-05 14:41:24.510590

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '4971d0b79e17'
down_revision: Union[str, Sequence[str], None] = 'fed0e4f7dfa9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 新增 is_platform_managed 字段，默认 false（组织 BYOK）
    op.add_column(
        'org_llm_keys',
        sa.Column(
            'is_platform_managed',
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    # 回填：历史 minimax-* 行视为平台托管（Working Plan 旧语义）
    op.execute(
        """
        UPDATE org_llm_keys
           SET is_platform_managed = TRUE
         WHERE provider LIKE 'minimax-%%'
           AND deleted_at IS NULL
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('org_llm_keys', 'is_platform_managed')
