"""RBAC 进程内 LRU + TTL 缓存。

第一期保持简单：使用 Python 标准库 OrderedDict 实现 LRU；过期由读时检查驱动，
不引入后台清理协程。每个 Uvicorn worker 各持一份本地缓存，TTL 默认 60s
（可通过 settings.RBAC_CACHE_TTL_SECONDS 调整）。

缓存键：(subject_type, subject_id)
缓存值：[(role_key, scope_type, scope_id), ...] —— 主体已被授予的全部角色

grant_role / revoke_role 时必须调用 invalidate_subject(...)，否则 TTL 内
权限变更不可见。第三期可平滑替换为 Redis 共享缓存。
"""

import time
from collections import OrderedDict
from typing import Final

from app.core.config import settings

# 进程内缓存最大条目数；超出按 LRU 淘汰
_MAX_ENTRIES: Final[int] = 4096

# (subject_type, subject_id) -> (timestamp_monotonic, [(role_key, scope_type, scope_id), ...])
_store: "OrderedDict[tuple[str, str], tuple[float, list[tuple[str, str, str | None]]]]" = (
    OrderedDict()
)


def _ttl_seconds() -> int:
    """读取配置 TTL；运行期可热修改 settings 来调整。"""
    return max(1, int(settings.RBAC_CACHE_TTL_SECONDS))


def get_cached_grants(
    subject_type: str, subject_id: str,
) -> list[tuple[str, str, str | None]] | None:
    """获取主体的角色授权缓存，未命中或过期返回 None。"""
    key = (subject_type, subject_id)
    item = _store.get(key)
    if item is None:
        return None
    ts, grants = item
    if time.monotonic() - ts > _ttl_seconds():
        # 过期清理，回退到 DB 重新加载
        _store.pop(key, None)
        return None
    # 命中后移到 LRU 末尾（最近使用）
    _store.move_to_end(key)
    return grants


def set_cached_grants(
    subject_type: str, subject_id: str,
    grants: list[tuple[str, str, str | None]],
) -> None:
    """写入主体的角色授权缓存；超容时弹出最久未用条目。"""
    key = (subject_type, subject_id)
    _store[key] = (time.monotonic(), grants)
    _store.move_to_end(key)
    if len(_store) > _MAX_ENTRIES:
        _store.popitem(last=False)


def invalidate_subject(subject_type: str, subject_id: str) -> None:
    """主动失效主体缓存。grant_role / revoke_role 写入旧字段时务必调用。"""
    _store.pop((subject_type, subject_id), None)


def clear_all_caches() -> None:
    """清空进程内全部缓存。仅用于测试或紧急排障。"""
    _store.clear()
