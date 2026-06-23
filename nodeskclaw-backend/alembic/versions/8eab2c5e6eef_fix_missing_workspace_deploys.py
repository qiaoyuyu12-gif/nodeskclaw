"""fix_missing_workspace_deploys

workspace_deploys 表在合并迁移路径中未被正确执行，此迁移通过
IF NOT EXISTS 方式补建，对已存在该表的环境无影响。

Revision ID: 8eab2c5e6eef
Revises: 778c6720d744
Create Date: 2026-06-17 14:54:51.187276

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON


# revision identifiers, used by Alembic.
revision: str = '8eab2c5e6eef'
down_revision: Union[str, Sequence[str], None] = '778c6720d744'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """补建 workspace_deploys 表（幂等，表已存在则跳过）。"""
    conn = op.get_bind()
    # to_regclass 返回 None 说明表不存在，此时才执行建表
    result = conn.execute(sa.text("SELECT to_regclass('public.workspace_deploys')"))
    if result.scalar() is not None:
        return

    op.create_table(
        "workspace_deploys",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("workspace_id", sa.String(36), nullable=True),
        sa.Column("template_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("total_agents", sa.Integer(), nullable=False),
        sa.Column("completed_agents", sa.Integer(), nullable=False),
        sa.Column("failed_agents", sa.Integer(), nullable=False),
        sa.Column("progress_detail", JSON, nullable=False),
        sa.Column("config_snapshot", JSON, nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["template_id"], ["workspace_templates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workspace_deploys_workspace_id", "workspace_deploys", ["workspace_id"])
    op.create_index("ix_workspace_deploys_template_id", "workspace_deploys", ["template_id"])
    op.create_index("ix_workspace_deploys_status", "workspace_deploys", ["status"])
    op.create_index("ix_workspace_deploys_created_by", "workspace_deploys", ["created_by"])
    op.create_index("ix_workspace_deploys_org_id", "workspace_deploys", ["org_id"])
    op.create_index("ix_workspace_deploys_deleted_at", "workspace_deploys", ["deleted_at"])


def downgrade() -> None:
    # 本迁移是修复补丁，downgrade 不执行删除以避免数据丢失
    pass

