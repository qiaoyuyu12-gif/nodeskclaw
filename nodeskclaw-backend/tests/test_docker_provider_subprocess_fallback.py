"""验证 docker_provider._run_docker 跨平台 fallback 与 13 处统一迁移。

背景：Windows SelectorEventLoop 上 asyncio.create_subprocess_exec 抛
NotImplementedError，导致 docker_provider 整个部署链路炸掉。
本组测试锁住三个不变量，防止以后又有人裸写 asyncio.create_subprocess_exec。
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.runtime.compute import docker_provider as dp


# ─── _run_docker fallback ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_docker_falls_back_to_sync_on_not_implemented():
    """asyncio.create_subprocess_exec 抛 NotImplementedError 时，必须走
    线程池里的 subprocess.run 同步 fallback；返回 (rc, stdout, stderr)。"""

    async def _raise(*_args, **_kwargs):
        raise NotImplementedError()

    fake_completed = MagicMock(returncode=0, stdout=b"v2.30.0", stderr=b"")

    with patch.object(dp.asyncio, "create_subprocess_exec", side_effect=_raise), \
         patch("subprocess.run", return_value=fake_completed) as sync_run:
        rc, out, err = await dp._run_docker("docker", "compose", "version")

    assert rc == 0
    assert out == b"v2.30.0"
    assert err == b""
    sync_run.assert_called_once()
    # 同步路径必须传完整 args 列表
    called_args = sync_run.call_args[0][0]
    assert called_args == ["docker", "compose", "version"]


@pytest.mark.asyncio
async def test_run_docker_uses_async_when_supported():
    """正常路径（Linux/macOS）下不应触发 to_thread 回退，保持原异步实现。"""
    fake_proc = MagicMock()
    fake_proc.communicate = AsyncMock(return_value=(b"hello", b""))
    fake_proc.returncode = 0

    async def _create(*_args, **_kwargs):
        return fake_proc

    with patch.object(dp.asyncio, "create_subprocess_exec", side_effect=_create), \
         patch("subprocess.run") as sync_run:
        rc, out, err = await dp._run_docker("docker", "ps")

    assert rc == 0
    assert out == b"hello"
    sync_run.assert_not_called()  # 不应回退


@pytest.mark.asyncio
async def test_run_docker_propagates_nonzero_returncode():
    """命令失败时 rc 非 0、stderr 透传，调用方据此决定 raise 与否。"""
    fake_proc = MagicMock()
    fake_proc.communicate = AsyncMock(return_value=(b"", b"docker daemon not running"))
    fake_proc.returncode = 1

    async def _create(*_args, **_kwargs):
        return fake_proc

    with patch.object(dp.asyncio, "create_subprocess_exec", side_effect=_create):
        rc, _, err = await dp._run_docker("docker", "ps")

    assert rc == 1
    assert b"daemon not running" in err


# ─── 防回归：业务代码不再裸用 asyncio.create_subprocess_exec ─────────


def test_docker_provider_no_raw_async_subprocess_in_business_logic():
    """静态扫：业务代码不应再裸调 asyncio.create_subprocess_exec。

    全文应恰好出现 1 次（helper 内部）+ 文档字符串里提及（不算调用）。
    出现更多 = 这条 CLAUDE.md 易踩点 #2 的规则又被绕过了。
    """
    src = Path(dp.__file__).read_text(encoding="utf-8")
    # 仅统计真正的"调用"（带左括号），不统计 docstring 里的提及（"asyncio.create_subprocess_exec"）
    call_count = len(re.findall(r"asyncio\.create_subprocess_exec\s*\(", src))
    assert call_count == 1, (
        f"docker_provider.py 出现 {call_count} 次 asyncio.create_subprocess_exec(...) 调用，"
        f"期望恰好 1 次（仅 _run_docker helper 内部）。多余的调用必须改用 _run_docker。"
    )
