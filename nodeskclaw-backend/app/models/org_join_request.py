"""组织加入申请模型：用户主动申请加入某个组织，由该组织管理员审核。

与 Invitation（管理员邀请用户）相对的反向流程：
- Invitation: admin → user 邀请加入组织
- OrgJoinRequest: user → org 申请加入组织

字段语义参考 Invitation；状态机参考 GeneReviewStatus 的 pending/approved/rejected
模式，外加用户自行撤回时的 cancelled 终态。
"""

from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


# 状态机：pending → approved/rejected/cancelled（三种终态）
# - cancelled 仅在申请者本人主动撤回时使用，与审核者拒绝（rejected）区分开
class OrgJoinRequestStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    cancelled = "cancelled"


class OrgJoinRequest(BaseModel):
    """用户申请加入某个组织的待审记录。

    Partial unique 索引 `uq_org_join_request_pending` 限制：
      同一 user_id × org_id 组合，未删除且 status='pending' 的记录只能有一条。
    其他终态（approved/rejected/cancelled）不受限，允许历史多次申请。
    """

    __tablename__ = "org_join_requests"
    __table_args__ = (
        Index(
            "uq_org_join_request_pending",
            "user_id", "org_id",
            unique=True,
            postgresql_where=text("status = 'pending' AND deleted_at IS NULL"),
        ),
    )

    # 申请者 user_id
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True,
    )
    # 目标组织 org_id
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True,
    )
    # 申请理由（可选，500 字以内）
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 当前状态：pending/approved/rejected/cancelled
    status: Mapped[str] = mapped_column(
        String(16), default=OrgJoinRequestStatus.pending, nullable=False, index=True,
    )
    # 审核人 user_id（approve/reject 时回填，cancelled 不填）
    reviewed_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True,
    )
    # 审核时间（与 reviewed_by 同步回填）
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    # 审核备注（拒绝原因等，500 字以内）
    review_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
