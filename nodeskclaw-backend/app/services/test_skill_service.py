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
