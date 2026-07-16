"""Agent 侧知识库检索代理接口 —— 供 nodeskclaw_knowledge_search 工具调用。

仅接受 agent（实例 proxy_token）调用，instance_id 严格从 AuthActor 派生，
不接受调用方传参，避免跨实例越权查询他人绑定的知识库。
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.security import AuthActor, get_auth_actor, get_current_user_or_agent
from app.schemas.agent_knowledge import (
    BoundKnowledgeBaseInfo,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
)
from app.schemas.common import ApiResponse
from app.services import agent_knowledge_service

router = APIRouter()


def _require_agent_instance_id() -> str:
    actor: AuthActor | None = get_auth_actor()
    if actor is None or actor.actor_type != "agent":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": 40300,
                "message_key": "errors.agent_knowledge.agent_only",
                "message": "该接口仅供 AI 员工实例调用",
            },
        )
    return actor.actor_id


@router.get("/knowledge/bindings", response_model=ApiResponse[list[BoundKnowledgeBaseInfo]])
async def list_my_knowledge_bases(
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user_or_agent),
):
    instance_id = _require_agent_instance_id()
    kbs = await agent_knowledge_service.list_bound_knowledge_bases(instance_id, db)
    return ApiResponse(data=kbs)


@router.post("/knowledge/search", response_model=ApiResponse[KnowledgeSearchResponse])
async def search_my_knowledge_bases(
    body: KnowledgeSearchRequest,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user_or_agent),
):
    instance_id = _require_agent_instance_id()
    result = await agent_knowledge_service.search_bound_knowledge(
        instance_id=instance_id,
        query=body.query,
        top_k=body.top_k,
        kb_ids=body.kb_ids,
        db=db,
    )
    return ApiResponse(data=result)
