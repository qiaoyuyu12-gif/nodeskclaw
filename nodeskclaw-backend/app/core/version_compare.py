"""nodeskclaw-backend/app/core/version_compare.py

语义化版本号解析与比较工具。只识别 "X.Y.Z" 前缀（X/Y/Z 为非负整数），
不支持 pre-release/build metadata 后缀，够用即可。
"""

from __future__ import annotations

import re

_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def parse_version(version: str) -> tuple[int, int, int] | None:
    """解析 "X.Y.Z" 版本号为 (major, minor, patch) 整数元组。

    不合法格式返回 None，调用方自行决定降级策略：写入路径应该直接拒绝，
    读取路径应该跳过比较，不能装作知道谁新谁旧。
    """
    match = _SEMVER_RE.match(version.strip())
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def compare_versions(a: str, b: str) -> int | None:
    """比较两个版本号。a 更新返回 1，b 更新返回 -1，相等返回 0；

    任一个解析失败返回 None（调用方不能把 None 当成"相等"处理）。
    """
    parsed_a = parse_version(a)
    parsed_b = parse_version(b)
    if parsed_a is None or parsed_b is None:
        return None
    if parsed_a == parsed_b:
        return 0
    return 1 if parsed_a > parsed_b else -1
