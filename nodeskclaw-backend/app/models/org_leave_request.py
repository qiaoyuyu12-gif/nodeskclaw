"""组织退出申请模型：成员主动申请退出某个已加入的组织，由该组织管理员审核。

与 OrgJoinRequest 对称：
- OrgJoinRequest: 非成员 → 申请加入
- OrgLeaveRequest: 已加入成员 → 申请退出

approve 时会软删 OrgMembership 并触发 on_member_removed hook；
reject 仅置状态、不动 membership；
cancelled 由申请者本人主动撤回。
"""

from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


# 状态机与 OrgJoinRequestStatus 完全对齐，保持双向流程的对称性
class OrgLeaveRequestStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    cancelled = "cancelled"


class OrgLeaveRequest(BaseModel):
    """成员申请退出某个组织的待审记录。

    Partial unique 索引 `uq_org_leave_request_pending` 限制：
      同一 user_id × org_id，未删除且 status='pending' 的记录只能有一条。
    """

    __tablename__ = "org_leave_requests"
    __table_args__ = (
        Index(
            "uq_org_leave_request_pending",
            "user_id", "org_id",
            unique=True,
            postgresql_where=text("status = 'pending' AND deleted_at IS NULL"),
        ),
    )

    # 申请退出的成员 user_id
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True,
    )
    # 要退出的组织 org_id
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True,
    )
    # 退出理由（可选）
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 状态
    status: Mapped[str] = mapped_column(
        String(16), default=OrgLeaveRequestStatus.pending, nullable=False, index=True,
    )
    # 审核人（approve/reject 时回填）
    reviewed_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    # 审核备注（拒绝原因等）
    review_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
