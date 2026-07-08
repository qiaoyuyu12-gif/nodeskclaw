"""验证 /genes/upload-folder 的文件大小/数量限制（防内存与存储 DoS）。

覆盖范围：
  - 单文件超过单文件大小上限 → BadRequestError
  - 总大小超过总大小上限 → BadRequestError
  - 文件数量超过数量上限 → BadRequestError
以上三种情况都应立即拒绝，不进入后续 skill_package_service 解析/DB 写入流程。

用 monkeypatch 把限制常量调小，避免测试里构造几十 MB 的假数据。
"""

from __future__ import annotations

import io
from unittest.mock import MagicMock

import pytest
from starlette.datastructures import UploadFile

from app.api import genes
from app.core.exceptions import BadRequestError


def _make_upload(filename: str, content: bytes) -> UploadFile:
    return UploadFile(io.BytesIO(content), filename=filename)


def _fake_user():
    user = MagicMock()
    user.current_org_id = None
    return user


@pytest.mark.asyncio
async def test_single_file_over_size_limit_rejected(monkeypatch):
    monkeypatch.setattr(genes, "_MAX_UPLOAD_FILE_SIZE", 100)
    monkeypatch.setattr(genes, "_MAX_UPLOAD_TOTAL_SIZE", 10_000)
    files = [_make_upload("skill.md", b"x" * 101)]
    with pytest.raises(BadRequestError, match="超过单文件大小限制"):
        await genes.upload_gene_folder(
            files=files, db=MagicMock(), current_user=_fake_user(),
            overwrite=False, target="personal",
        )


@pytest.mark.asyncio
async def test_total_size_over_limit_rejected(monkeypatch):
    monkeypatch.setattr(genes, "_MAX_UPLOAD_FILE_SIZE", 100)
    monkeypatch.setattr(genes, "_MAX_UPLOAD_TOTAL_SIZE", 150)
    # 单个文件都不超过 100，但两个加起来 (80+80=160) 超过总大小上限 150
    files = [
        _make_upload("a.md", b"a" * 80),
        _make_upload("b.md", b"b" * 80),
    ]
    with pytest.raises(BadRequestError, match="总大小超过限制"):
        await genes.upload_gene_folder(
            files=files, db=MagicMock(), current_user=_fake_user(),
            overwrite=False, target="personal",
        )


@pytest.mark.asyncio
async def test_file_count_over_limit_rejected(monkeypatch):
    monkeypatch.setattr(genes, "_MAX_UPLOAD_FILE_COUNT", 3)
    files = [_make_upload(f"f{i}.md", b"x") for i in range(4)]
    with pytest.raises(BadRequestError, match="文件数量超过限制"):
        await genes.upload_gene_folder(
            files=files, db=MagicMock(), current_user=_fake_user(),
            overwrite=False, target="personal",
        )
