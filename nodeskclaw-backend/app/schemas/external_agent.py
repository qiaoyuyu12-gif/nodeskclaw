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
    protocol: Literal["openai_compatible", "custom"] = "openai_compatible"
    description: str | None = None
    capabilities: list[str] = []
    icon_emoji: str | None = None
    theme_color: str | None = None


class ExternalAgentUpdate(PydanticBase):
    name: str | None = None
    endpoint: str | None = None
    api_key: str | None = None
    protocol: Literal["openai_compatible", "custom"] | None = None
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

