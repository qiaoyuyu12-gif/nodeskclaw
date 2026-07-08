"""验证 channel 插件包解压时对 zip-slip / .. 路径穿越的拦截。

背景：`_extract_tgz`/`_extract_zip` 曾经只去掉压缩包内的第一层目录名，
不校验剩余路径是否含 `..`，恶意压缩包可借此把文件写穿到目标实例根目录之外。
"""

from __future__ import annotations

import io
import tarfile
import zipfile

import pytest

from app.api.channel_configs import _extract_tgz, _extract_zip


def _make_zip(entries: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


def _make_tgz(entries: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, content in entries.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_extract_zip_rejects_dotdot_traversal():
    payload = _make_zip({"plugin/../../../../etc/cron.d/evil": "* * * * * root touch /tmp/pwned"})
    with pytest.raises(ValueError):
        _extract_zip(payload)


def test_extract_tgz_rejects_dotdot_traversal():
    payload = _make_tgz({"plugin/../../../../etc/cron.d/evil": "* * * * * root touch /tmp/pwned"})
    with pytest.raises(ValueError):
        _extract_tgz(payload)


def test_extract_zip_accepts_normal_paths():
    payload = _make_zip({
        "plugin/openclaw.plugin.json": '{"channels": ["demo"]}',
        "plugin/index.js": "module.exports = {};",
    })
    files, plugin_id = _extract_zip(payload)
    assert files["openclaw.plugin.json"] == '{"channels": ["demo"]}'
    assert files["index.js"] == "module.exports = {};"
    assert plugin_id == "demo"


def test_extract_tgz_accepts_normal_paths():
    payload = _make_tgz({
        "plugin/openclaw.plugin.json": '{"channels": ["demo"]}',
        "plugin/index.js": "module.exports = {};",
    })
    files, plugin_id = _extract_tgz(payload)
    assert files["openclaw.plugin.json"] == '{"channels": ["demo"]}'
    assert files["index.js"] == "module.exports = {};"
    assert plugin_id == "demo"
