"""验证 /genes/upload-folder 的文件大小/数量限制（防内存与存储 DoS）。

覆盖范围：
  - 单文件超过单文件大小上限 → BadRequestError
  - 总大小超过总大小上限 → BadRequestError
  - 文件数量超过数量上限 → BadRequestError
  - 超大文件在分块读取过程中一旦越界立即中止，不会被整体读入内存
以上情况都应立即拒绝，不进入后续 skill_package_service 解析/DB 写入流程。

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


class _LazyHugeUpload:
    """按需生成内容的“超大文件”假对象：不预先分配声称的总大小，
    只在 read() 被调用时才吐出下一块，用来验证分块读取是否在越界后立刻停止。
    """

    def __init__(self, filename: str, chunk_size: int, total_chunks: int):
        self.filename = filename
        self._chunk_size = chunk_size
        self._remaining_chunks = total_chunks
        self.read_calls = 0

    async def read(self, size: int = -1) -> bytes:
        self.read_calls += 1
        if self._remaining_chunks <= 0:
            return b""
        self._remaining_chunks -= 1
        return b"x" * self._chunk_size


@pytest.mark.asyncio
async def test_oversized_file_aborts_early_without_full_buffering(monkeypatch):
    """单文件上限=5个分块，但“文件”声称有 10000 个分块（远超上限）。
    分块读取应在刚超过上限时立即抛错，read() 调用次数应远小于 10000，
    证明没有像旧实现那样先把整个超大文件读进内存再判断。
    """
    monkeypatch.setattr(genes, "_UPLOAD_READ_CHUNK_SIZE", 1024)
    monkeypatch.setattr(genes, "_MAX_UPLOAD_FILE_SIZE", 5 * 1024)
    monkeypatch.setattr(genes, "_MAX_UPLOAD_TOTAL_SIZE", 10_000 * 1024)

    huge = _LazyHugeUpload("huge.bin", chunk_size=1024, total_chunks=10_000)
    with pytest.raises(BadRequestError, match="超过单文件大小限制"):
        await genes.upload_gene_folder(
            files=[huge], db=MagicMock(), current_user=_fake_user(),
            overwrite=False, target="personal",
        )

    # 允许 5 块 + 触发越界判断的第 6 块，留一点余量但必须远小于声称的 10000 块
    assert huge.read_calls <= 10, (
        f"read() 被调用了 {huge.read_calls} 次，说明超大文件没有被提前中止读取"
    )
