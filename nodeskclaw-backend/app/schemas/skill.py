from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel as PydanticBase, field_validator


class KnowledgeBaseCreate(PydanticBase):
    name: str
    ragflow_endpoint: str
    ragflow_kb_id: str
    api_key: str
    source_type: str = "doc"

    @field_validator("source_type")
    @classmethod
    def validate_source_type(cls, v: str) -> str:
        if v not in ("doc", "system", "mixed"):
            raise ValueError("source_type must be doc, system, or mixed")
        return v


class KnowledgeBaseUpdate(PydanticBase):
    name: str | None = None
    ragflow_endpoint: str | None = None
    ragflow_kb_id: str | None = None
    api_key: str | None = None
    source_type: str | None = None

    @field_validator("source_type")
    @classmethod
    def validate_source_type(cls, v: str | None) -> str | None:
        if v is not None and v not in ("doc", "system", "mixed"):
            raise ValueError("source_type must be doc, system, or mixed")
        return v


class KnowledgeBaseResponse(PydanticBase):
    id: str
    org_id: str
    name: str
    ragflow_kb_id: str
    ragflow_endpoint: str
    source_type: str
    is_reachable: bool
    last_checked_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InstanceKnowledgeBaseResponse(PydanticBase):
    """AI 员工与知识库绑定的响应体，含嵌套知识库详情。"""

    id: str
    instance_id: str
    kb_id: str
    enabled: bool
    kb: KnowledgeBaseResponse
    created_at: datetime

    model_config = {"from_attributes": True}


class SkillCreate(PydanticBase):
    name: str
    type: str
    kb_id: str | None = None
    config: dict[str, Any] = {}

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in ("rag_query", "gene", "composite", "tool", "prompt"):
            raise ValueError("type must be rag_query, gene, composite, tool, or prompt")
        return v


class SkillUpdate(PydanticBase):
    name: str | None = None
    kb_id: str | None = None
    config: dict[str, Any] | None = None
    enabled: bool | None = None


class SkillResponse(PydanticBase):
    id: str
    org_id: str
    name: str
    type: str
    kb_id: str | None
    config: dict[str, Any]
    enabled: bool
    description: str | None
    package_path: str | None
    # manifest：文件夹上传后内联序列化的 JSON，agent 命中时读取
    manifest: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}


class BindRequest(PydanticBase):
    instance_id: str


class QueryRequest(PydanticBase):
    question: str


class QueryResponse(PydanticBase):
    degraded: bool = False
    message: str | None = None
    results: list[dict[str, Any]] = []
