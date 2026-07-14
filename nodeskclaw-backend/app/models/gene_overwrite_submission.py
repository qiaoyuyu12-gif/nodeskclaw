"""nodeskclaw-backend/app/models/gene_overwrite_submission.py

Fork 覆盖 org/public scope 时的审核暂存记录。genes 表的 partial unique
index（uq_genes_name_org_active / uq_genes_slug_org_active）语义是"同一
scope 内任意时刻只能有一条未软删的同名/同 slug 记录"，不区分审核状态——
如果不软删旧行就先插入一条同名的 pending 新行，会直接撞上这两条唯一索引。
所以待审核的覆盖内容放在这张独立的表里，不占用 genes 表的唯一索引位置，
approve 时才把内容真正搬进 genes 表（同时软删旧行）。
"""

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class GeneOverwriteSubmission(BaseModel):
    __tablename__ = "gene_overwrite_submissions"
    __table_args__ = (
        Index("ix_gene_overwrite_submissions_target_gene_id", "target_gene_id"),
        Index("ix_gene_overwrite_submissions_review_status", "review_status"),
    )

    # 本次提交打算替换掉的那一条 Gene.id（也就是 fork_gene_to_library 里的
    # existing_name）。approve 时会把这一行软删。
    target_gene_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("genes.id"), nullable=False,
    )
    # fork 源头 gene 的 id；本地来源时有值，外部聚合器来源时为空
    source_gene_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("genes.id"), nullable=True,
    )
    # 继承自 source，approve 时原样赋给新插入的 Gene 行
    lineage_group_id: Mapped[str] = mapped_column(String(36), nullable=False)

    # 以下字段是本次提交要写入的完整内容快照，approve 时原样搬进新的 Gene 行，
    # 字段类型跟 Gene 对应字段保持一致
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    short_description: Mapped[str | None] = mapped_column(String(256), nullable=True)
    category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tags: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    icon: Mapped[str | None] = mapped_column(String(32), nullable=True)
    version: Mapped[str] = mapped_column(String(16), nullable=False)
    manifest: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    dependencies: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array
    synergies: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array

    # 目标归属（resolve_target_attrs 算出来的）
    visibility: Mapped[str] = mapped_column(String(16), nullable=False)
    org_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=True,
    )
    created_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True,
    )

    # 复用 GeneReviewStatus 的字符串值：pending_owner -> approved/rejected
    review_status: Mapped[str] = mapped_column(String(16), nullable=False)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 没有 is_published 字段——这张表里的记录永远代表"还没生效的提议"，
    # approve 之后内容被搬进 genes 表，is_published 才有意义。
