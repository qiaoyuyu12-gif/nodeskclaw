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
