"""add gene lineage group id and overwrite submission

新增 genes.lineage_group_id 列（并通过并查集回填历史 fork 链的血缘分组），
以及 gene_overwrite_submissions 覆盖提交审核表。

Revision ID: b50c716fd16f
Revises: 7fb5a9d6c852
Create Date: 2026-07-14 15:30:38.234405

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import table, column


# revision identifiers, used by Alembic.
revision: str = 'b50c716fd16f'
down_revision: Union[str, Sequence[str], None] = '7fb5a9d6c852'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _find(parent: dict[str, str], x: str) -> str:
    """并查集：查找 x 所在集合的根节点（路径压缩）。"""
    root = x
    while parent[root] != root:
        root = parent[root]
    while parent[x] != root:
        parent[x], x = root, parent[x]
    return root


def _union(parent: dict[str, str], a: str, b: str) -> None:
    """并查集：合并 a、b 所在的两个集合（按根节点字符串大小定新根，保证结果确定性）。"""
    ra, rb = _find(parent, a), _find(parent, b)
    if ra == rb:
        return
    if ra < rb:
        parent[rb] = ra
    else:
        parent[ra] = rb


def upgrade() -> None:
    """Upgrade schema."""
    # ── 1. lineage_group_id：加列 + 并查集回填 ──────────────────────────
    # 先允许为空以便回填，回填完成后再收紧为 NOT NULL
    op.add_column("genes", sa.Column("lineage_group_id", sa.String(36), nullable=True))
    op.create_index("ix_genes_lineage_group_id", "genes", ["lineage_group_id"])

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, parent_gene_id FROM genes")).fetchall()

    # 基于 (id, parent_gene_id) 构建并查集，得到每条 fork 链的连通分量
    parent: dict[str, str] = {}
    for row in rows:
        parent.setdefault(row.id, row.id)
        if row.parent_gene_id:
            parent.setdefault(row.parent_gene_id, row.parent_gene_id)
            _union(parent, row.id, row.parent_gene_id)

    # 按连通分量分组，同组成员共享同一个 lineage_group_id（取根节点 id 作为分组值）
    group_members: dict[str, list[str]] = {}
    for row in rows:
        root = _find(parent, row.id)
        group_members.setdefault(root, []).append(row.id)

    genes_table = table("genes", column("id", sa.String), column("lineage_group_id", sa.String))
    for root, members in group_members.items():
        conn.execute(
            genes_table.update().where(genes_table.c.id.in_(members)).values(lineage_group_id=root)
        )

    op.alter_column("genes", "lineage_group_id", nullable=False)

    # ── 2. gene_overwrite_submissions 新表 ───────────────────────────────
    op.create_table(
        "gene_overwrite_submissions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("target_gene_id", sa.String(36), sa.ForeignKey("genes.id"), nullable=False),
        sa.Column("source_gene_id", sa.String(36), sa.ForeignKey("genes.id"), nullable=True),
        sa.Column("lineage_group_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("short_description", sa.String(256), nullable=True),
        sa.Column("category", sa.String(32), nullable=True),
        sa.Column("tags", sa.Text(), nullable=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("source_ref", sa.String(512), nullable=True),
        sa.Column("icon", sa.String(32), nullable=True),
        sa.Column("version", sa.String(16), nullable=False),
        sa.Column("manifest", sa.Text(), nullable=True),
        sa.Column("dependencies", sa.Text(), nullable=True),
        sa.Column("synergies", sa.Text(), nullable=True),
        sa.Column("visibility", sa.String(16), nullable=False),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("review_status", sa.String(16), nullable=False),
        sa.Column("reject_reason", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_gene_overwrite_submissions_target_gene_id",
        "gene_overwrite_submissions", ["target_gene_id"],
    )
    op.create_index(
        "ix_gene_overwrite_submissions_review_status",
        "gene_overwrite_submissions", ["review_status"],
    )
    # BaseModel.deleted_at 声明了 index=True，此处补建对应索引，
    # 与仓库内其他 BaseModel 派生表迁移的惯例保持一致（避免 alembic check 产生噪音 diff）
    op.create_index(
        "ix_gene_overwrite_submissions_deleted_at",
        "gene_overwrite_submissions", ["deleted_at"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_gene_overwrite_submissions_deleted_at", table_name="gene_overwrite_submissions")
    op.drop_index("ix_gene_overwrite_submissions_review_status", table_name="gene_overwrite_submissions")
    op.drop_index("ix_gene_overwrite_submissions_target_gene_id", table_name="gene_overwrite_submissions")
    op.drop_table("gene_overwrite_submissions")
    op.drop_index("ix_genes_lineage_group_id", table_name="genes")
    op.drop_column("genes", "lineage_group_id")
