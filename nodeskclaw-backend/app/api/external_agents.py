"""外部专用 Agent 的 REST API 路由。

CRUD 操作需要 org admin 权限；
聊天端点（SSE）仅需普通登录用户。
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import async_session_factory, get_current_org, get_db, require_org_admin
from app.schemas.common import ApiResponse
from app.schemas.external_agent import (
    AttachmentItem,
    AttachmentItemWithUrl,
    ChatRequest,
    ChatSessionResponse,
    ExternalAgentCreate,
    ExternalAgentResponse,
    ExternalAgentUpdate,
    MessageResponse,
)
from app.services import external_agent_adapter, external_agent_service
from app.services import external_agent_chat_service
from app.services import storage_service

logger = logging.getLogger(__name__)

router = APIRouter()


async def _persist_messages(
    session_id: str,
    user_content: str,
    user_attachments: list[dict] | None,
    assistant_content: str,
) -> None:
    """SSE 流结束后异步持久化消息，使用独立 DB Session 避免与请求 Session 竞争。"""
    try:
        async with async_session_factory() as db:
            await external_agent_chat_service.save_messages(
                session_id=session_id,
                user_content=user_content,
                user_attachments=user_attachments,
                assistant_content=assistant_content,
                db=db,
            )
    except Exception as exc:
        logger.warning("Failed to persist chat messages for session %s: %s", session_id, exc)


def _to_response(agent) -> ExternalAgentResponse:
    """将 ORM 对象转换为响应体（capabilities 由 Schema validator 自动解析）。"""
    return ExternalAgentResponse.model_validate(agent)


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
    """验证外部 Agent 连接可达性，更新 is_reachable（需要 org admin）。

    NAP 协议额外调用 /meta，将 capabilities / description 同步回数据库。
    """
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

    # NAP 协议：连通后从 /meta 同步 capabilities 和 description
    if agent.protocol == "nap" and reachable:
        try:
            meta = await external_agent_adapter.fetch_meta(
                endpoint=agent.endpoint, api_key=api_key
            )
            if meta.get("capabilities"):
                agent.capabilities = json.dumps(meta["capabilities"], ensure_ascii=False)
            if meta.get("description"):
                agent.description = meta["description"]
        except Exception:
            logger.warning("NAP /meta fetch failed for agent %s, skipping meta sync", agent_id)

    await db.commit()
    return ApiResponse(data={"reachable": reachable, "agent_id": agent_id})


# ── Attachments ────────────────────────────────────────────────────────────────

MAX_ATTACHMENT_SIZE = 20 * 1024 * 1024  # 20MB


@router.post("/{agent_id}/attachments/upload", response_model=ApiResponse[dict])
async def upload_attachment(
    agent_id: str,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    auth=Depends(get_current_org),
):
    """上传聊天附件（图片或文件），返回 storage_key 和临时预签名 URL。

    URL 仅供本次发送使用，不会持久化到数据库。
    """
    _, org = auth
    await external_agent_service.get_external_agent(agent_id=agent_id, org_id=org.id, db=db)

    content = await file.read()
    if len(content) > MAX_ATTACHMENT_SIZE:
        raise HTTPException(status_code=413, detail="文件超过 20MB 限制")

    storage_key = await storage_service.upload_external_agent_file(
        file_content=content,
        filename=file.filename or "attachment",
        content_type=file.content_type or "application/octet-stream",
        org_id=org.id,
    )
    url = await storage_service.get_presigned_url(storage_key)

    return ApiResponse(data={
        "storage_key": storage_key,
        "name": file.filename,
        "size": len(content),
        "content_type": file.content_type,
        "url": url,
    })


# ── Sessions ────────────────────────────────────────────────────────────────────

@router.get("/{agent_id}/sessions", response_model=ApiResponse[list[ChatSessionResponse]])
async def list_sessions(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    auth=Depends(get_current_org),
):
    """列出当前用户在指定 Agent 下的所有会话，按最后更新时间倒序。"""
    user, org = auth
    await external_agent_service.get_external_agent(agent_id=agent_id, org_id=org.id, db=db)
    sessions = await external_agent_chat_service.list_sessions(
        agent_id=agent_id, user_id=str(user.id), db=db
    )
    return ApiResponse(data=[ChatSessionResponse.model_validate(s) for s in sessions])


@router.post("/{agent_id}/sessions", response_model=ApiResponse[ChatSessionResponse])
async def create_session(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    auth=Depends(get_current_org),
):
    """创建新聊天会话（title 为空，发送首条消息后自动填充）。"""
    user, org = auth
    await external_agent_service.get_external_agent(agent_id=agent_id, org_id=org.id, db=db)
    session = await external_agent_chat_service.create_session(
        agent_id=agent_id, org_id=org.id, user_id=str(user.id), db=db
    )
    return ApiResponse(data=ChatSessionResponse.model_validate(session))


@router.delete("/{agent_id}/sessions/{session_id}", response_model=ApiResponse[None])
async def delete_session(
    agent_id: str,
    session_id: str,
    db: AsyncSession = Depends(get_db),
    auth=Depends(get_current_org),
):
    """软删除指定会话（仅会话归属用户可操作）。"""
    user, _ = auth
    await external_agent_chat_service.delete_session(
        session_id=session_id, user_id=str(user.id), db=db
    )
    return ApiResponse(data=None)


# ── Messages ────────────────────────────────────────────────────────────────────

@router.get(
    "/{agent_id}/sessions/{session_id}/messages",
    response_model=ApiResponse[list[MessageResponse]],
)
async def list_messages(
    agent_id: str,
    session_id: str,
    db: AsyncSession = Depends(get_db),
    auth=Depends(get_current_org),
):
    """返回会话内全部消息，用户消息的附件实时注入预签名 URL。"""
    user, _ = auth
    chat_session = await external_agent_chat_service.get_session(
        session_id=session_id, user_id=str(user.id), db=db
    )
    if not chat_session:
        raise HTTPException(status_code=404, detail="会话不存在")

    messages = await external_agent_chat_service.get_messages(session_id=session_id, db=db)

    result: list[MessageResponse] = []
    for msg in messages:
        attachments_with_url: list[AttachmentItemWithUrl] | None = None
        if msg.attachments:
            attachments_with_url = []
            for att in msg.attachments:
                url = await storage_service.get_presigned_url(att["storage_key"])
                attachments_with_url.append(AttachmentItemWithUrl(**att, url=url))
        result.append(MessageResponse(
            id=msg.id,
            session_id=msg.session_id,
            role=msg.role,
            content=msg.content,
            attachments=attachments_with_url,
            created_at=msg.created_at,
        ))

    return ApiResponse(data=result)


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
      { "message": "用户消息", "session_id": "UUID", "attachments": [...] }

    SSE 事件格式：
      data: {"chunk": "文本片段"}\n\n
      data: {"done": true}\n\n
      data: {"error": "错误信息"}\n\n
    """
    user, org = auth
    body = await request.json()
    message: str = body.get("message", "")
    session_id: str = body.get("session_id", "")
    attachments: list[dict] | None = body.get("attachments")

    agent = await external_agent_service.get_external_agent(
        agent_id=agent_id, org_id=org.id, db=db
    )
    api_key = external_agent_service.get_decrypted_api_key(agent)

    # 构建发给外部 Agent 的用户消息内容（附件以 URL 引用追加）
    user_content = message
    if attachments:
        file_lines = [
            f"- {a['name']} ({a['content_type']}, {a['size'] // 1024}KB): {a['url']}"
            for a in attachments
        ]
        user_content += "\n\n附件:\n" + "\n".join(file_lines)

    # 从 DB 加载历史消息，构建完整 messages 列表
    history = await external_agent_chat_service.get_messages(session_id=session_id, db=db)
    messages_for_agent = [{"role": m.role, "content": m.content} for m in history]
    messages_for_agent.append({"role": "user", "content": user_content})

    # 仅保存 storage_key，不保存 URL（URL 有有效期）
    attachments_to_save: list[dict] | None = None
    if attachments:
        attachments_to_save = [
            {
                "name": a["name"],
                "size": a["size"],
                "content_type": a["content_type"],
                "storage_key": a["storage_key"],
            }
            for a in attachments
        ]

    collected_chunks: list[str] = []

    async def event_stream():
        try:
            async for chunk in external_agent_adapter.chat_stream(
                endpoint=agent.endpoint,
                api_key=api_key,
                protocol=agent.protocol,
                messages=messages_for_agent,
                session_id=session_id,
                user_id=str(user.id),
                organization_id=str(org.id),
            ):
                collected_chunks.append(chunk)
                yield f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            logger.warning("External agent chat error: %s %s", agent_id, exc)
            yield f"data: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"
        finally:
            yield f"data: {json.dumps({'done': True})}\n\n"
            assistant_content = "".join(collected_chunks)
            if session_id and message:
                asyncio.create_task(
                    _persist_messages(
                        session_id=session_id,
                        user_content=message,
                        user_attachments=attachments_to_save,
                        assistant_content=assistant_content,
                    )
                )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
