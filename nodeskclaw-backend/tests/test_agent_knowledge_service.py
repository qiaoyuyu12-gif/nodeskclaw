from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import BadRequestError
from app.services import agent_knowledge_service


def _binding(kb_id: str, *, enabled: bool = True, name: str = "KB", source_type: str = "ragflow") -> SimpleNamespace:
    kb = SimpleNamespace(
        id=kb_id,
        name=name,
        source_type=source_type,
        ragflow_endpoint="https://ragflow.example.com",
        ragflow_kb_id=f"ragflow-{kb_id}",
        api_key_encrypted="encrypted",
    )
    return SimpleNamespace(kb_id=kb_id, enabled=enabled, kb=kb)


async def test_search_bound_knowledge_returns_empty_when_no_bindings(monkeypatch) -> None:
    monkeypatch.setattr(
        agent_knowledge_service.instance_kb_service, "list_instance_kbs", AsyncMock(return_value=[]),
    )

    result = await agent_knowledge_service.search_bound_knowledge(
        instance_id="inst-1", query="hello", top_k=5, kb_ids=None, db=object(),
    )

    assert result.results == []
    assert result.kb_count == 0
    assert result.degraded is False
    assert result.errors == []


async def test_search_bound_knowledge_excludes_disabled_bindings(monkeypatch) -> None:
    bindings = [_binding("kb-1", enabled=True), _binding("kb-2", enabled=False)]
    monkeypatch.setattr(
        agent_knowledge_service.instance_kb_service, "list_instance_kbs", AsyncMock(return_value=bindings),
    )
    monkeypatch.setattr(agent_knowledge_service.kb_service, "get_decrypted_api_key", lambda kb: "api-key")
    retrieve = AsyncMock(return_value=[{"content": "chunk-1", "similarity": 0.9, "document_keyword": "doc.pdf"}])
    monkeypatch.setattr(agent_knowledge_service.ragflow_adapter, "retrieve", retrieve)

    result = await agent_knowledge_service.search_bound_knowledge(
        instance_id="inst-1", query="hello", top_k=5, kb_ids=None, db=object(),
    )

    assert result.kb_count == 1
    retrieve.assert_awaited_once()
    assert retrieve.await_args.args[2] == "ragflow-kb-1"


async def test_search_bound_knowledge_filters_by_kb_ids(monkeypatch) -> None:
    bindings = [_binding("kb-1"), _binding("kb-2")]
    monkeypatch.setattr(
        agent_knowledge_service.instance_kb_service, "list_instance_kbs", AsyncMock(return_value=bindings),
    )
    monkeypatch.setattr(agent_knowledge_service.kb_service, "get_decrypted_api_key", lambda kb: "api-key")
    retrieve = AsyncMock(return_value=[])
    monkeypatch.setattr(agent_knowledge_service.ragflow_adapter, "retrieve", retrieve)

    result = await agent_knowledge_service.search_bound_knowledge(
        instance_id="inst-1", query="hello", top_k=5, kb_ids=["kb-2"], db=object(),
    )

    assert result.kb_count == 1
    retrieve.assert_awaited_once()
    assert retrieve.await_args.args[2] == "ragflow-kb-2"


async def test_search_bound_knowledge_degrades_on_partial_failure(monkeypatch) -> None:
    bindings = [_binding("kb-1", name="Good KB"), _binding("kb-2", name="Bad KB")]
    monkeypatch.setattr(
        agent_knowledge_service.instance_kb_service, "list_instance_kbs", AsyncMock(return_value=bindings),
    )
    monkeypatch.setattr(agent_knowledge_service.kb_service, "get_decrypted_api_key", lambda kb: "api-key")

    async def fake_retrieve(_endpoint, _api_key, kb_id, _query, top_k=5):
        if kb_id == "ragflow-kb-1":
            return [{"content": "good chunk", "similarity": 0.8, "document_keyword": "doc.pdf"}]
        raise BadRequestError("RAGFlow 认证失败", "errors.ragflow.auth_failed")

    monkeypatch.setattr(agent_knowledge_service.ragflow_adapter, "retrieve", AsyncMock(side_effect=fake_retrieve))

    result = await agent_knowledge_service.search_bound_knowledge(
        instance_id="inst-1", query="hello", top_k=5, kb_ids=None, db=object(),
    )

    assert result.kb_count == 2
    assert result.degraded is True
    assert len(result.results) == 1
    assert result.results[0].content == "good chunk"
    assert len(result.errors) == 1
    assert result.errors[0].kb_id == "kb-2"
    assert result.errors[0].message == "RAGFlow 认证失败"


async def test_search_bound_knowledge_caps_and_sorts_results(monkeypatch) -> None:
    bindings = [_binding("kb-1")]
    monkeypatch.setattr(
        agent_knowledge_service.instance_kb_service, "list_instance_kbs", AsyncMock(return_value=bindings),
    )
    monkeypatch.setattr(agent_knowledge_service.kb_service, "get_decrypted_api_key", lambda kb: "api-key")
    chunks = [
        {"content": "low", "similarity": 0.1},
        {"content": "high", "similarity": 0.9},
        {"content": "mid", "similarity": 0.5},
    ]
    monkeypatch.setattr(agent_knowledge_service.ragflow_adapter, "retrieve", AsyncMock(return_value=chunks))

    result = await agent_knowledge_service.search_bound_knowledge(
        instance_id="inst-1", query="hello", top_k=2, kb_ids=None, db=object(),
    )

    assert [r.content for r in result.results] == ["high", "mid"]


async def test_list_bound_knowledge_bases_excludes_disabled(monkeypatch) -> None:
    bindings = [_binding("kb-1", enabled=True, name="A"), _binding("kb-2", enabled=False, name="B")]
    monkeypatch.setattr(
        agent_knowledge_service.instance_kb_service, "list_instance_kbs", AsyncMock(return_value=bindings),
    )

    result = await agent_knowledge_service.list_bound_knowledge_bases("inst-1", db=object())

    assert [kb.kb_id for kb in result] == ["kb-1"]
