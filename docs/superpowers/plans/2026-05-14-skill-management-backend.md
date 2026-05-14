# Skill Management + RAGFlow — Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add enterprise skill management API to nodeskclaw-backend: knowledge base CRUD (backed by RAGFlow), skill definitions, agent bindings, and employee RAG Q&A with graceful degradation.

**Architecture:** Three new SQLAlchemy models registered in `app/models/__init__.py`; a stateless RAGFlow HTTP adapter; two service modules (`kb_service`, `skill_service`); two routers (`knowledge_bases`, `skills`) registered in `app/api/router.py`; Pydantic schemas in `app/schemas/skill.py`.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, asyncpg, httpx, pytest-asyncio, cryptography (AES-256-GCM — already in project)

---

## File Map

**Create:**
- `app/schemas/skill.py` — Pydantic request/response schemas
- `app/models/knowledge_base.py` — KnowledgeBase ORM model
- `app/models/skill_definition.py` — SkillDefinition ORM model
- `app/models/agent_skill_binding.py` — AgentSkillBinding ORM model
- `app/services/ragflow_adapter.py` — stateless RAGFlow HTTP wrapper
- `app/services/test_ragflow_adapter.py` — adapter tests
- `app/services/kb_service.py` — knowledge base CRUD
- `app/services/test_kb_service.py` — KB service tests
- `app/services/skill_service.py` — skill CRUD, binding, RAG query
- `app/services/test_skill_service.py` — skill service tests
- `app/api/knowledge_bases.py` — admin KB router
- `app/api/skills.py` — admin + employee skill router
- `alembic/versions/<hash>_add_skill_management.py` — auto-generated migration

**Modify:**
- `app/models/__init__.py` — add 3 new model imports
- `app/api/router.py` — register 2 new routers

---

## Task 1: Pydantic Schemas

**Files:**
- Create: `app/schemas/skill.py`

- [ ] **Step 1: Create the schemas file**

```python
# app/schemas/skill.py
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
```

- [ ] **Step 2: Commit**

```bash
git add app/schemas/skill.py
git commit -m "feat(skill): add Pydantic schemas for skill management"
```

---

## Task 2: Data Models

**Files:**
- Create: `app/models/knowledge_base.py`
- Create: `app/models/skill_definition.py`
- Create: `app/models/agent_skill_binding.py`
- Modify: `app/models/__init__.py`

- [ ] **Step 1: Create KnowledgeBase model**

```python
# app/models/knowledge_base.py
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class KnowledgeBase(BaseModel):
    __tablename__ = "knowledge_bases"

    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    ragflow_kb_id: Mapped[str] = mapped_column(String(256), nullable=False)
    ragflow_endpoint: Mapped[str] = mapped_column(String(512), nullable=False)
    # AES-256-GCM encrypted, stored as base64(nonce + ciphertext)
    api_key_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="doc", server_default="doc"
    )
```

- [ ] **Step 2: Create SkillDefinition model**

```python
# app/models/skill_definition.py
from sqlalchemy import Boolean, ForeignKey, Index, JSON, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class SkillDefinition(BaseModel):
    __tablename__ = "skill_definitions"
    __table_args__ = (
        Index(
            "uq_skill_definitions_org_name",
            "org_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)  # rag_query / gene / composite
    kb_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("knowledge_bases.id"), nullable=True
    )
    config: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'::json")
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
```

- [ ] **Step 3: Create AgentSkillBinding model**

```python
# app/models/agent_skill_binding.py
from sqlalchemy import Boolean, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class AgentSkillBinding(BaseModel):
    __tablename__ = "agent_skill_bindings"
    __table_args__ = (
        Index(
            "uq_agent_skill_bindings_instance_skill",
            "instance_id",
            "skill_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    instance_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("instances.id"), nullable=False, index=True
    )
    skill_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("skill_definitions.id"), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
```

- [ ] **Step 4: Register models in `__init__.py`**

Add after the last `from app.models.workspace_template import ...` line:

```python
from app.models.knowledge_base import KnowledgeBase  # noqa: F401
from app.models.skill_definition import SkillDefinition  # noqa: F401
from app.models.agent_skill_binding import AgentSkillBinding  # noqa: F401
```

- [ ] **Step 5: Commit**

```bash
git add app/models/knowledge_base.py app/models/skill_definition.py \
        app/models/agent_skill_binding.py app/models/__init__.py
git commit -m "feat(skill): add KnowledgeBase, SkillDefinition, AgentSkillBinding models"
```

---

## Task 3: Alembic Migration

**Files:**
- Create: `alembic/versions/<hash>_add_skill_management.py` (auto-generated)

- [ ] **Step 1: Generate the migration**

Run from `nodeskclaw-backend/`:

```bash
uv run alembic revision --autogenerate -m "add_skill_management"
```

Expected output: `Generating .../alembic/versions/<hash>_add_skill_management.py ... done`

- [ ] **Step 2: Verify the generated migration**

Open the generated file and confirm it contains `op.create_table("knowledge_bases", ...)`, `op.create_table("skill_definitions", ...)`, `op.create_table("agent_skill_bindings", ...)`, and the three `op.create_index(...)` calls for partial unique indexes.

If any table is missing, a model import was not added to `app/models/__init__.py` — fix that and regenerate.

- [ ] **Step 3: Apply the migration**

```bash
uv run alembic upgrade head
```

Expected output: `Running upgrade <prev> -> <hash>, add_skill_management`

- [ ] **Step 4: Commit**

```bash
git add alembic/versions/
git commit -m "feat(skill): add Alembic migration for skill management tables"
```

---

## Task 4: RAGFlow Adapter

**Files:**
- Create: `app/services/ragflow_adapter.py`
- Create: `app/services/test_ragflow_adapter.py`

- [ ] **Step 1: Write failing tests**

```python
# app/services/test_ragflow_adapter.py
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_retrieve_returns_chunks():
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": {"chunks": [{"content": "hello", "score": 0.9}]}
    }
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        from app.services.ragflow_adapter import retrieve

        result = await retrieve("http://ragflow:9380", "api-key", "kb-1", "what is X")

    assert result == [{"content": "hello", "score": 0.9}]
    mock_client.post.assert_called_once_with(
        "http://ragflow:9380/api/v1/retrieval",
        headers={"Authorization": "Bearer api-key"},
        json={"dataset_ids": ["kb-1"], "question": "what is X", "top_k": 5},
    )


@pytest.mark.asyncio
async def test_retrieve_respects_custom_top_k():
    mock_response = MagicMock()
    mock_response.json.return_value = {"data": {"chunks": []}}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        from app.services.ragflow_adapter import retrieve

        await retrieve("http://ragflow:9380", "key", "kb-1", "query", top_k=10)

    call_json = mock_client.post.call_args.kwargs["json"]
    assert call_json["top_k"] == 10


@pytest.mark.asyncio
async def test_verify_connection_returns_true_on_200():
    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response

    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        from app.services.ragflow_adapter import verify_connection

        result = await verify_connection("http://ragflow:9380", "key")

    assert result is True


@pytest.mark.asyncio
async def test_verify_connection_returns_false_on_exception():
    mock_client = AsyncMock()
    mock_client.get.side_effect = Exception("connection refused")

    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        from app.services.ragflow_adapter import verify_connection

        result = await verify_connection("http://ragflow:9380", "bad-key")

    assert result is False
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
uv run pytest app/services/test_ragflow_adapter.py -v
```

Expected: `ImportError: cannot import name 'retrieve' from 'app.services.ragflow_adapter'`

- [ ] **Step 3: Implement the adapter**

```python
# app/services/ragflow_adapter.py
import logging

import httpx

logger = logging.getLogger(__name__)


async def retrieve(
    endpoint: str,
    api_key: str,
    kb_id: str,
    question: str,
    top_k: int = 5,
) -> list[dict]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{endpoint.rstrip('/')}/api/v1/retrieval",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"dataset_ids": [kb_id], "question": question, "top_k": top_k},
        )
        resp.raise_for_status()
        return resp.json()["data"]["chunks"]


async def verify_connection(endpoint: str, api_key: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{endpoint.rstrip('/')}/api/v1/datasets",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            return resp.status_code == 200
    except Exception:
        logger.debug("RAGFlow connection check failed", exc_info=True)
        return False
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
uv run pytest app/services/test_ragflow_adapter.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add app/services/ragflow_adapter.py app/services/test_ragflow_adapter.py
git commit -m "feat(skill): add RAGFlow HTTP adapter"
```

---

## Task 5: Knowledge Base Service

**Files:**
- Create: `app/services/kb_service.py`
- Create: `app/services/test_kb_service.py`

- [ ] **Step 1: Write failing tests**

```python
# app/services/test_kb_service.py
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_create_knowledge_base_encrypts_api_key():
    db = AsyncMock()
    db.add = MagicMock()

    with patch("app.services.kb_service.encrypt_sensitive", return_value="encrypted-key"):
        from app.services.kb_service import create_knowledge_base

        kb = await create_knowledge_base(
            org_id="org-1",
            name="My KB",
            ragflow_endpoint="http://ragflow:9380",
            ragflow_kb_id="kb-abc",
            api_key="plain-secret",
            source_type="doc",
            db=db,
        )

    assert kb.name == "My KB"
    assert kb.api_key_encrypted == "encrypted-key"
    assert kb.org_id == "org-1"
    db.add.assert_called_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_knowledge_base_soft_deletes():
    existing_kb = MagicMock()
    existing_kb.soft_delete = MagicMock()
    db = AsyncMock()

    with patch("app.services.kb_service.get_knowledge_base", return_value=existing_kb):
        from app.services.kb_service import delete_knowledge_base

        await delete_knowledge_base("kb-1", "org-1", db)

    existing_kb.soft_delete.assert_called_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_decrypted_api_key_decrypts():
    kb = MagicMock()
    kb.api_key_encrypted = "encrypted-value"

    with patch("app.services.kb_service.decrypt_sensitive", return_value="plain-key"):
        from app.services.kb_service import get_decrypted_api_key

        result = await get_decrypted_api_key(kb)

    assert result == "plain-key"
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
uv run pytest app/services/test_kb_service.py -v
```

Expected: `ImportError: cannot import name 'create_knowledge_base' from 'app.services.kb_service'`

- [ ] **Step 3: Implement KB service**

```python
# app/services/kb_service.py
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.security import decrypt_sensitive, encrypt_sensitive
from app.models.knowledge_base import KnowledgeBase

logger = logging.getLogger(__name__)


async def create_knowledge_base(
    org_id: str,
    name: str,
    ragflow_endpoint: str,
    ragflow_kb_id: str,
    api_key: str,
    source_type: str,
    db: AsyncSession,
) -> KnowledgeBase:
    kb = KnowledgeBase(
        org_id=org_id,
        name=name,
        ragflow_endpoint=ragflow_endpoint,
        ragflow_kb_id=ragflow_kb_id,
        api_key_encrypted=encrypt_sensitive(api_key),
        source_type=source_type,
    )
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    return kb


async def list_knowledge_bases(org_id: str, db: AsyncSession) -> list[KnowledgeBase]:
    result = await db.execute(
        select(KnowledgeBase)
        .where(KnowledgeBase.org_id == org_id, KnowledgeBase.deleted_at.is_(None))
        .order_by(KnowledgeBase.created_at.desc())
    )
    return list(result.scalars().all())


async def get_knowledge_base(kb_id: str, org_id: str, db: AsyncSession) -> KnowledgeBase:
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.org_id == org_id,
            KnowledgeBase.deleted_at.is_(None),
        )
    )
    kb = result.scalar_one_or_none()
    if kb is None:
        raise NotFoundError("knowledge_base", kb_id)
    return kb


async def get_decrypted_api_key(kb: KnowledgeBase) -> str:
    return decrypt_sensitive(kb.api_key_encrypted)


async def update_knowledge_base(
    kb_id: str,
    org_id: str,
    updates: dict,
    db: AsyncSession,
) -> KnowledgeBase:
    kb = await get_knowledge_base(kb_id, org_id, db)
    if "api_key" in updates:
        kb.api_key_encrypted = encrypt_sensitive(updates.pop("api_key"))
    for key, value in updates.items():
        setattr(kb, key, value)
    await db.commit()
    await db.refresh(kb)
    return kb


async def delete_knowledge_base(kb_id: str, org_id: str, db: AsyncSession) -> None:
    kb = await get_knowledge_base(kb_id, org_id, db)
    kb.soft_delete()
    await db.commit()
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
uv run pytest app/services/test_kb_service.py -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add app/services/kb_service.py app/services/test_kb_service.py
git commit -m "feat(skill): add knowledge base service"
```

---

## Task 6: Skill Service

**Files:**
- Create: `app/services/skill_service.py`
- Create: `app/services/test_skill_service.py`

- [ ] **Step 1: Write failing tests**

```python
# app/services/test_skill_service.py
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_create_skill_raises_for_rag_query_without_kb_id():
    from app.core.exceptions import BadRequestError
    from app.services.skill_service import create_skill

    db = AsyncMock()
    with pytest.raises(BadRequestError, match="kb_id is required"):
        await create_skill("org-1", "my-skill", "rag_query", None, {}, db)


@pytest.mark.asyncio
async def test_create_skill_succeeds_for_gene_without_kb_id():
    db = AsyncMock()
    db.add = MagicMock()

    from app.services.skill_service import create_skill

    skill = await create_skill("org-1", "gene-skill", "gene", None, {}, db)

    assert skill.name == "gene-skill"
    assert skill.type == "gene"
    db.add.assert_called_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_query_skill_returns_chunks_from_ragflow():
    mock_skill = MagicMock()
    mock_skill.type = "rag_query"
    mock_skill.kb_id = "kb-1"
    mock_skill.config = {"top_k": 3}

    mock_kb = MagicMock()
    mock_kb.ragflow_endpoint = "http://ragflow:9380"
    mock_kb.ragflow_kb_id = "ragflow-dataset-abc"

    db = AsyncMock()

    with (
        patch("app.services.skill_service.get_skill", return_value=mock_skill),
        patch("app.services.skill_service.kb_service.get_knowledge_base", return_value=mock_kb),
        patch("app.services.skill_service.kb_service.get_decrypted_api_key", return_value="api-key"),
        patch(
            "app.services.skill_service.ragflow_adapter.retrieve",
            return_value=[{"content": "answer", "score": 0.95}],
        ),
    ):
        from app.services.skill_service import query_skill

        result = await query_skill("skill-1", "org-1", "what is X?", db)

    assert result["degraded"] is False
    assert result["results"] == [{"content": "answer", "score": 0.95}]


@pytest.mark.asyncio
async def test_query_skill_returns_degraded_when_ragflow_fails():
    mock_skill = MagicMock()
    mock_skill.type = "rag_query"
    mock_skill.kb_id = "kb-1"
    mock_skill.config = {}

    mock_kb = MagicMock()
    mock_kb.ragflow_endpoint = "http://ragflow:9380"
    mock_kb.ragflow_kb_id = "kb-abc"

    db = AsyncMock()

    with (
        patch("app.services.skill_service.get_skill", return_value=mock_skill),
        patch("app.services.skill_service.kb_service.get_knowledge_base", return_value=mock_kb),
        patch("app.services.skill_service.kb_service.get_decrypted_api_key", return_value="key"),
        patch(
            "app.services.skill_service.ragflow_adapter.retrieve",
            side_effect=Exception("connection timeout"),
        ),
    ):
        from app.services.skill_service import query_skill

        result = await query_skill("skill-1", "org-1", "test?", db)

    assert result["degraded"] is True
    assert "暂时不可用" in result["message"]
    assert result["results"] == []
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
uv run pytest app/services/test_skill_service.py -v
```

Expected: `ImportError: cannot import name 'create_skill' from 'app.services.skill_service'`

- [ ] **Step 3: Implement skill service**

```python
# app/services/skill_service.py
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError
from app.models.agent_skill_binding import AgentSkillBinding
from app.models.skill_definition import SkillDefinition
from app.services import kb_service, ragflow_adapter

logger = logging.getLogger(__name__)


async def create_skill(
    org_id: str,
    name: str,
    skill_type: str,
    kb_id: str | None,
    config: dict,
    db: AsyncSession,
) -> SkillDefinition:
    if skill_type == "rag_query" and not kb_id:
        raise BadRequestError("kb_id is required for rag_query skills")
    skill = SkillDefinition(
        org_id=org_id,
        name=name,
        type=skill_type,
        kb_id=kb_id,
        config=config,
    )
    db.add(skill)
    await db.commit()
    await db.refresh(skill)
    return skill


async def list_skills(
    org_id: str,
    skill_type: str | None,
    db: AsyncSession,
) -> list[SkillDefinition]:
    q = select(SkillDefinition).where(
        SkillDefinition.org_id == org_id,
        SkillDefinition.deleted_at.is_(None),
    )
    if skill_type:
        q = q.where(SkillDefinition.type == skill_type)
    result = await db.execute(q.order_by(SkillDefinition.created_at.desc()))
    return list(result.scalars().all())


async def get_skill(skill_id: str, org_id: str, db: AsyncSession) -> SkillDefinition:
    result = await db.execute(
        select(SkillDefinition).where(
            SkillDefinition.id == skill_id,
            SkillDefinition.org_id == org_id,
            SkillDefinition.deleted_at.is_(None),
        )
    )
    skill = result.scalar_one_or_none()
    if skill is None:
        raise NotFoundError("skill", skill_id)
    return skill


async def update_skill(
    skill_id: str,
    org_id: str,
    updates: dict,
    db: AsyncSession,
) -> SkillDefinition:
    skill = await get_skill(skill_id, org_id, db)
    for key, value in updates.items():
        setattr(skill, key, value)
    await db.commit()
    await db.refresh(skill)
    return skill


async def delete_skill(skill_id: str, org_id: str, db: AsyncSession) -> None:
    skill = await get_skill(skill_id, org_id, db)
    skill.soft_delete()
    await db.commit()


async def bind_skill(
    skill_id: str,
    instance_id: str,
    created_by: str,
    db: AsyncSession,
) -> AgentSkillBinding:
    binding = AgentSkillBinding(
        skill_id=skill_id,
        instance_id=instance_id,
        created_by=created_by,
    )
    db.add(binding)
    await db.commit()
    await db.refresh(binding)
    return binding


async def unbind_skill(skill_id: str, instance_id: str, db: AsyncSession) -> None:
    result = await db.execute(
        select(AgentSkillBinding).where(
            AgentSkillBinding.skill_id == skill_id,
            AgentSkillBinding.instance_id == instance_id,
            AgentSkillBinding.deleted_at.is_(None),
        )
    )
    binding = result.scalar_one_or_none()
    if binding is None:
        raise NotFoundError("binding", f"{skill_id}/{instance_id}")
    binding.soft_delete()
    await db.commit()


async def list_my_skills(org_id: str, db: AsyncSession) -> list[SkillDefinition]:
    result = await db.execute(
        select(SkillDefinition)
        .where(
            SkillDefinition.org_id == org_id,
            SkillDefinition.enabled.is_(True),
            SkillDefinition.deleted_at.is_(None),
        )
        .order_by(SkillDefinition.name)
    )
    return list(result.scalars().all())


async def query_skill(
    skill_id: str,
    org_id: str,
    question: str,
    db: AsyncSession,
) -> dict:
    try:
        skill = await get_skill(skill_id, org_id, db)
        if skill.type != "rag_query" or not skill.kb_id:
            raise BadRequestError("skill is not a rag_query type with a knowledge base")
        kb = await kb_service.get_knowledge_base(skill.kb_id, org_id, db)
        api_key = await kb_service.get_decrypted_api_key(kb)
        top_k = skill.config.get("top_k", 5) if skill.config else 5
        chunks = await ragflow_adapter.retrieve(
            kb.ragflow_endpoint, api_key, kb.ragflow_kb_id, question, top_k
        )
        return {"degraded": False, "message": None, "results": chunks}
    except BadRequestError:
        raise
    except Exception:
        logger.exception("RAGFlow query failed for skill %s", skill_id)
        return {"degraded": True, "message": "知识库暂时不可用，请稍后重试", "results": []}
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
uv run pytest app/services/test_skill_service.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add app/services/skill_service.py app/services/test_skill_service.py
git commit -m "feat(skill): add skill service with RAG query and degraded fallback"
```

---

## Task 7: Knowledge Base Router

**Files:**
- Create: `app/api/knowledge_bases.py`

- [ ] **Step 1: Create the KB admin router**

```python
# app/api/knowledge_bases.py
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_org_admin
from app.schemas.common import ApiResponse
from app.schemas.skill import KnowledgeBaseCreate, KnowledgeBaseResponse, KnowledgeBaseUpdate
from app.services import kb_service

router = APIRouter()


@router.post("", response_model=ApiResponse[KnowledgeBaseResponse])
async def create_kb(
    body: KnowledgeBaseCreate,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_org_admin),
):
    user, org = auth
    kb = await kb_service.create_knowledge_base(
        org_id=org.id,
        name=body.name,
        ragflow_endpoint=body.ragflow_endpoint,
        ragflow_kb_id=body.ragflow_kb_id,
        api_key=body.api_key,
        source_type=body.source_type,
        db=db,
    )
    return ApiResponse(data=KnowledgeBaseResponse.model_validate(kb))


@router.get("", response_model=ApiResponse[list[KnowledgeBaseResponse]])
async def list_kbs(
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_org_admin),
):
    user, org = auth
    kbs = await kb_service.list_knowledge_bases(org_id=org.id, db=db)
    return ApiResponse(data=[KnowledgeBaseResponse.model_validate(kb) for kb in kbs])


@router.patch("/{kb_id}", response_model=ApiResponse[KnowledgeBaseResponse])
async def update_kb(
    kb_id: str,
    body: KnowledgeBaseUpdate,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_org_admin),
):
    user, org = auth
    updates = body.model_dump(exclude_none=True)
    kb = await kb_service.update_knowledge_base(
        kb_id=kb_id, org_id=org.id, updates=updates, db=db
    )
    return ApiResponse(data=KnowledgeBaseResponse.model_validate(kb))


@router.delete("/{kb_id}", response_model=ApiResponse[None])
async def delete_kb(
    kb_id: str,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_org_admin),
):
    user, org = auth
    await kb_service.delete_knowledge_base(kb_id=kb_id, org_id=org.id, db=db)
    return ApiResponse(data=None)
```

- [ ] **Step 2: Add sync endpoint to the KB router**

Append to `app/api/knowledge_bases.py` after `delete_kb`:

```python
@router.post("/{kb_id}/sync", response_model=ApiResponse[dict])
async def sync_kb(
    kb_id: str,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_org_admin),
):
    user, org = auth
    kb = await kb_service.get_knowledge_base(kb_id=kb_id, org_id=org.id, db=db)
    api_key = await kb_service.get_decrypted_api_key(kb)
    reachable = await ragflow_adapter.verify_connection(kb.ragflow_endpoint, api_key)
    return ApiResponse(data={"reachable": reachable, "kb_id": kb_id})
```

Add the import at the top of the file:

```python
from app.services import ragflow_adapter
```

- [ ] **Step 3: Commit**

```bash
git add app/api/knowledge_bases.py
git commit -m "feat(skill): add knowledge base admin router with sync endpoint"
```

---

## Task 8: Skill Router

**Files:**
- Create: `app/api/skills.py`

- [ ] **Step 1: Create the skill router**

```python
# app/api/skills.py
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_org_admin
from app.core.security import get_current_user
from app.schemas.common import ApiResponse
from app.schemas.skill import (
    BindRequest,
    QueryRequest,
    QueryResponse,
    SkillCreate,
    SkillResponse,
    SkillUpdate,
)
from app.services import skill_service

router = APIRouter()


@router.get("/my", response_model=ApiResponse[list[SkillResponse]])
async def my_skills(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    if not user.current_org_id:
        return ApiResponse(data=[])
    skills = await skill_service.list_my_skills(org_id=user.current_org_id, db=db)
    return ApiResponse(data=[SkillResponse.model_validate(s) for s in skills])


@router.post("/{skill_id}/query", response_model=ApiResponse[QueryResponse])
async def query_skill(
    skill_id: str,
    body: QueryRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    if not user.current_org_id:
        return ApiResponse(data=QueryResponse(degraded=True, message="用户未加入组织"))
    result = await skill_service.query_skill(
        skill_id=skill_id, org_id=user.current_org_id, question=body.question, db=db
    )
    return ApiResponse(data=QueryResponse(**result))


@router.post("", response_model=ApiResponse[SkillResponse])
async def create_skill(
    body: SkillCreate,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_org_admin),
):
    user, org = auth
    skill = await skill_service.create_skill(
        org_id=org.id,
        name=body.name,
        skill_type=body.type,
        kb_id=body.kb_id,
        config=body.config,
        db=db,
    )
    return ApiResponse(data=SkillResponse.model_validate(skill))


@router.get("", response_model=ApiResponse[list[SkillResponse]])
async def list_skills(
    skill_type: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_org_admin),
):
    user, org = auth
    skills = await skill_service.list_skills(org_id=org.id, skill_type=skill_type, db=db)
    return ApiResponse(data=[SkillResponse.model_validate(s) for s in skills])


@router.patch("/{skill_id}", response_model=ApiResponse[SkillResponse])
async def update_skill(
    skill_id: str,
    body: SkillUpdate,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_org_admin),
):
    user, org = auth
    skill = await skill_service.update_skill(
        skill_id=skill_id, org_id=org.id, updates=body.model_dump(exclude_none=True), db=db
    )
    return ApiResponse(data=SkillResponse.model_validate(skill))


@router.delete("/{skill_id}", response_model=ApiResponse[None])
async def delete_skill(
    skill_id: str,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_org_admin),
):
    user, org = auth
    await skill_service.delete_skill(skill_id=skill_id, org_id=org.id, db=db)
    return ApiResponse(data=None)


@router.post("/{skill_id}/bind", response_model=ApiResponse[None])
async def bind_skill(
    skill_id: str,
    body: BindRequest,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_org_admin),
):
    user, org = auth
    await skill_service.bind_skill(
        skill_id=skill_id, instance_id=body.instance_id, created_by=user.id, db=db
    )
    return ApiResponse(data=None)


@router.delete("/{skill_id}/bind/{instance_id}", response_model=ApiResponse[None])
async def unbind_skill(
    skill_id: str,
    instance_id: str,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_org_admin),
):
    user, org = auth
    await skill_service.unbind_skill(skill_id=skill_id, instance_id=instance_id, db=db)
    return ApiResponse(data=None)
```

- [ ] **Step 2: Commit**

```bash
git add app/api/skills.py
git commit -m "feat(skill): add skill admin and employee router"
```

---

## Task 9: Register Routers

**Files:**
- Modify: `app/api/router.py`

- [ ] **Step 1: Add imports to `router.py`**

Find the existing import block at the top of `app/api/router.py` and add:

```python
from app.api.knowledge_bases import router as kb_router
from app.api.skills import router as skill_router
```

- [ ] **Step 2: Register routers**

In the `api_router.include_router(...)` block, add after the last `gene_router` line:

```python
api_router.include_router(kb_router, prefix="/knowledge-bases", tags=["知识库管理"])
api_router.include_router(skill_router, prefix="/skills", tags=["技能管理"])
```

- [ ] **Step 3: Start the server and verify endpoints appear**

```bash
uv run uvicorn app.main:app --reload --port 4510
```

Open http://localhost:4510/docs and confirm `/api/v1/knowledge-bases` and `/api/v1/skills` groups appear.

- [ ] **Step 4: Run the full test suite**

```bash
uv run pytest app/services/test_ragflow_adapter.py \
              app/services/test_kb_service.py \
              app/services/test_skill_service.py -v
```

Expected: `11 passed`

- [ ] **Step 5: Commit**

```bash
git add app/api/router.py
git commit -m "feat(skill): register knowledge-bases and skills routers"
```
