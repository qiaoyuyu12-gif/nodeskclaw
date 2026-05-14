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


class KnowledgeBaseResponse(PydanticBase):
    id: str
    org_id: str
    name: str
    ragflow_kb_id: str
    ragflow_endpoint: str
    source_type: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SkillCreate(PydanticBase):
    name: str
    type: str
    kb_id: str | None = None
    config: dict[str, Any] = {}

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in ("rag_query", "gene", "composite"):
            raise ValueError("type must be rag_query, gene, or composite")
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
