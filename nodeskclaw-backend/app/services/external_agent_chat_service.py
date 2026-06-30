"""外部 Agent 聊天会话与消息的 CRUD 服务层。"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import not_deleted
from app.models.external_agent_chat import ExternalAgentChatSession, ExternalAgentMessage


async def create_session(
    *, agent_id: str, org_id: str, user_id: str, db: AsyncSession
) -> ExternalAgentChatSession:
    """创建空会话，title 待首条消息写入后自动填充。"""
    session = ExternalAgentChatSession(agent_id=agent_id, org_id=org_id, user_id=user_id)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def list_sessions(
    *, agent_id: str, user_id: str, db: AsyncSession
) -> list[ExternalAgentChatSession]:
    """列出用户在指定 Agent 下的所有会话，按 updated_at 倒序。"""
    result = await db.execute(
        select(ExternalAgentChatSession)
        .where(
            ExternalAgentChatSession.agent_id == agent_id,
            ExternalAgentChatSession.user_id == user_id,
            not_deleted(ExternalAgentChatSession),
        )
        .order_by(ExternalAgentChatSession.updated_at.desc())
    )
    return list(result.scalars().all())


async def get_session(
    *, session_id: str, user_id: str, db: AsyncSession
) -> ExternalAgentChatSession | None:
    """按 id 查询会话，同时校验归属用户。"""
    result = await db.execute(
        select(ExternalAgentChatSession).where(
            ExternalAgentChatSession.id == session_id,
            ExternalAgentChatSession.user_id == user_id,
            not_deleted(ExternalAgentChatSession),
        )
    )
    return result.scalar_one_or_none()


async def delete_session(
    *, session_id: str, user_id: str, db: AsyncSession
) -> None:
    """软删除会话（设置 deleted_at）。"""
    session = await get_session(session_id=session_id, user_id=user_id, db=db)
    if session:
        session.deleted_at = datetime.now(timezone.utc)
        await db.commit()


async def get_messages(
    *, session_id: str, db: AsyncSession
) -> list[ExternalAgentMessage]:
    """按时间升序返回会话内全部消息。"""
    result = await db.execute(
        select(ExternalAgentMessage)
        .where(ExternalAgentMessage.session_id == session_id)
        .order_by(ExternalAgentMessage.created_at.asc())
    )
    return list(result.scalars().all())


async def save_messages(
    *,
    session_id: str,
    user_content: str,
    user_attachments: list[dict] | None,
    assistant_content: str,
    assistant_thinking: str | None = None,
    db: AsyncSession,
) -> None:
    """批量写入用户消息和 Agent 响应，同时更新 session 的 updated_at 和 title。"""
    db.add(ExternalAgentMessage(
        session_id=session_id,
        role="user",
        content=user_content,
        attachments=user_attachments or None,
    ))
    db.add(ExternalAgentMessage(
        session_id=session_id,
        role="assistant",
        content=assistant_content,
        thinking=assistant_thinking or None,
    ))

    result = await db.execute(
        select(ExternalAgentChatSession).where(ExternalAgentChatSession.id == session_id)
    )
    chat_session = result.scalar_one_or_none()
    if chat_session:
        chat_session.updated_at = datetime.now(timezone.utc)
        if not chat_session.title and user_content:
            chat_session.title = user_content[:50]

    await db.commit()
