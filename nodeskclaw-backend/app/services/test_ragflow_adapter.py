# app/services/test_ragflow_adapter.py
from contextlib import asynccontextmanager

import httpx
import pytest

from app.core.exceptions import BadRequestError
from app.services import ragflow_adapter


class _FakeResp:
    def __init__(self, status_code=200, json_body=None):
        self.status_code = status_code
        self._json = json_body or {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "err", request=httpx.Request("GET", "http://x"),
                response=httpx.Response(self.status_code),
            )


def _patch_client(monkeypatch, resp=None, exc=None):
    """让 httpx.AsyncClient(...) 的 get/post 返回 resp 或抛 exc。"""
    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        @asynccontextmanager
        async def _ctx(self):
            yield self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            if exc:
                raise exc
            return resp

        post = get

    monkeypatch.setattr(ragflow_adapter.httpx, "AsyncClient", _FakeClient)


# ── _parse_ragflow：核心信封校验 ──────────────────────────────

def test_parse_ragflow_success_returns_body():
    body = ragflow_adapter._parse_ragflow(
        _FakeResp(200, {"code": 0, "data": {"docs": [], "total": 0}})
    )
    assert body["data"] == {"docs": [], "total": 0}


def test_parse_ragflow_error_envelope_raises_with_message():
    # RAGFlow 错误约定：HTTP 200 + code!=0 + data:false
    with pytest.raises(BadRequestError) as ei:
        ragflow_adapter._parse_ragflow(
            _FakeResp(200, {"code": 102, "message": "dataset not found", "data": False})
        )
    assert "dataset not found" in ei.value.message
    assert ei.value.message_key == "errors.kb.ragflow_error"
    assert ei.value.message_params == {"detail": "dataset not found"}


def test_parse_ragflow_auth_failure():
    with pytest.raises(BadRequestError) as ei:
        ragflow_adapter._parse_ragflow(_FakeResp(401))
    assert ei.value.message_key == "errors.kb.ragflow_auth_failed"


# ── list_documents：根因回归（data:false 不再 500） ──────────

@pytest.mark.asyncio
async def test_list_documents_surfaces_ragflow_error(monkeypatch):
    _patch_client(monkeypatch, resp=_FakeResp(200, {
        "code": 102, "message": "You don't own the dataset", "data": False,
    }))
    with pytest.raises(BadRequestError) as ei:
        await ragflow_adapter.list_documents("http://rf", "key", "bad-id")
    assert "You don't own the dataset" in ei.value.message


@pytest.mark.asyncio
async def test_list_documents_success_returns_dict(monkeypatch):
    _patch_client(monkeypatch, resp=_FakeResp(200, {
        "code": 0, "data": {"docs": [{"id": "d1", "name": "a.pdf"}], "total": 1},
    }))
    data = await ragflow_adapter.list_documents("http://rf", "key", "ok-id")
    assert data["total"] == 1
    assert data["docs"][0]["name"] == "a.pdf"


@pytest.mark.asyncio
async def test_list_documents_connection_error(monkeypatch):
    _patch_client(monkeypatch, exc=httpx.ConnectError("refused"))
    with pytest.raises(BadRequestError) as ei:
        await ragflow_adapter.list_documents("http://rf", "key", "id")
    assert ei.value.message_key == "errors.kb.ragflow_unreachable"


# ── verify_connection：带 kb_id 时校验具体 dataset ────────────

@pytest.mark.asyncio
async def test_verify_connection_invalid_kb_id_returns_false(monkeypatch):
    _patch_client(monkeypatch, resp=_FakeResp(200, {"code": 102, "data": False}))
    assert await ragflow_adapter.verify_connection("http://rf", "key", "bad-id") is False


@pytest.mark.asyncio
async def test_verify_connection_valid_kb_id_returns_true(monkeypatch):
    _patch_client(monkeypatch, resp=_FakeResp(200, {"code": 0, "data": {"docs": [], "total": 0}}))
    assert await ragflow_adapter.verify_connection("http://rf", "key", "ok-id") is True
