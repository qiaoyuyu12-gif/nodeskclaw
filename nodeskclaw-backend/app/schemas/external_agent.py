"""ExternalAgent 的 Pydantic 请求/响应 Schema。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel as PydanticBase, field_validator


class ExternalAgentCreate(PydanticBase):
    name: str
    endpoint: str
    api_key: str | None = None
    protocol: Literal["openai_compatible", "custom", "nap"] = "openai_compatible"
    description: str | None = None
    capabilities: list[str] = []
    icon_emoji: str | None = None
    theme_color: str | None = None


class ExternalAgentUpdate(PydanticBase):
    name: str | None = None
    endpoint: str | None = None
    api_key: str | None = None
    protocol: Literal["openai_compatible", "custom", "nap"] | None = None
    description: str | None = None
    capabilities: list[str] | None = None
    icon_emoji: str | None = None
    theme_color: str | None = None


class ExternalAgentResponse(PydanticBase):
    id: str
    org_id: str
    name: str
    description: str | None
    endpoint: str
    protocol: str
    capabilities: list[str]
    icon_emoji: str | None
    theme_color: str | None
    is_reachable: bool
    last_checked_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("capabilities", mode="before")
    @classmethod
    def parse_capabilities(cls, v: Any) -> list[str]:
        """数据库存 JSON 字符串，Pydantic 验证前自动解析为列表。"""
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                return parsed if isinstance(parsed, list) else []
            except (json.JSONDecodeError, ValueError):
                return []
        return v or []


# ── 附件 Schema ───────────────────────────────────────────────────────────────

class AttachmentItem(PydanticBase):
    """附件元数据（DB 存储格式，不含 URL）。"""

    name: str
    size: int
    content_type: str
    storage_key: str


class AttachmentItemWithUrl(AttachmentItem):
    """附件元数据 + 预签名 URL（仅用于 API 响应，不持久化）。"""

    url: str


# ── 会话 Schema ───────────────────────────────────────────────────────────────

class ChatSessionResponse(PydanticBase):
    id: str
    agent_id: str
    user_id: str
    org_id: str
    title: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── 消息 Schema ───────────────────────────────────────────────────────────────

class MessageResponse(PydanticBase):
    id: str
    session_id: str
    role: str
    content: str
    thinking: str | None = None
    attachments: list[AttachmentItemWithUrl] | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── 聊天请求 Schema ────────────────────────────────────────────────────────────

class ChatRequest(PydanticBase):
    """新版聊天请求（后端从 DB 加载历史，前端只发当前消息）。"""

    message: str
    session_id: str
    attachments: list[AttachmentItem] | None = None

