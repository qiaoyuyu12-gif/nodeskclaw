"""组织退出申请 Pydantic Schema。

与 JoinRequest schemas 对称：
- LeaveRequestCreate：成员发起退出（不需要 org_id，自动用 current_org_id 或 path param）
- LeaveRequestReview：管理员审核入参
- LeaveRequestInfo：列表/详情返回结构
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LeaveRequestCreate(BaseModel):
    """成员发起退出申请入参。

    org_id：要退出的组织 ID（必填，避免依赖 current_org_id 隐式上下文，多组织场景更清晰）。
    reason：退出理由，可选。
    """

    org_id: str = Field(..., min_length=1, max_length=36)
    reason: str | None = Field(default=None, max_length=500)


class LeaveRequestReview(BaseModel):
    """审核者批准/拒绝入参。"""

    action: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=500)


class LeaveRequestInfo(BaseModel):
    """退出申请详情/列表返回结构。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    org_id: str
    reason: str | None = None
    status: str
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None
    created_at: datetime

    # 批量注入字段：申请者人话身份 + 目标组织信息（避免裸显 UUID）
    requester_name: str | None = None
    requester_email: str | None = None
    requester_role: str | None = None
    org_name: str | None = None
    org_slug: str | None = None
