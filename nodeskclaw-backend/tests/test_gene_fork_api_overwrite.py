"""nodeskclaw-backend/tests/test_gene_fork_api_overwrite.py

验证 POST /genes/{gene_identifier}/fork 端点把请求体里的 overwrite 字段
透传给 service 层的 fork_gene_to_library()，而不是被悄悄丢弃或写死成 False。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_fork_endpoint_passes_overwrite_true_to_service_layer():
    # 注意：genes.py 里实际是 `from app.core.security import get_current_user`
    # dependency_overrides 必须覆盖同一个函数对象
    from app.core.security import get_current_user

    class _FakeUser:
        id = "u1"
        current_org_id = "org1"
        is_super_admin = False

    app.dependency_overrides[get_current_user] = lambda: _FakeUser()
    try:
        with patch(
            "app.api.genes.gene_service.fork_gene_to_library", new=AsyncMock(return_value={"id": "g1"}),
        ) as mock_fork:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/genes/some-gene-id/fork",
                    json={"target": "org", "overwrite": True},
                )
            assert resp.status_code == 200
            mock_fork.assert_awaited_once()
            _, kwargs = mock_fork.await_args
            assert kwargs.get("overwrite") is True
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_fork_endpoint_defaults_overwrite_to_false_when_omitted():
    from app.core.security import get_current_user

    class _FakeUser:
        id = "u1"
        current_org_id = "org1"
        is_super_admin = False

    app.dependency_overrides[get_current_user] = lambda: _FakeUser()
    try:
        with patch(
            "app.api.genes.gene_service.fork_gene_to_library", new=AsyncMock(return_value={"id": "g1"}),
        ) as mock_fork:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/genes/some-gene-id/fork",
                    json={"target": "personal"},
                )
            assert resp.status_code == 200
            mock_fork.assert_awaited_once()
            _, kwargs = mock_fork.await_args
            assert kwargs.get("overwrite") is False
    finally:
        app.dependency_overrides.pop(get_current_user, None)
