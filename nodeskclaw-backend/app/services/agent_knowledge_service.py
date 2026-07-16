"""Agent 侧知识库检索代理：在对话中实时查询实例已绑定的知识库并转发到 RAGFlow。"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.models.instance_knowledge_base import InstanceKnowledgeBase
from app.schemas.agent_knowledge import (
    BoundKnowledgeBaseInfo,
    KnowledgeSearchChunk,
    KnowledgeSearchKbError,
    KnowledgeSearchResponse,
)
from app.services import instance_kb_service, kb_service, ragflow_adapter

logger = logging.getLogger(__name__)


async def _enabled_bindings(
    instance_id: str, kb_ids: list[str] | None, db: AsyncSession,
) -> list[InstanceKnowledgeBase]:
    bindings = await instance_kb_service.list_instance_kbs(instance_id=instance_id, db=db)
    bindings = [b for b in bindings if b.enabled]
    if kb_ids:
        wanted = set(kb_ids)
        bindings = [b for b in bindings if b.kb_id in wanted]
    return bindings


async def list_bound_knowledge_bases(
    instance_id: str, db: AsyncSession,
) -> list[BoundKnowledgeBaseInfo]:
    bindings = await _enabled_bindings(instance_id, None, db)
    return [
        BoundKnowledgeBaseInfo(kb_id=b.kb.id, kb_name=b.kb.name, source_type=b.kb.source_type)
        for b in bindings
    ]


async def search_bound_knowledge(
    instance_id: str,
    query: str,
    top_k: int,
    kb_ids: list[str] | None,
    db: AsyncSession,
) -> KnowledgeSearchResponse:
    bindings = await _enabled_bindings(instance_id, kb_ids, db)
    if not bindings:
        return KnowledgeSearchResponse(results=[], kb_count=0, degraded=False, errors=[])

    results: list[KnowledgeSearchChunk] = []
    errors: list[KnowledgeSearchKbError] = []

    for binding in bindings:
        kb = binding.kb
        try:
            api_key = kb_service.get_decrypted_api_key(kb)
            chunks = await ragflow_adapter.retrieve(
                kb.ragflow_endpoint, api_key, kb.ragflow_kb_id, query, top_k=top_k,
            )
        except AppException as exc:
            errors.append(KnowledgeSearchKbError(kb_id=kb.id, kb_name=kb.name, message=exc.message))
            continue
        except Exception as exc:  # noqa: BLE001 - 解密失败等未预期异常也不能拖垮整个请求
            logger.warning("knowledge search unexpected error kb=%s: %s", kb.id, exc)
            errors.append(
                KnowledgeSearchKbError(kb_id=kb.id, kb_name=kb.name, message="检索时发生未知错误"),
            )
            continue

        for chunk in chunks:
            results.append(KnowledgeSearchChunk(
                kb_id=kb.id,
                kb_name=kb.name,
                content=chunk.get("content", ""),
                score=chunk.get("similarity"),
                document_name=chunk.get("document_keyword"),
            ))

    results.sort(key=lambda r: r.score or 0.0, reverse=True)
    results = results[:top_k]

    return KnowledgeSearchResponse(
        results=results, kb_count=len(bindings), degraded=bool(errors), errors=errors,
    )
