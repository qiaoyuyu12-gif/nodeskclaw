"""RBAC LRU + TTL 缓存行为验证。"""

import time

import pytest

from app.core.rbac.cache import (
    clear_all_caches,
    get_cached_grants,
    invalidate_subject,
    set_cached_grants,
)


def test_cache_hit_after_set():
    """set 之后立即 get 应命中。"""
    set_cached_grants("user", "u-cache-1", [("org_admin", "org", "org-1")])
    grants = get_cached_grants("user", "u-cache-1")
    assert grants == [("org_admin", "org", "org-1")]


def test_invalidate_subject_removes_entry():
    """invalidate 后 get 返回 None。"""
    set_cached_grants("user", "u-cache-2", [("org_member", "org", "org-2")])
    invalidate_subject("user", "u-cache-2")
    assert get_cached_grants("user", "u-cache-2") is None


def test_clear_all_caches():
    """clear_all_caches 清空全部缓存。"""
    set_cached_grants("user", "u-cache-3", [("a", "platform", None)])
    set_cached_grants("agent", "i-cache-3", [("b", "workspace", "w-1")])
    clear_all_caches()
    assert get_cached_grants("user", "u-cache-3") is None
    assert get_cached_grants("agent", "i-cache-3") is None


def test_cache_ttl_expiry(monkeypatch):
    """超过 TTL 后 get 返回 None。"""
    from app.core.rbac import cache as cache_mod

    # 直接 monkeypatch _ttl_seconds 返回 0，避开 cache.py 的 max(1, ...) 下限
    monkeypatch.setattr(cache_mod, "_ttl_seconds", lambda: 0)
    set_cached_grants("user", "u-cache-ttl", [("x", "org", "org-x")])
    # 让 monotonic 至少前进一帧，确保 elapsed > 0
    time.sleep(0.01)
    assert get_cached_grants("user", "u-cache-ttl") is None


def test_lru_eviction(monkeypatch):
    """超容时弹出最久未用条目。"""
    from app.core.rbac import cache as cache_mod

    # 缩小 _MAX_ENTRIES 触发 LRU 淘汰
    monkeypatch.setattr(cache_mod, "_MAX_ENTRIES", 3)
    monkeypatch.setattr(
        cache_mod.settings, "RBAC_CACHE_TTL_SECONDS", 60,
    )
    cache_mod.clear_all_caches()

    set_cached_grants("user", "u1", [("a", "platform", None)])
    set_cached_grants("user", "u2", [("b", "platform", None)])
    set_cached_grants("user", "u3", [("c", "platform", None)])
    # 此时正好满
    assert get_cached_grants("user", "u1") is not None
    # 写入第 4 个，最旧的 u2（u1 刚被命中变成最新）应被淘汰
    set_cached_grants("user", "u4", [("d", "platform", None)])

    assert get_cached_grants("user", "u2") is None
    assert get_cached_grants("user", "u1") is not None
    assert get_cached_grants("user", "u3") is not None
    assert get_cached_grants("user", "u4") is not None
