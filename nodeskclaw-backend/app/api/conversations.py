"""Conversation API — list conversations and get conversation messages."""

import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_org, get_db
from app.core.exceptions import NotFoundError
from app.models.base import not_deleted
from app.models.conversation import Conversation
from app.models.workspace import Workspace
from app.services import conversation_service, workspace_message_service as wm_msg_service
from app.services import workspace_member_service as wm_service

logger = logging.getLogger(__name__)
router = APIRouter()


def _ok(data=None, message: str = "success"):
    return {"code": 0, "message": message, "data": data}


def _org_id(org) -> str:
    return org.id if hasattr(org, "id") else org.get("org_id", "")


async def _check_workspace(workspace_id: str, org, db: AsyncSession) -> Workspace:
    result = await db.execute(
        select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.org_id == _org_id(org),
            not_deleted(Workspace),
        )
    )
    ws = result.scalar_one_or_none()
    if not ws:
        raise NotFoundError("办公室不存在", "errors.workspace.not_found")
    return ws


@router.get("/{workspace_id}/conversations")
async def list_conversations(
    workspace_id: str,
    member_id: str | None = Query(None, description="按成员 instance_id 过滤"),
    is_manual: bool | None = Query(None, description="None=全部, true=仅手动, false=仅拓扑"),
    org_ctx=Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    user, org = org_ctx
    await _check_workspace(workspace_id, org, db)
    await wm_service.check_workspace_member(workspace_id, user, db)
    # 工作空间群聊默认只显示拓扑驱动的会话（is_manual=False），
    # 私人会话（is_manual=True）只在 InstanceChat 中通过 member_id + is_manual=true 查询
    effective_is_manual = is_manual if is_manual is not None else (True if member_id else False)
    convs = await conversation_service.list_conversations(
        workspace_id, db, member_id=member_id, is_manual=effective_is_manual,
    )
    return _ok([_conv_dict(c) for c in convs])


@router.get("/{workspace_id}/conversations/{conv_id}/messages")
async def get_conversation_messages(
    workspace_id: str,
    conv_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    org_ctx=Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    user, org = org_ctx
    await _check_workspace(workspace_id, org, db)
    await wm_service.check_workspace_member(workspace_id, user, db)

    conv_q = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.workspace_id == workspace_id,
            not_deleted(Conversation),
        ).limit(1)
    )
    if not conv_q.scalar_one_or_none():
        raise NotFoundError("群聊不存在", "errors.conversation.not_found")

    messages = await wm_msg_service.get_recent_messages(
        db, workspace_id, limit=limit, conversation_id=conv_id,
    )
    return _ok([
        {
            "id": m.id,
            "sender_type": m.sender_type,
            "sender_id": m.sender_id,
            "sender_name": m.sender_name,
            "content": m.content,
            "message_type": m.message_type,
            "target_instance_id": m.target_instance_id,
            "depth": m.depth,
            "conversation_id": m.conversation_id,
            "attachments": m.attachments,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in messages
    ])


class _CreateConversationRequest(BaseModel):
    name: str
    member_node_ids: list[str]


def _conv_dict(c: Conversation) -> dict:
    return {
        "id": c.id,
        "workspace_id": c.workspace_id,
        "name": c.name,
        "is_blackboard_group": c.is_blackboard_group,
        "member_node_ids": c.member_node_ids,
        "last_message_at": c.last_message_at.isoformat() if c.last_message_at else None,
        "last_message_preview": c.last_message_preview,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


@router.post("/{workspace_id}/conversations")
async def create_conversation(
    workspace_id: str,
    body: _CreateConversationRequest,
    org_ctx=Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    user, org = org_ctx
    await _check_workspace(workspace_id, org, db)
    await wm_service.check_workspace_member(workspace_id, user, db)
    conv = await conversation_service.create_manual_conversation(
        db, workspace_id, body.name, body.member_node_ids,
    )
    return _ok(_conv_dict(conv))


@router.delete("/{workspace_id}/conversations/{conv_id}")
async def delete_conversation(
    workspace_id: str,
    conv_id: str,
    org_ctx=Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    user, org = org_ctx
    await _check_workspace(workspace_id, org, db)
    await wm_service.check_workspace_member(workspace_id, user, db)

    from datetime import datetime, timezone
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.workspace_id == workspace_id,
            not_deleted(Conversation),
        ).limit(1)
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise NotFoundError("群聊不存在", "errors.conversation.not_found")

    conv.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    return _ok()
