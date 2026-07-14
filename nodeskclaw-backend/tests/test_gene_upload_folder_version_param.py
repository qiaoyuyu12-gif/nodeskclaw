"""nodeskclaw-backend/tests/test_gene_upload_folder_version_param.py

验证 POST /genes/upload-folder 的 version query 参数被正确传给
create_gene()，而不是被忽略、永远落到 schema 默认值 "1.0.0"。

跟 test_gene_upload_target_restriction.py 保持一致的风格：复用
tests/conftest.py 里的 `client` fixture（已配好 get_db override），
从 app.core.security 导入 get_current_user 做 dependency override。
"""
from __future__ import annotations

import io
from unittest.mock import AsyncMock, patch

import pytest

from app.core.security import get_current_user
from app.main import app


class _FakeUser:
    """最小可用的伪用户，覆盖上传接口用到的字段。"""

    id = "u1"
    current_org_id = None
    is_super_admin = False


@pytest.mark.asyncio
async def test_upload_folder_passes_version_to_create_gene(client):
    # patch gene_service.create_gene，避免真正落库，同时可以断言它被调用时
    # 收到的 GeneCreateRequest 是否带上了 query 里传的 version
    app.dependency_overrides[get_current_user] = lambda: _FakeUser()
    try:
        with patch(
            "app.api.genes.gene_service.create_gene",
            new=AsyncMock(return_value={"id": "g1", "version": "2.3.0"}),
        ) as mock_create:
            files = {"files": ("SKILL.md", io.BytesIO(b"# skill\ncontent"), "text/markdown")}
            resp = await client.post(
                "/api/v1/genes/upload-folder?target=personal&version=2.3.0", files=files,
            )
            assert resp.status_code == 200
            mock_create.assert_awaited_once()
            args, _kwargs = mock_create.await_args
            # create_gene(db, gene_req, user_id=..., org_id=..., visibility=..., review_status=...)
            # version 应该在 gene_req（GeneCreateRequest 实例）里，而不是丢失
            gene_req = args[1]
            assert gene_req.version == "2.3.0"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_upload_folder_defaults_version_when_omitted(client):
    # 不传 version 时，应透传 schema 默认值 "1.0.0"，行为与改动前保持一致
    app.dependency_overrides[get_current_user] = lambda: _FakeUser()
    try:
        with patch(
            "app.api.genes.gene_service.create_gene",
            new=AsyncMock(return_value={"id": "g1", "version": "1.0.0"}),
        ) as mock_create:
            files = {"files": ("SKILL.md", io.BytesIO(b"# skill\ncontent"), "text/markdown")}
            resp = await client.post(
                "/api/v1/genes/upload-folder?target=personal", files=files,
            )
            assert resp.status_code == 200
            mock_create.assert_awaited_once()
            args, _kwargs = mock_create.await_args
            gene_req = args[1]
            assert gene_req.version == "1.0.0"
    finally:
        app.dependency_overrides.pop(get_current_user, None)
