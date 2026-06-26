"""workspace add cluster_id

Revision ID: d9017e4ff2a0
Revises: 46265507105c
Create Date: 2026-04-16 17:22:53.579987

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd9017e4ff2a0'
down_revision: Union[str, Sequence[str], None] = '46265507105c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('workspaces', sa.Column('cluster_id', sa.String(length=36), nullable=True))
    op.create_index(op.f('ix_workspaces_cluster_id'), 'workspaces', ['cluster_id'], unique=False)
    op.create_foreign_key('fk_workspaces_cluster_id', 'workspaces', 'clusters', ['cluster_id'], ['id'])

    conn = op.get_bind()
    row = conn.execute(
        sa.text("SELECT id FROM clusters WHERE deleted_at IS NULL")
    ).fetchall()
    if len(row) == 1:
        cluster_id = row[0][0]
        conn.execute(
            sa.text("UPDATE workspaces SET cluster_id = :cid WHERE cluster_id IS NULL"),
            {"cid": cluster_id},
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_workspaces_cluster_id', 'workspaces', type_='foreignkey')
    op.drop_index(op.f('ix_workspaces_cluster_id'), table_name='workspaces')
    op.drop_column('workspaces', 'cluster_id')
