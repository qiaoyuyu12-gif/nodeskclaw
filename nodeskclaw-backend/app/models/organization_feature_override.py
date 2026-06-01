"""组织级 Feature 覆盖模型 — 在 edition_features 默认之上叠加 override。

超管可以针对某个组织强制启用或关闭某个 Feature，覆盖 edition 默认值。
每条记录对应一个 (org_id, feature_id) 组合，软删除保证历史可追溯。
"""

from sqlalchemy import Boolean, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class OrganizationFeatureOverride(BaseModel):
    """单条 (org_id, feature_id) 覆盖记录；软删 + Partial Unique Index 保唯一。

    同一 org 对同一 feature 只能存在一条未删除的覆盖记录。
    需要变更时先软删旧记录，再创建新记录，保留操作历史。
    """

    __tablename__ = "organization_feature_overrides"
    __table_args__ = (
        # Partial Unique Index：仅对未删除记录（deleted_at IS NULL）保唯一
        # 软删后旧记录不参与唯一约束，允许重新创建新覆盖记录
        Index(
            "uq_org_feature_overrides_org_feature",
            "org_id",
            "feature_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    # 目标组织 id，关联 organizations 表
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    # 目标 feature_id，与 features.yaml 中 id 字段对应
    feature_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # True = 强制启用，False = 强制关闭，覆盖 edition 默认值
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # 设置原因，便于事后追溯（可空）
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 执行操作的超管 user_id，关联 users 表
    set_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
