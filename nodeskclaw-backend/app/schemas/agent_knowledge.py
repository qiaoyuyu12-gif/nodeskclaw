"""Agent 侧知识库检索代理接口的请求/响应模型。"""

from pydantic import BaseModel as PydanticBase, Field


class KnowledgeSearchRequest(PydanticBase):
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(5, ge=1, le=20)
    kb_ids: list[str] | None = None


class KnowledgeSearchChunk(PydanticBase):
    kb_id: str
    kb_name: str
    content: str
    score: float | None = None
    document_name: str | None = None


class KnowledgeSearchKbError(PydanticBase):
    kb_id: str
    kb_name: str
    message: str


class KnowledgeSearchResponse(PydanticBase):
    results: list[KnowledgeSearchChunk]
    kb_count: int
    degraded: bool
    errors: list[KnowledgeSearchKbError]


class BoundKnowledgeBaseInfo(PydanticBase):
    kb_id: str
    kb_name: str
    source_type: str
