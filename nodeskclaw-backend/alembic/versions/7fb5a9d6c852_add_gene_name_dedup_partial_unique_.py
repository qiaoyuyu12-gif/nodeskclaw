"""add gene name dedup partial unique indexes

Revision ID: 7fb5a9d6c852
Revises: a3f9b2c1d8e0
Create Date: 2026-07-10 10:09:27.157440

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7fb5a9d6c852'
down_revision: Union[str, Sequence[str], None] = 'a3f9b2c1d8e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 按 scope (personal/org_private/public) 分别对 lower(trim(name)) 建 partial unique index，
    # 与应用层 get_gene_by_name_in_scope() 的查重语义对应，作为并发场景下的数据库兜底约束。
    op.create_index(
        'uq_genes_name_personal_active', 'genes',
        [sa.text('lower(trim(name))'), 'created_by'],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND visibility = 'personal'"),
    )
    op.create_index(
        'uq_genes_name_org_active', 'genes',
        [sa.text('lower(trim(name))'), 'org_id'],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND visibility = 'org_private'"),
    )
    op.create_index(
        'uq_genes_name_public_active', 'genes',
        [sa.text('lower(trim(name))')],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND visibility = 'public'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_genes_name_public_active', table_name='genes', postgresql_where=sa.text("deleted_at IS NULL AND visibility = 'public'"))
    op.drop_index('uq_genes_name_org_active', table_name='genes', postgresql_where=sa.text("deleted_at IS NULL AND visibility = 'org_private'"))
    op.drop_index('uq_genes_name_personal_active', table_name='genes', postgresql_where=sa.text("deleted_at IS NULL AND visibility = 'personal'"))
