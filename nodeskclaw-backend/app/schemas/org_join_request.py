"""组织加入申请相关的 Pydantic Schema 定义。

与 invitation 类似分三类：
- JoinRequestCreate: 用户提交申请的入参
- JoinRequestReview: 审核者批准/拒绝的入参
- JoinRequestInfo: 列表/详情返回，含申请者人话身份信息
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class JoinRequestCreate(BaseModel):
    """用户提交加入申请入参。

    org_slug：组织 slug（已唯一），作为申请目标的"邀请码"使用，避免暴露 org UUID。
    reason：申请理由，可选，500 字以内。
    """

    org_slug: str = Field(..., min_length=1, max_length=128)
    reason: str | None = Field(default=None, max_length=500)


class JoinRequestReview(BaseModel):
    """审核者批准/拒绝入参。

    action：approve 通过；reject 拒绝。
    note：审核备注，可选，500 字以内（拒绝时常用于填写原因）。
    """

    action: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=500)


class JoinRequestInfo(BaseModel):
    """加入申请详情/列表返回结构。

    包含申请者的 name/email（批量注入，避免 N+1），以及目标组织的 name/slug，
    用于前端审核中心避免裸显 UUID。
    """

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

    # 批量注入字段（service 层填充），前端展示用
    requester_name: str | None = None
    requester_email: str | None = None
    org_name: str | None = None
    org_slug: str | None = None
