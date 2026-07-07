"""验证技能附属文件（reference/example/assets）部署到实例的行为。

背景：文件夹上传的技能包中 reference/example 等文件存于 genes.manifest，
但安装到实例时只写 SKILL.md，导致 agent 读不到附属文件。

测试矩阵：
  - sanitize_skill_file_path：合法路径归一化 / 路径穿越与空路径拒绝
  - OpenClawGeneInstallAdapter.deploy_skill_files：按相对路径写入技能目录，
    跳过非法路径与空内容
  - _apply_manifest_actions：manifest 中 assets + references 合并后
    调用 deploy_skill_files；无 skill_name 时不调用
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.runtime.gene_install_adapter import sanitize_skill_file_path
from app.services.runtime.openclaw_gene_install_adapter import (
    OpenClawGeneInstallAdapter,
)


# ── sanitize_skill_file_path ────────────────────


def test_sanitize_normal_path():
    """正常相对路径原样返回。"""
    assert sanitize_skill_file_path("reference/guide.md") == "reference/guide.md"


def test_sanitize_windows_separator_and_leading_slash():
    """反斜杠归一化为正斜杠，首尾斜杠剥离。"""
    assert sanitize_skill_file_path("example\\demo.md") == "example/demo.md"
    assert sanitize_skill_file_path("/reference/a.md") == "reference/a.md"


def test_sanitize_rejects_traversal_and_empty():
    """路径穿越、当前目录引用、空路径均拒绝。"""
    assert sanitize_skill_file_path("../evil.md") is None
    assert sanitize_skill_file_path("reference/../../etc/passwd") is None
    assert sanitize_skill_file_path("./reference/a.md") is None
    assert sanitize_skill_file_path("") is None
    assert sanitize_skill_file_path("/") is None


# ── OpenClawGeneInstallAdapter.deploy_skill_files ────────────────────


@pytest.mark.asyncio
async def test_deploy_skill_files_writes_relative_paths():
    """附属文件按相对路径写入 .openclaw/skills/{name}/ 下。"""
    adapter = OpenClawGeneInstallAdapter()
    fs = AsyncMock()

    await adapter.deploy_skill_files(fs, "my-skill", {
        "reference/guide.md": "guide content",
        "example/demo.md": "demo content",
    })

    written = {call.args[0]: call.args[1] for call in fs.write_text.call_args_list}
    assert written == {
        ".openclaw/skills/my-skill/reference/guide.md": "guide content",
        ".openclaw/skills/my-skill/example/demo.md": "demo content",
    }


@pytest.mark.asyncio
async def test_deploy_skill_files_skips_illegal_and_empty():
    """非法路径（穿越）与空内容（二进制解码失败）跳过，不写文件。"""
    adapter = OpenClawGeneInstallAdapter()
    fs = AsyncMock()

    await adapter.deploy_skill_files(fs, "my-skill", {
        "../escape.md": "evil",
        "assets/binary.png": "",
        "reference/ok.md": "ok",
    })

    written_paths = [call.args[0] for call in fs.write_text.call_args_list]
    assert written_paths == [".openclaw/skills/my-skill/reference/ok.md"]


@pytest.mark.asyncio
async def test_deploy_skill_files_empty_dict_noop():
    """空文件字典不产生任何写入。"""
    adapter = OpenClawGeneInstallAdapter()
    fs = AsyncMock()

    await adapter.deploy_skill_files(fs, "my-skill", {})

    fs.write_text.assert_not_called()


# ── _apply_manifest_actions ────────────────────


def _make_adapter() -> MagicMock:
    adapter = MagicMock()
    adapter.apply_config = AsyncMock()
    adapter.allow_tools = AsyncMock()
    adapter.deploy_scripts = AsyncMock()
    adapter.deploy_skill_files = AsyncMock()
    return adapter


@pytest.mark.asyncio
async def test_apply_manifest_actions_deploys_assets_and_references():
    """manifest 中 assets + references 合并后通过 deploy_skill_files 部署。"""
    from app.services.gene_service import _apply_manifest_actions

    fs = AsyncMock()
    adapter = _make_adapter()
    manifest = {
        "skill": {"name": "my-skill", "content": "..."},
        "assets": {"example/demo.md": "demo"},
        "references": {"reference/guide.md": "guide"},
    }

    await _apply_manifest_actions(fs, manifest, adapter, "my-skill")

    adapter.deploy_skill_files.assert_awaited_once_with(fs, "my-skill", {
        "example/demo.md": "demo",
        "reference/guide.md": "guide",
    })


@pytest.mark.asyncio
async def test_apply_manifest_actions_without_skill_name_skips_files():
    """未提供 skill_name（旧调用方式）时不部署附属文件。"""
    from app.services.gene_service import _apply_manifest_actions

    fs = AsyncMock()
    adapter = _make_adapter()
    manifest = {"assets": {"a.md": "x"}, "references": {"reference/b.md": "y"}}

    await _apply_manifest_actions(fs, manifest, adapter)

    adapter.deploy_skill_files.assert_not_awaited()


@pytest.mark.asyncio
async def test_apply_manifest_actions_no_extra_files_skips_call():
    """manifest 无 assets/references 时不调用 deploy_skill_files。"""
    from app.services.gene_service import _apply_manifest_actions

    fs = AsyncMock()
    adapter = _make_adapter()

    await _apply_manifest_actions(fs, {"skill": {"name": "s"}}, adapter, "s")

    adapter.deploy_skill_files.assert_not_awaited()
