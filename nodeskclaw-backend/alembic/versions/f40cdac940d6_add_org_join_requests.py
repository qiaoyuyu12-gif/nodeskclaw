"""add org join requests

Revision ID: f40cdac940d6
Revises: 4971d0b79e17
Create Date: 2026-06-05 15:57:39.773656

新增 org_join_requests 表：用户主动申请加入某个组织、由组织 admin 审核。

注：autogenerate 同时检测到一批旧表（topology_audit_logs / workspace_deploys /
plans / performance_snapshots）和 clusters 老字段，与本次变更无关，已手动剔除。
"""
from typing import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f40cdac940d6'
down_revision: str | Sequence[str] | None = '4971d0b79e17'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """新增 org_join_requests 表 + 索引（含 partial unique 索引）。"""
    op.create_table(
        'org_join_requests',
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('org_id', sa.String(length=36), nullable=False),
        sa.Column('reason', sa.String(length=500), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('reviewed_by', sa.String(length=36), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('review_note', sa.String(length=500), nullable=True),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False,
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False,
        ),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['reviewed_by'], ['users.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_org_join_requests_deleted_at'),
        'org_join_requests', ['deleted_at'], unique=False,
    )
    op.create_index(
        op.f('ix_org_join_requests_org_id'),
        'org_join_requests', ['org_id'], unique=False,
    )
    op.create_index(
        op.f('ix_org_join_requests_status'),
        'org_join_requests', ['status'], unique=False,
    )
    op.create_index(
        op.f('ix_org_join_requests_user_id'),
        'org_join_requests', ['user_id'], unique=False,
    )
    # Partial unique：同一用户对同一组织最多一条未删除的 pending 申请
    op.create_index(
        'uq_org_join_request_pending',
        'org_join_requests', ['user_id', 'org_id'],
        unique=True,
        postgresql_where=sa.text("status = 'pending' AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    """回滚：删除 org_join_requests 表及全部相关索引。"""
    op.drop_index(
        'uq_org_join_request_pending', table_name='org_join_requests',
        postgresql_where=sa.text("status = 'pending' AND deleted_at IS NULL"),
    )
    op.drop_index(
        op.f('ix_org_join_requests_user_id'), table_name='org_join_requests',
    )
    op.drop_index(
        op.f('ix_org_join_requests_status'), table_name='org_join_requests',
    )
    op.drop_index(
        op.f('ix_org_join_requests_org_id'), table_name='org_join_requests',
    )
    op.drop_index(
        op.f('ix_org_join_requests_deleted_at'), table_name='org_join_requests',
    )
    op.drop_table('org_join_requests')
