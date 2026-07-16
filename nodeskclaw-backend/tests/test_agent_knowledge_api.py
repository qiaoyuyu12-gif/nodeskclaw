from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api import agent_knowledge
from app.core.security import AuthActor, _auth_actor
from app.schemas.agent_knowledge import BoundKnowledgeBaseInfo, KnowledgeSearchRequest, KnowledgeSearchResponse


@pytest.fixture
def agent_actor():
    token = _auth_actor.set(AuthActor("agent", "inst-1", "Hermes"))
    try:
        yield
    finally:
        _auth_actor.reset(token)


@pytest.fixture
def user_actor():
    token = _auth_actor.set(AuthActor("user", "user-1", "Alice"))
    try:
        yield
    finally:
        _auth_actor.reset(token)


async def test_list_my_knowledge_bases_rejects_human_actor(user_actor) -> None:
    with pytest.raises(HTTPException) as exc:
        await agent_knowledge.list_my_knowledge_bases(db=object())

    assert exc.value.status_code == 403
    assert exc.value.detail["message_key"] == "errors.agent_knowledge.agent_only"


async def test_list_my_knowledge_bases_returns_bindings_for_agent(monkeypatch, agent_actor) -> None:
    list_bound = AsyncMock(return_value=[BoundKnowledgeBaseInfo(kb_id="kb-1", kb_name="KB", source_type="ragflow")])
    monkeypatch.setattr(agent_knowledge.agent_knowledge_service, "list_bound_knowledge_bases", list_bound)
    db = object()

    response = await agent_knowledge.list_my_knowledge_bases(db=db)

    assert response.data[0].kb_id == "kb-1"
    list_bound.assert_awaited_once_with("inst-1", db)


async def test_search_my_knowledge_bases_rejects_human_actor(user_actor) -> None:
    with pytest.raises(HTTPException) as exc:
        await agent_knowledge.search_my_knowledge_bases(
            KnowledgeSearchRequest(query="hello"), db=object(),
        )

    assert exc.value.status_code == 403
    assert exc.value.detail["message_key"] == "errors.agent_knowledge.agent_only"


async def test_search_my_knowledge_bases_derives_instance_id_from_actor(monkeypatch, agent_actor) -> None:
    search = AsyncMock(
        return_value=KnowledgeSearchResponse(results=[], kb_count=0, degraded=False, errors=[]),
    )
    monkeypatch.setattr(agent_knowledge.agent_knowledge_service, "search_bound_knowledge", search)
    db = object()

    await agent_knowledge.search_my_knowledge_bases(
        KnowledgeSearchRequest(query="hello", top_k=3, kb_ids=["kb-9"]), db=db,
    )

    search.assert_awaited_once_with(
        instance_id="inst-1", query="hello", top_k=3, kb_ids=["kb-9"], db=db,
    )
