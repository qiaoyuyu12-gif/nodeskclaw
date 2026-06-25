# 外部 Agent 聊天记录持久化 + 附件上传 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为外部 Agent 聊天新增多会话持久化存储和附件上传功能，用户刷新页面后历史记录不丢失，聊天时可上传图片/文件并将预签名 URL 传递给外部 Agent。

**Architecture:** 新建两张表（ExternalAgentChatSession + ExternalAgentMessage）；后端 SSE 流结束后异步落库；附件上传复用现有 storage_service，仅存 storage_key，读取时实时生成 presigned URL；前端 ExternalAgentChat.vue 改造为左侧会话列表 + 右侧聊天区布局。

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy async / Alembic / Vue 3 Composition API / TypeScript / Tailwind CSS / lucide-vue-next

---

## 文件变更清单

| 操作 | 文件 |
|------|------|
| 修改 | `nodeskclaw-backend/app/services/storage_service.py` |
| 新建 | `nodeskclaw-backend/app/models/external_agent_chat.py` |
| 修改 | `nodeskclaw-backend/app/models/__init__.py` |
| 新建 | `nodeskclaw-backend/alembic/versions/<hash>_add_external_agent_chat.py` |
| 修改 | `nodeskclaw-backend/app/schemas/external_agent.py` |
| 新建 | `nodeskclaw-backend/app/services/external_agent_chat_service.py` |
| 修改 | `nodeskclaw-backend/app/api/external_agents.py` |
| 修改 | `nodeskclaw-portal/src/services/externalAgents.ts` |
| 修改 | `nodeskclaw-portal/src/views/external-agents/ExternalAgentChat.vue` |

---

## Task 1: storage_service 添加外部 Agent 文件上传函数

**Files:**
- Modify: `nodeskclaw-backend/app/services/storage_service.py`

现有 `upload_file` 函数将路径硬编码为 `workspace-files/{workspace_id}/...`，外部 Agent 需要独立路径前缀 `external-agent-files/{org_id}/...`。

- [ ] **Step 1: 在 storage_service.py 末尾追加以下代码**

在文件末尾（`delete_raw` 函数之后）追加：

```python
# ── External Agent Attachments ────────────────────────────

def _s3_upload_ea(file_content: bytes, filename: str, content_type: str, org_id: str) -> str:
    """上传外部 Agent 附件到 S3，返回含 prefix 的完整 storage key。"""
    client = _get_s3_client()
    prefix = settings.S3_KEY_PREFIX.strip("/")
    base = f"external-agent-files/{org_id}/{uuid.uuid4().hex}/{filename}"
    key = f"{prefix}/{base}" if prefix else base
    client.put_object(
        Bucket=settings.S3_BUCKET,
        Key=key,
        Body=file_content,
        ContentType=content_type,
    )
    return key


def _local_upload_ea(file_content: bytes, filename: str, _content_type: str, org_id: str) -> str:
    """上传外部 Agent 附件到本地文件系统，返回相对路径 key。"""
    base = f"external-agent-files/{org_id}/{uuid.uuid4().hex}/{filename}"
    local_dir = _get_local_dir()
    file_path = local_dir / base
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(file_content)
    return base


async def upload_external_agent_file(
    file_content: bytes, filename: str, content_type: str, org_id: str
) -> str:
    """上传外部 Agent 附件，返回 storage key（可直接传入 get_presigned_url）。"""
    if _use_s3():
        return await asyncio.to_thread(_s3_upload_ea, file_content, filename, content_type, org_id)
    return await asyncio.to_thread(_local_upload_ea, file_content, filename, content_type, org_id)
```

- [ ] **Step 2: 提交**

```bash
cd nodeskclaw-backend
git add app/services/storage_service.py
git commit -m "feat(storage): 添加外部 Agent 附件上传函数"
```

---

## Task 2: 创建 DB Model

**Files:**
- Create: `nodeskclaw-backend/app/models/external_agent_chat.py`

- [ ] **Step 1: 创建文件**

```python
"""外部 Agent 聊天会话与消息模型。"""

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class ExternalAgentChatSession(BaseModel):
    """外部 Agent 聊天会话（用户与单个 Agent 可开多个独立对话）。"""

    __tablename__ = "external_agent_chat_sessions"

    org_id: Mapped[str] = mapped_column(String(36), nullable=False)
    agent_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("external_agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)


class ExternalAgentMessage(BaseModel):
    """外部 Agent 聊天消息（user / assistant 两种角色）。

    attachments 仅存 storage_key，不存 URL（URL 按需生成以防失效）。
    跟随 session 级联删除，自身不做软删除。
    """

    __tablename__ = "external_agent_messages"

    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("external_agent_chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    attachments: Mapped[list | None] = mapped_column(JSONB, nullable=True)
```

- [ ] **Step 2: 在 `app/models/__init__.py` 末尾添加导入**

在 `from app.models.external_agent import ExternalAgent` 行之后添加：

```python
from app.models.external_agent_chat import ExternalAgentChatSession, ExternalAgentMessage  # noqa: F401
```

- [ ] **Step 3: 提交**

```bash
git add app/models/external_agent_chat.py app/models/__init__.py
git commit -m "feat(models): 新增 ExternalAgentChatSession + ExternalAgentMessage 模型"
```

---

## Task 3: 生成并执行 Alembic Migration

**Files:**
- Create: `nodeskclaw-backend/alembic/versions/<hash>_add_external_agent_chat.py` (自动生成)

- [ ] **Step 1: 生成 migration**

```bash
cd nodeskclaw-backend
uv run alembic revision --autogenerate -m "add_external_agent_chat_sessions_and_messages"
```

期望输出：`Generating .../alembic/versions/<hash>_add_external_agent_chat_sessions_and_messages.py ... done`

- [ ] **Step 2: 检查生成的文件**

打开生成的 migration 文件，确认 `upgrade()` 中包含：
- `op.create_table('external_agent_chat_sessions', ...)` - 含 id, org_id, agent_id, user_id, title, created_at, updated_at, deleted_at 字段
- `op.create_table('external_agent_messages', ...)` - 含 id, session_id, role, content, attachments, created_at, updated_at, deleted_at 字段
- 两张表的 FK 约束和索引

如果 upgrade() 为空，说明模型未被 alembic 检测到，检查 `__init__.py` 的导入是否正确。

- [ ] **Step 3: 执行 migration**

```bash
uv run alembic upgrade head
```

期望输出：`Running upgrade <prev_rev> -> <new_rev>, add_external_agent_chat_sessions_and_messages`

- [ ] **Step 4: 提交**

```bash
git add alembic/versions/
git commit -m "feat(db): 迁移添加外部 Agent 聊天会话和消息表"
```

---

## Task 4: 扩展 Pydantic Schema

**Files:**
- Modify: `nodeskclaw-backend/app/schemas/external_agent.py`

- [ ] **Step 1: 在文件末尾追加以下内容**

在现有 `ExternalAgentResponse` 类之后追加：

```python
# ── 附件 Schema ───────────────────────────────────────────────────────────────

class AttachmentItem(PydanticBase):
    """附件元数据（DB 存储格式，不含 URL）。"""

    name: str
    size: int
    content_type: str
    storage_key: str


class AttachmentItemWithUrl(AttachmentItem):
    """附件元数据 + 预签名 URL（仅用于 API 响应，不持久化）。"""

    url: str


# ── 会话 Schema ───────────────────────────────────────────────────────────────

class ChatSessionResponse(PydanticBase):
    id: str
    agent_id: str
    user_id: str
    org_id: str
    title: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── 消息 Schema ───────────────────────────────────────────────────────────────

class MessageResponse(PydanticBase):
    id: str
    session_id: str
    role: str
    content: str
    attachments: list[AttachmentItemWithUrl] | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── 聊天请求 Schema ────────────────────────────────────────────────────────────

class ChatRequest(PydanticBase):
    """新版聊天请求（后端从 DB 加载历史，前端只发当前消息）。"""

    message: str
    session_id: str
    attachments: list[AttachmentItem] | None = None
```

- [ ] **Step 2: 在文件顶部 `from __future__ import annotations` 之后添加 datetime 导入**

确认文件顶部已有：
```python
from datetime import datetime
```

如果没有，在 `from __future__ import annotations` 行之后添加这行。

- [ ] **Step 3: 提交**

```bash
git add app/schemas/external_agent.py
git commit -m "feat(schemas): 添加外部 Agent 聊天会话、消息、附件 Schema"
```

---

## Task 5: 创建 external_agent_chat_service

**Files:**
- Create: `nodeskclaw-backend/app/services/external_agent_chat_service.py`

- [ ] **Step 1: 创建文件**

```python
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
```

- [ ] **Step 2: 提交**

```bash
git add app/services/external_agent_chat_service.py
git commit -m "feat(services): 添加外部 Agent 聊天会话与消息 CRUD 服务"
```

---

## Task 6: 新增 API 路由（附件上传 + 会话管理 + 消息历史）

**Files:**
- Modify: `nodeskclaw-backend/app/api/external_agents.py`

- [ ] **Step 1: 在文件顶部更新 import 区**

将现有 import 区替换为：

```python
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
```

- [ ] **Step 2: 在文件末尾（chat 端点之前）添加附件上传路由**

在 `# ── Chat（SSE 代理）` 注释之前添加：

```python
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
    # 验证 agent 属于该 org（顺带检查是否存在）
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
```

- [ ] **Step 3: 提交**

```bash
git add app/api/external_agents.py
git commit -m "feat(api): 新增外部 Agent 附件上传、会话管理、消息历史接口"
```

---

## Task 7: 改造 Chat 路由（新请求格式 + 异步落库）

**Files:**
- Modify: `nodeskclaw-backend/app/api/external_agents.py`

- [ ] **Step 1: 在文件中添加 `_persist_messages` 辅助函数**

在 `router = APIRouter()` 行之后、`_to_response` 函数之前添加：

```python
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
```

- [ ] **Step 2: 将 `chat_with_agent` 端点替换为新版本**

将现有 `@router.post("/{agent_id}/chat")` 端点完整替换：

```python
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
```

- [ ] **Step 3: 启动后端，验证新端点正常注册**

```bash
cd nodeskclaw-backend
uv run uvicorn app.main:app --reload --port 4510
```

访问 `http://localhost:4510/docs`，确认以下路由出现：
- `POST /api/v1/external-agents/{agent_id}/attachments/upload`
- `GET /api/v1/external-agents/{agent_id}/sessions`
- `POST /api/v1/external-agents/{agent_id}/sessions`
- `DELETE /api/v1/external-agents/{agent_id}/sessions/{session_id}`
- `GET /api/v1/external-agents/{agent_id}/sessions/{session_id}/messages`
- `POST /api/v1/external-agents/{agent_id}/chat` (已有，参数变化)

- [ ] **Step 4: 提交**

```bash
git add app/api/external_agents.py
git commit -m "feat(api): 改造聊天接口支持新请求格式和异步消息持久化"
```

---

## Task 8: 扩展前端服务层

**Files:**
- Modify: `nodeskclaw-portal/src/services/externalAgents.ts`

- [ ] **Step 1: 将文件完整替换为以下内容**

先读取现有文件内容，然后在现有 `externalAgentApi` 对象中添加新方法，并在文件顶部添加类型定义：

在文件顶部（所有现有代码之前）添加类型定义：

```typescript
export interface AttachmentItem {
  name: string
  size: number
  content_type: string
  storage_key: string
}

export interface AttachmentItemWithUrl extends AttachmentItem {
  url: string
}

export interface AttachmentUploadResponse {
  storage_key: string
  name: string
  size: number
  content_type: string
  url: string
}

export interface ChatSession {
  id: string
  agent_id: string
  user_id: string
  org_id: string
  title: string | null
  created_at: string
  updated_at: string
}

export interface ChatMessage {
  id: string
  session_id: string
  role: 'user' | 'assistant'
  content: string
  attachments: AttachmentItemWithUrl[] | null
  created_at: string
}
```

将现有 `chatStream` 方法签名从：
```typescript
chatStream(id: string, messages: any[], sessionId?: string)
```
改为：
```typescript
async chatStream(
  agentId: string,
  message: string,
  sessionId: string,
  attachments?: AttachmentItem[]
): Promise<Response>
```

请求体改为：
```typescript
body: JSON.stringify({
  message,
  session_id: sessionId,
  attachments: attachments ?? [],
})
```

将现有 `chatStream` 方法**完整替换**为以下新版（签名从 `messages: any[]` 改为 `message: string + sessionId + attachments`）：

```typescript
async chatStream(
  agentId: string,
  message: string,
  sessionId: string,
  attachments?: AttachmentItemWithUrl[]  // 含 url 字段，后端用于拼接给外部 Agent 的消息
): Promise<Response> {
  const token = localStorage.getItem('portal_token')
  return fetch(`/api/v1/external-agents/${agentId}/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      message,
      session_id: sessionId,
      attachments: attachments ?? [],
    }),
  })
},
```

在 `externalAgentApi` 对象中追加以下方法（在 `chatStream` 之后）：

```typescript
async uploadAttachment(agentId: string, file: File): Promise<AttachmentUploadResponse> {
  const token = localStorage.getItem('portal_token')
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`/api/v1/external-agents/${agentId}/attachments/upload`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  })
  if (!res.ok) throw new Error(`上传失败: ${res.status}`)
  const json = await res.json()
  return json.data as AttachmentUploadResponse
},

async listSessions(agentId: string): Promise<ChatSession[]> {
  const token = localStorage.getItem('portal_token')
  const res = await fetch(`/api/v1/external-agents/${agentId}/sessions`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error(`加载会话列表失败: ${res.status}`)
  const json = await res.json()
  return json.data as ChatSession[]
},

async createSession(agentId: string): Promise<ChatSession> {
  const token = localStorage.getItem('portal_token')
  const res = await fetch(`/api/v1/external-agents/${agentId}/sessions`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error(`创建会话失败: ${res.status}`)
  const json = await res.json()
  return json.data as ChatSession
},

async deleteSession(agentId: string, sessionId: string): Promise<void> {
  const token = localStorage.getItem('portal_token')
  await fetch(`/api/v1/external-agents/${agentId}/sessions/${sessionId}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token}` },
  })
},

async getMessages(agentId: string, sessionId: string): Promise<ChatMessage[]> {
  const token = localStorage.getItem('portal_token')
  const res = await fetch(
    `/api/v1/external-agents/${agentId}/sessions/${sessionId}/messages`,
    { headers: { Authorization: `Bearer ${token}` } }
  )
  if (!res.ok) throw new Error(`加载消息历史失败: ${res.status}`)
  const json = await res.json()
  return json.data as ChatMessage[]
},
```

- [ ] **Step 2: 提交**

```bash
cd nodeskclaw-portal
git add src/services/externalAgents.ts
git commit -m "feat(portal): 扩展外部 Agent 服务层（会话管理、消息历史、附件上传）"
```

---

## Task 9: 改造 ExternalAgentChat.vue（完整重写）

**Files:**
- Modify: `nodeskclaw-portal/src/views/external-agents/ExternalAgentChat.vue`

本 task 将组件完整重写为三栏布局（左侧会话列表 + 右侧聊天区）。

- [ ] **Step 1: 用以下内容完整替换 ExternalAgentChat.vue**

```vue
<script setup lang="ts">
import { ref, computed, nextTick, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import {
  ChevronLeft,
  Plus,
  Trash2,
  Paperclip,
  X,
  Send,
  FileText,
} from 'lucide-vue-next'
import { externalAgentApi } from '@/services/externalAgents'
import type {
  AttachmentItem,
  AttachmentItemWithUrl,
  AttachmentUploadResponse,
  ChatMessage,
  ChatSession,
} from '@/services/externalAgents'
import { useExternalAgentStore } from '@/stores/externalAgents'

// ── 路由 ─────────────────────────────────────────────────────────────────────
const route = useRoute()
const agentId = route.params.id as string

// ── Store ────────────────────────────────────────────────────────────────────
const agentStore = useExternalAgentStore()

const agent = computed(() => agentStore.agents.find((a) => a.id === agentId) ?? null)

// ── 会话状态 ──────────────────────────────────────────────────────────────────
const sessions = ref<ChatSession[]>([])
const currentSessionId = ref<string | null>(null)
const sessionsLoading = ref(false)

// ── 消息状态 ──────────────────────────────────────────────────────────────────
interface LocalMessage {
  id?: string
  role: 'user' | 'assistant'
  content: string
  attachments?: AttachmentItemWithUrl[]
  streaming?: boolean
}

const messages = ref<LocalMessage[]>([])
const messagesLoading = ref(false)
const isStreaming = ref(false)
const inputText = ref('')
const messagesEndRef = ref<HTMLElement | null>(null)

// ── 附件状态 ──────────────────────────────────────────────────────────────────
interface PendingAttachment extends AttachmentUploadResponse {
  previewUrl?: string  // 图片预览用的本地 ObjectURL
}

const pendingAttachments = ref<PendingAttachment[]>([])
const isUploading = ref(false)
const fileInputRef = ref<HTMLInputElement | null>(null)

// ── 初始化 ────────────────────────────────────────────────────────────────────
onMounted(async () => {
  if (!agentStore.agents.length) {
    await agentStore.fetchAgents()
  }
  await loadSessions()
})

// ── 会话操作 ──────────────────────────────────────────────────────────────────
async function loadSessions() {
  sessionsLoading.value = true
  try {
    sessions.value = await externalAgentApi.listSessions(agentId)
    if (sessions.value.length > 0) {
      await switchSession(sessions.value[0].id)
    }
  } catch (e) {
    console.error('加载会话列表失败', e)
  } finally {
    sessionsLoading.value = false
  }
}

async function newSession() {
  const session = await externalAgentApi.createSession(agentId)
  sessions.value.unshift(session)
  await switchSession(session.id)
}

async function switchSession(sessionId: string) {
  if (currentSessionId.value === sessionId) return
  currentSessionId.value = sessionId
  messages.value = []
  messagesLoading.value = true
  try {
    const history = await externalAgentApi.getMessages(agentId, sessionId)
    messages.value = history.map((m: ChatMessage) => ({
      id: m.id,
      role: m.role,
      content: m.content,
      attachments: m.attachments ?? undefined,
    }))
    await scrollToBottom()
  } catch (e) {
    console.error('加载消息历史失败', e)
  } finally {
    messagesLoading.value = false
  }
}

async function deleteSession(sessionId: string, e: Event) {
  e.stopPropagation()
  await externalAgentApi.deleteSession(agentId, sessionId)
  sessions.value = sessions.value.filter((s) => s.id !== sessionId)
  if (currentSessionId.value === sessionId) {
    messages.value = []
    currentSessionId.value = null
    if (sessions.value.length > 0) {
      await switchSession(sessions.value[0].id)
    }
  }
}

// ── 附件操作 ──────────────────────────────────────────────────────────────────
function openFilePicker() {
  fileInputRef.value?.click()
}

async function handleFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = ''
  if (!files.length || !currentSessionId.value) return

  isUploading.value = true
  for (const file of files) {
    try {
      const result = await externalAgentApi.uploadAttachment(agentId, file)
      const pending: PendingAttachment = { ...result }
      if (file.type.startsWith('image/')) {
        pending.previewUrl = URL.createObjectURL(file)
      }
      pendingAttachments.value.push(pending)
    } catch (err) {
      console.error('附件上传失败', err)
    }
  }
  isUploading.value = false
}

function removePendingAttachment(index: number) {
  const att = pendingAttachments.value[index]
  if (att.previewUrl) URL.revokeObjectURL(att.previewUrl)
  pendingAttachments.value.splice(index, 1)
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)}KB`
  return `${(bytes / 1024 / 1024).toFixed(1)}MB`
}

// ── 发送消息 ──────────────────────────────────────────────────────────────────
async function send() {
  const text = inputText.value.trim()
  if ((!text && !pendingAttachments.value.length) || isStreaming.value) return
  if (!currentSessionId.value) {
    await newSession()
    if (!currentSessionId.value) return
  }

  // 构造带 URL 的附件用于发送和本地展示（使用上传时返回的 url）
  const attachmentsToSend: AttachmentItemWithUrl[] = pendingAttachments.value.map((a) => ({
    name: a.name,
    size: a.size,
    content_type: a.content_type,
    storage_key: a.storage_key,
    url: a.url,  // 后端用于拼接给外部 Agent 的附件文本
  }))

  // 乐观更新：立即显示用户消息
  messages.value.push({
    role: 'user',
    content: text,
    attachments: attachmentsToSend.length ? attachmentsToSend : undefined,
  })

  inputText.value = ''
  pendingAttachments.value = []
  isStreaming.value = true

  // 添加 assistant 占位消息（流式更新）
  const assistantIndex = messages.value.length
  messages.value.push({ role: 'assistant', content: '', streaming: true })
  await scrollToBottom()

  try {
    const res = await externalAgentApi.chatStream(
      agentId,
      text,
      currentSessionId.value,
      attachmentsToSend.length ? attachmentsToSend : undefined,
    )

    if (!res.body) throw new Error('响应无 body')
    const reader = res.body.getReader()
    const decoder = new TextDecoder()

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      const raw = decoder.decode(value, { stream: true })
      for (const line of raw.split('\n')) {
        if (!line.startsWith('data: ')) continue
        try {
          const payload = JSON.parse(line.slice(6))
          if (payload.chunk) {
            messages.value[assistantIndex].content += payload.chunk
            await scrollToBottom()
          } else if (payload.error) {
            messages.value[assistantIndex].content += `[错误: ${payload.error}]`
          }
        } catch {
          // 忽略非 JSON 行
        }
      }
    }
  } catch (e) {
    messages.value[assistantIndex].content += '[连接失败]'
  } finally {
    messages.value[assistantIndex].streaming = false
    isStreaming.value = false

    // 更新侧边栏会话 title（本地乐观更新）
    const session = sessions.value.find((s) => s.id === currentSessionId.value)
    if (session && !session.title && text) {
      session.title = text.slice(0, 50)
    }
    // 将当前会话移到列表顶部
    if (session) {
      sessions.value = [session, ...sessions.value.filter((s) => s.id !== session.id)]
    }
  }
}

async function scrollToBottom() {
  await nextTick()
  messagesEndRef.value?.scrollIntoView({ behavior: 'smooth' })
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}

// ── 内容渲染（linkify）────────────────────────────────────────────────────────
function renderContent(text: string): string {
  // 先做 HTML 转义防 XSS，再将 URL 转为可点击链接
  const escaped = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/\n/g, '<br>')
  return escaped.replace(
    /(https?:\/\/[^\s&<>"]+)/g,
    '<a href="$1" target="_blank" rel="noopener noreferrer" class="text-blue-600 underline break-all">$1</a>',
  )
}

function formatRelativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes}分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}小时前`
  return `${Math.floor(hours / 24)}天前`
}
</script>

<template>
  <div class="flex h-screen bg-white">
    <!-- 左侧会话列表 -->
    <aside class="w-60 flex-shrink-0 border-r border-gray-200 flex flex-col">
      <!-- 返回 + 新建 -->
      <div class="flex items-center justify-between px-3 py-3 border-b border-gray-100">
        <button
          class="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700"
          @click="$router.back()"
        >
          <ChevronLeft :size="16" />
          返回
        </button>
        <button
          class="flex items-center gap-1 text-sm text-indigo-600 hover:text-indigo-700"
          @click="newSession"
        >
          <Plus :size="16" />
          新建
        </button>
      </div>

      <!-- Agent 名称 -->
      <div class="px-3 py-2 border-b border-gray-100">
        <div class="flex items-center gap-2">
          <span v-if="agent?.icon_emoji" class="text-lg">{{ agent.icon_emoji }}</span>
          <span class="text-sm font-medium text-gray-800 truncate">{{ agent?.name }}</span>
        </div>
        <div class="flex items-center gap-1 mt-0.5">
          <span
            class="w-1.5 h-1.5 rounded-full"
            :class="agent?.is_reachable ? 'bg-green-500' : 'bg-gray-300'"
          />
          <span class="text-xs text-gray-400">
            {{ agent?.is_reachable ? '已连接' : '未连接' }}
          </span>
        </div>
      </div>

      <!-- 会话列表 -->
      <div class="flex-1 overflow-y-auto py-1">
        <div v-if="sessionsLoading" class="px-3 py-4 text-xs text-gray-400 text-center">
          加载中...
        </div>
        <div v-else-if="!sessions.length" class="px-3 py-4 text-xs text-gray-400 text-center">
          暂无对话，点击「新建」开始
        </div>
        <button
          v-for="s in sessions"
          :key="s.id"
          class="w-full text-left px-3 py-2 group flex items-start justify-between gap-1 hover:bg-gray-50 transition-colors"
          :class="s.id === currentSessionId ? 'bg-indigo-50' : ''"
          @click="switchSession(s.id)"
        >
          <div class="flex-1 min-w-0">
            <p class="text-sm text-gray-800 truncate">
              {{ s.title || '新对话' }}
            </p>
            <p class="text-xs text-gray-400">{{ formatRelativeTime(s.updated_at) }}</p>
          </div>
          <button
            class="opacity-0 group-hover:opacity-100 p-0.5 text-gray-400 hover:text-red-500 transition-opacity"
            @click="deleteSession(s.id, $event)"
          >
            <Trash2 :size="13" />
          </button>
        </button>
      </div>
    </aside>

    <!-- 右侧聊天区 -->
    <div class="flex-1 flex flex-col min-w-0">
      <!-- 消息区 -->
      <div class="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        <!-- 欢迎占位 -->
        <div
          v-if="!currentSessionId && !messagesLoading"
          class="flex flex-col items-center justify-center h-full gap-3 text-gray-400"
        >
          <span v-if="agent?.icon_emoji" class="text-4xl">{{ agent.icon_emoji }}</span>
          <p class="text-sm">{{ agent?.description || '开始与 Agent 对话' }}</p>
        </div>

        <!-- 消息加载中 -->
        <div v-if="messagesLoading" class="flex justify-center py-8">
          <span class="text-sm text-gray-400">加载历史消息...</span>
        </div>

        <!-- 消息列表 -->
        <template v-if="!messagesLoading">
          <div
            v-for="(msg, i) in messages"
            :key="i"
            class="flex"
            :class="msg.role === 'user' ? 'justify-end' : 'justify-start'"
          >
            <!-- 用户消息 -->
            <div v-if="msg.role === 'user'" class="max-w-[70%] space-y-1">
              <!-- 附件预览 -->
              <div v-if="msg.attachments?.length" class="flex flex-wrap gap-2 justify-end">
                <a
                  v-for="att in msg.attachments"
                  :key="att.storage_key"
                  :href="att.url"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="block"
                >
                  <img
                    v-if="att.content_type.startsWith('image/')"
                    :src="att.url"
                    :alt="att.name"
                    class="h-24 w-auto rounded-lg object-cover border border-gray-200"
                  />
                  <div
                    v-else
                    class="flex items-center gap-2 px-3 py-2 bg-white border border-gray-200 rounded-lg text-xs text-gray-600"
                  >
                    <FileText :size="14" />
                    <span class="truncate max-w-[160px]">{{ att.name }}</span>
                    <span class="text-gray-400">{{ formatFileSize(att.size) }}</span>
                  </div>
                </a>
              </div>
              <!-- 文本气泡 -->
              <div
                v-if="msg.content"
                class="px-4 py-2.5 bg-indigo-600 text-white text-sm rounded-2xl rounded-tr-sm whitespace-pre-wrap"
              >
                {{ msg.content }}
              </div>
            </div>

            <!-- Assistant 消息 -->
            <div v-else class="max-w-[70%]">
              <div
                class="px-4 py-2.5 bg-gray-100 text-gray-800 text-sm rounded-2xl rounded-tl-sm"
              >
                <!-- eslint-disable-next-line vue/no-v-html -->
                <span v-html="renderContent(msg.content)" />
                <span v-if="msg.streaming" class="inline-block w-0.5 h-3.5 bg-gray-500 ml-0.5 animate-pulse" />
              </div>
            </div>
          </div>
        </template>

        <div ref="messagesEndRef" />
      </div>

      <!-- 输入区 -->
      <div class="border-t border-gray-200 px-4 py-3">
        <!-- 待发附件预览卡片 -->
        <div v-if="pendingAttachments.length" class="flex flex-wrap gap-2 mb-2">
          <div
            v-for="(att, idx) in pendingAttachments"
            :key="att.storage_key"
            class="relative group"
          >
            <img
              v-if="att.content_type.startsWith('image/')"
              :src="att.previewUrl ?? att.url"
              :alt="att.name"
              class="h-16 w-auto rounded-lg object-cover border border-gray-200"
            />
            <div
              v-else
              class="flex items-center gap-2 px-3 py-2 bg-gray-100 rounded-lg text-xs text-gray-600 border border-gray-200"
            >
              <FileText :size="14" />
              <span class="truncate max-w-[100px]">{{ att.name }}</span>
            </div>
            <button
              class="absolute -top-1.5 -right-1.5 w-4 h-4 bg-gray-700 text-white rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
              @click="removePendingAttachment(idx)"
            >
              <X :size="10" />
            </button>
          </div>
          <div v-if="isUploading" class="flex items-center px-3 py-2 text-xs text-gray-400">
            上传中...
          </div>
        </div>

        <!-- 输入行 -->
        <div class="flex items-end gap-2">
          <!-- 附件按钮 -->
          <button
            class="p-2 text-gray-400 hover:text-gray-600 transition-colors flex-shrink-0"
            :disabled="!currentSessionId || isStreaming"
            @click="openFilePicker"
          >
            <Paperclip :size="18" />
          </button>
          <input
            ref="fileInputRef"
            type="file"
            multiple
            class="hidden"
            @change="handleFileChange"
          />

          <!-- 文本输入框 -->
          <textarea
            v-model="inputText"
            rows="1"
            class="flex-1 resize-none rounded-xl border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:border-indigo-400 max-h-32 overflow-y-auto"
            :class="{ 'opacity-50': !currentSessionId }"
            placeholder="输入消息，Enter 发送，Shift+Enter 换行"
            :disabled="!currentSessionId || isStreaming"
            @keydown="handleKeydown"
          />

          <!-- 发送按钮 -->
          <button
            class="p-2 bg-indigo-600 text-white rounded-xl hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex-shrink-0"
            :disabled="(!inputText.trim() && !pendingAttachments.length) || isStreaming || !currentSessionId"
            @click="send"
          >
            <Send :size="16" />
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 2: 启动前端开发服务器验证**

```bash
cd nodeskclaw-portal
npm run dev
```

访问外部 Agent 聊天页，检查：
1. 左侧显示会话列表（有历史则展示，无则显示「暂无对话」）
2. 「新建」按钮创建新会话
3. 切换会话后右侧历史消息加载
4. 回形针图标可点击，弹出文件选择
5. 选中图片后显示缩略图预览卡片，右上角 × 可移除
6. 输入文字 + 点击发送，用户气泡出现，助手流式回复

- [ ] **Step 3: 验证附件上传链路**

1. 选一张图片，确认预览卡片出现
2. 发送消息，Network 面板确认 `POST /attachments/upload` 和 `POST /chat` 请求均成功
3. 用户气泡上方出现图片缩略图
4. 刷新页面，历史消息（含附件）正常回显

- [ ] **Step 4: 验证助手消息 URL 可点击**

让外部 Agent 在回复中返回一个 URL（如 `https://example.com`），确认前端渲染为蓝色可点击链接。

- [ ] **Step 5: 提交**

```bash
git add src/views/external-agents/ExternalAgentChat.vue
git commit -m "feat(portal): 外部 Agent 聊天改造 — 多会话侧边栏 + 附件上传 + 历史持久化"
```

---

## 自检清单（实施完成后验证）

- [ ] 刷新页面后历史消息仍在
- [ ] 新建对话后切换至另一对话再切回，各自消息独立
- [ ] 删除会话后列表更新，若删当前会话则自动切换到下一个
- [ ] 附件 URL（presigned）在历史消息中正常展示（不因过期失效）
- [ ] 后端日志无 DB session 报错（`_persist_messages` 异常只打 warning）
- [ ] 发送时 `attachments_to_save` 中无 `url` 字段（只有 `storage_key`）
- [ ] 大文件（>20MB）上传返回 413 错误并有友好提示
