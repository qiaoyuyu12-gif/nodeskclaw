"""验证 DockerFS 的 docker exec I/O 路径与 host 回退。

背景：openclaw 容器以 root 运行并把 .openclaw 收紧到 700，非 root 后端直接读写
宿主机 bind-mount 路径会 EACCES（原生 Linux/WSL）。DockerFS 因此改为：容器运行中
走 docker exec（root），未运行时回退宿主机路径。本组测试锁住这两条路径与分块写。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.nfs_mount import CHUNK_SIZE, DockerFS, NFSMountError, _reject_path_traversal


@pytest.fixture
def fs(tmp_path, monkeypatch):
    """构造一个 base 指向 tmp_path 的 DockerFS，避免污染真实数据目录。"""
    monkeypatch.setattr("app.services.docker_constants.DOCKER_DATA_DIR", tmp_path)
    return DockerFS("t1-abc", home_prefix=".openclaw")


# ─── 路径解析 ────────────────────────────────────────────────────────


def test_container_path_resolution(fs):
    assert fs._container_path(".openclaw/openclaw.json") == "/root/.openclaw/openclaw.json"
    assert fs._container_path("/root/.openclaw/skills/s/SKILL.md") == "/root/.openclaw/skills/s/SKILL.md"
    assert fs._container_path("openclaw.json") == "/root/.openclaw/openclaw.json"
    assert fs._container_path(".openclaw") == "/root/.openclaw"


# ─── 运行中：走 docker exec ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_write_text_running_uses_exec(fs):
    fs._running = True
    fs.exec_command = AsyncMock(return_value="")
    await fs.write_text(".openclaw/openclaw.json", '{"a":1}')

    fs.exec_command.assert_awaited_once()
    script = fs.exec_command.call_args.args[0][2]
    assert "base64 -d > '/root/.openclaw/openclaw.json'" in script
    assert "mkdir -p" in script


@pytest.mark.asyncio
async def test_read_text_running_uses_exec(fs):
    fs._running = True
    fs.exec_command = AsyncMock(return_value='{"x":1}')
    result = await fs.read_text(".openclaw/openclaw.json")

    assert result == '{"x":1}'
    script = fs.exec_command.call_args.args[0][2]
    assert "cat '/root/.openclaw/openclaw.json'" in script


@pytest.mark.asyncio
async def test_read_text_running_missing_returns_none(fs):
    fs._running = True
    fs.exec_command = AsyncMock(return_value="")  # cat ... || true -> 空
    assert await fs.read_text(".openclaw/nope.json") is None


@pytest.mark.asyncio
async def test_write_text_chunked_when_large(fs):
    fs._running = True
    fs.exec_command = AsyncMock(return_value="")
    # base64 膨胀 ~4/3，80KB 明文 -> 编码后 > CHUNK_SIZE，触发分块
    big = "x" * 80_000
    encoded_len = (len(big.encode()) + 2) // 3 * 4
    assert encoded_len > CHUNK_SIZE  # 前置条件

    await fs.write_text(".openclaw/big.json", big)

    calls = fs.exec_command.await_args_list
    # 第一刀清理临时文件
    assert calls[0].args[0] == ["rm", "-f", "/tmp/_ndk_upload.b64"]
    # 最后一刀解码落盘到目标
    last_script = calls[-1].args[0][2]
    assert "base64 -d /tmp/_ndk_upload.b64 > '/root/.openclaw/big.json'" in last_script
    # 中间至少有一次分块追加
    assert any(">> /tmp/_ndk_upload.b64" in c.args[0][2] for c in calls[1:-1])


# ─── 未运行：回退宿主机路径 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_write_text_stopped_falls_back_to_host(fs):
    fs._running = False
    fs.exec_command = AsyncMock()
    await fs.write_text(".openclaw/openclaw.json", '{"a":1}')

    fs.exec_command.assert_not_called()
    written = fs._base / "openclaw.json"
    assert written.read_text(encoding="utf-8") == '{"a":1}'


@pytest.mark.asyncio
async def test_read_text_stopped_reads_host_file(fs):
    fs._running = False
    (fs._base / "openclaw.json").write_text("hello", encoding="utf-8")
    assert await fs.read_text(".openclaw/openclaw.json") == "hello"


# ─── 容器状态检测 memoize ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_is_running_true_and_memoized(fs):
    with patch(
        "app.services.runtime.compute.docker_provider._run_docker",
        new=AsyncMock(return_value=(0, b"running\n", b"")),
    ) as run_docker:
        assert await fs._is_running() is True
        assert await fs._is_running() is True  # 第二次走缓存
    run_docker.assert_awaited_once()


@pytest.mark.asyncio
async def test_is_running_false_when_exited(fs):
    with patch(
        "app.services.runtime.compute.docker_provider._run_docker",
        new=AsyncMock(return_value=(0, b"exited\n", b"")),
    ):
        assert await fs._is_running() is False


@pytest.mark.asyncio
async def test_is_running_false_on_inspect_error(fs):
    with patch(
        "app.services.runtime.compute.docker_provider._run_docker",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        assert await fs._is_running() is False


# ─── 路径穿越防护（zip-slip 等恶意路径写穿到实例根目录之外）───────────


def test_reject_path_traversal_blocks_dotdot():
    with pytest.raises(NFSMountError):
        _reject_path_traversal("../../etc/passwd")
    with pytest.raises(NFSMountError):
        _reject_path_traversal("plugin/../../../../etc/cron.d/x")
    # 正常相对路径不受影响
    assert _reject_path_traversal(".openclaw/extensions/foo/bar.txt") == ".openclaw/extensions/foo/bar.txt"


def test_docker_fs_rel_blocks_dotdot(fs):
    with pytest.raises(NFSMountError):
        fs._rel("plugin/../../../../etc/cron.d/x")
    with pytest.raises(NFSMountError):
        fs._container_path("../../etc/passwd")


@pytest.mark.asyncio
async def test_write_text_stopped_rejects_traversal_before_touching_host(fs):
    """容器未运行时 write_text 直接落到宿主机 bind-mount 路径，.. 必须在落盘前被拦截。"""
    fs._running = False
    fs.exec_command = AsyncMock()
    with pytest.raises(NFSMountError):
        await fs.write_text("../../../../etc/cron.d/evil", "* * * * * root touch /tmp/pwned")

    fs.exec_command.assert_not_called()
