"""外部专用 Agent 的 REST API 路由。

CRUD 操作需要 org admin 权限；
聊天端点（SSE）仅需普通登录用户。
"""

import json
import logging
from datetime import datetime, timezone

from fastapi import Depends, Request
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_org, get_db, require_org_admin
from app.schemas.common import ApiResponse
from app.schemas.external_agent import (
    ExternalAgentCreate,
    ExternalAgentResponse,
    ExternalAgentUpdate,
)
from app.services import external_agent_adapter, external_agent_service

logger = logging.getLogger(__name__)

router = APIRouter()


def _to_response(agent) -> ExternalAgentResponse:
    """将 ORM 对象转换为响应体，同时解析 capabilities JSON。"""
    resp = ExternalAgentResponse.model_validate(agent)
    resp.capabilities = external_agent_service.get_capabilities(agent)
    return resp


# ── CRUD ─────────────────────────────────────────────────────────────────────

@router.post("", response_model=ApiResponse[ExternalAgentResponse])
async def create_agent(
    body: ExternalAgentCreate,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_org_admin),
):
    """创建外部 Agent 连接配置（需要 org admin）。"""
    _, org = auth
    agent = await external_agent_service.create_external_agent(
        org_id=org.id,
        name=body.name,
        endpoint=body.endpoint,
        protocol=body.protocol,
        api_key=body.api_key,
        description=body.description,
        capabilities=body.capabilities,
        icon_emoji=body.icon_emoji,
        theme_color=body.theme_color,
        db=db,
    )
    return ApiResponse(data=_to_response(agent))


@router.get("", response_model=ApiResponse[list[ExternalAgentResponse]])
async def list_agents(
    db: AsyncSession = Depends(get_db),
    auth=Depends(get_current_org),
):
    """列出组织内所有外部 Agent（所有登录成员可见）。"""
    _, org = auth
    agents = await external_agent_service.list_external_agents(org_id=org.id, db=db)
    return ApiResponse(data=[_to_response(a) for a in agents])


@router.patch("/{agent_id}", response_model=ApiResponse[ExternalAgentResponse])
async def update_agent(
    agent_id: str,
    body: ExternalAgentUpdate,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_org_admin),
):
    """更新外部 Agent 配置（需要 org admin）。"""
    _, org = auth
    updates = body.model_dump(exclude_none=True)
    agent = await external_agent_service.update_external_agent(
        agent_id=agent_id, org_id=org.id, updates=updates, db=db
    )
    return ApiResponse(data=_to_response(agent))


@router.delete("/{agent_id}", response_model=ApiResponse[None])
async def delete_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_org_admin),
):
    """软删除外部 Agent（需要 org admin）。"""
    _, org = auth
    await external_agent_service.delete_external_agent(
        agent_id=agent_id, org_id=org.id, db=db
    )
    return ApiResponse(data=None)


# ── Sync（连接验证）────────────────────────────────────────────────────────────

@router.post("/{agent_id}/sync", response_model=ApiResponse[dict])
async def sync_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_org_admin),
):
    """验证外部 Agent 连接可达性，更新 is_reachable（需要 org admin）。"""
    _, org = auth
    agent = await external_agent_service.get_external_agent(
        agent_id=agent_id, org_id=org.id, db=db
    )
    api_key = external_agent_service.get_decrypted_api_key(agent)
    reachable = await external_agent_adapter.verify_connection(
        endpoint=agent.endpoint,
        api_key=api_key,
        protocol=agent.protocol,
    )
    agent.is_reachable = reachable
    agent.last_checked_at = datetime.now(timezone.utc)
    await db.commit()
    return ApiResponse(data={"reachable": reachable, "agent_id": agent_id})


# ── Chat（SSE 代理）───────────────────────────────────────────────────────────

@router.post("/{agent_id}/chat")
async def chat_with_agent(
    agent_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth=Depends(get_current_org),
):
    """向外部 Agent 发起聊天，通过 SSE 流式返回响应（所有登录用户可用）。

    请求体：
      { "messages": [{"role": "user"|"assistant", "content": "..."}] }

    SSE 事件格式：
      data: {"chunk": "文本片段"}\n\n
      data: {"done": true}\n\n
      data: {"error": "错误信息"}\n\n
    """
    _, org = auth
    body = await request.json()
    messages: list[dict] = body.get("messages", [])

    agent = await external_agent_service.get_external_agent(
        agent_id=agent_id, org_id=org.id, db=db
    )
    api_key = external_agent_service.get_decrypted_api_key(agent)

    async def event_stream():
        try:
            async for chunk in external_agent_adapter.chat_stream(
                endpoint=agent.endpoint,
                api_key=api_key,
                protocol=agent.protocol,
                messages=messages,
            ):
                yield f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            logger.warning("External agent chat error: %s %s", agent_id, exc)
            yield f"data: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"
        finally:
            yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲，确保实时推送
        },
    )
