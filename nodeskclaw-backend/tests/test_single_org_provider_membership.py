"""验证 SingleOrgProvider 严格按 OrgMembership 校验 current_org_id 的行为。

回归 bug：当 user.current_org_id 指向用户不再是 member 的 org 时，旧实现直接
返回该 org，导致组织信息错位、人类成员列表 403。新实现应：
1. current_org_id 在 OrgMembership 中找得到 → 返回该 org
2. current_org_id 找不到（已不是 member）→ 回退到 user 实际归属的首个 org
3. 用户完全没有 OrgMembership → 走 _get_or_create_default 兜底
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.org.single_org import SingleOrgProvider


class _FakeUser:
    def __init__(self, user_id: str, current_org_id: str | None = None):
        self.id = user_id
        self.current_org_id = current_org_id


class _FakeOrg:
    def __init__(self, org_id: str, name: str = ""):
        self.id = org_id
        self.name = name


@pytest.mark.asyncio
async def test_resolve_returns_org_when_user_is_member():
    """current_org_id 指向用户实际归属的 org → 直接返回。"""
    provider = SingleOrgProvider()
    db = AsyncMock()
    target = _FakeOrg("org-A", "信息化")

    # _get_org_if_member 的 join 查询命中
    res = MagicMock()
    scalars = MagicMock()
    scalars.first.return_value = target
    res.scalars.return_value = scalars
    db.execute = AsyncMock(return_value=res)

    user = _FakeUser("u-1", current_org_id="org-A")
    org = await provider.resolve_org_for_user(user, db)
    assert org is target
    # 仅一次 SQL：成员校验直接命中
    assert db.execute.await_count == 1


@pytest.mark.asyncio
async def test_resolve_falls_back_when_user_not_member_of_current_org():
    """current_org_id 指向用户不再归属的 org → 回退到 OrgMembership 实际归属的首个。"""
    provider = SingleOrgProvider()
    actual = _FakeOrg("org-REAL", "信息化")

    db = AsyncMock()

    # 第 1 次 execute：_get_org_if_member 查不到（不是成员）
    miss = MagicMock()
    miss_scalars = MagicMock()
    miss_scalars.first.return_value = None
    miss.scalars.return_value = miss_scalars

    # 第 2 次 execute：_resolve_first_membership_org 找到实际归属
    hit = MagicMock()
    hit_scalars = MagicMock()
    hit_scalars.first.return_value = actual
    hit.scalars.return_value = hit_scalars

    db.execute = AsyncMock(side_effect=[miss, hit])
    db.commit = AsyncMock()

    user = _FakeUser("u-1", current_org_id="org-STALE")
    org = await provider.resolve_org_for_user(user, db)
    assert org is actual
    # current_org_id 已被修正
    assert user.current_org_id == "org-REAL"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_resolve_user_without_current_org_uses_membership():
    """user.current_org_id 为空 + 有 OrgMembership → 取实际归属的首个 org 并设回 user。"""
    provider = SingleOrgProvider()
    actual = _FakeOrg("org-REAL")

    db = AsyncMock()
    # 跳过 _get_org_if_member（current_org_id 为 None），直接查实际归属
    hit = MagicMock()
    hit_scalars = MagicMock()
    hit_scalars.first.return_value = actual
    hit.scalars.return_value = hit_scalars
    db.execute = AsyncMock(return_value=hit)
    db.commit = AsyncMock()

    user = _FakeUser("u-1", current_org_id=None)
    org = await provider.resolve_org_for_user(user, db)
    assert org is actual
    assert user.current_org_id == "org-REAL"


@pytest.mark.asyncio
async def test_resolve_user_without_any_membership_falls_back_to_default():
    """用户完全无 OrgMembership：走 _get_or_create_default 兜底。"""
    provider = SingleOrgProvider()
    fallback = _FakeOrg("org-DEFAULT", "Default")

    db = AsyncMock()
    # 第 1 次 execute：_get_org_if_member 查不到
    miss1 = MagicMock()
    miss1_scalars = MagicMock()
    miss1_scalars.first.return_value = None
    miss1.scalars.return_value = miss1_scalars

    # 第 2 次 execute：_resolve_first_membership_org 也查不到
    miss2 = MagicMock()
    miss2_scalars = MagicMock()
    miss2_scalars.first.return_value = None
    miss2.scalars.return_value = miss2_scalars

    # 第 3 次 execute：_get_or_create_default 取首个活跃 org
    hit = MagicMock()
    hit.scalar_one_or_none.return_value = fallback
    db.execute = AsyncMock(side_effect=[miss1, miss2, hit])

    user = _FakeUser("u-ghost", current_org_id="org-STALE")
    org = await provider.resolve_org_for_user(user, db)
    assert org is fallback
