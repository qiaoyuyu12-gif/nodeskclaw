"""跨组织 gene 可见性守卫测试。

覆盖 _assert_user_can_view_gene_by_slug 的所有路径：
- super_admin 全域放行
- DB 中无 slug：远程公共仓库 skill，放行
- public：放行
- personal：仅作者可见
- org_private：仅同 org 成员可见
- 多 scope 并存：任一命中即放行
- 全部失败：403
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import ForbiddenError
from app.services import gene_service


class _FakeUser:
    def __init__(
        self,
        user_id: str,
        *,
        is_super_admin: bool = False,
        current_org_id: str | None = None,
    ):
        self.id = user_id
        self.is_super_admin = is_super_admin
        self.current_org_id = current_org_id


class _FakeGene:
    def __init__(
        self,
        *,
        visibility: str,
        org_id: str | None = None,
        created_by: str | None = None,
    ):
        self.visibility = visibility
        self.org_id = org_id
        self.created_by = created_by


def _mk_db(genes: list[_FakeGene]) -> AsyncMock:
    """构造 mock db：唯一一次 execute 返回 genes 列表。"""
    db = AsyncMock()
    res = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = genes
    res.scalars.return_value = scalars
    db.execute = AsyncMock(return_value=res)
    return db


@pytest.mark.asyncio
async def test_super_admin_bypasses_visibility_check():
    """超管不受任何限制，应在不查询 DB 的情况下直接放行。"""
    db = AsyncMock()
    user = _FakeUser("u-super", is_super_admin=True)
    await gene_service._assert_user_can_view_gene_by_slug(db, "any-slug", user)
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_unknown_slug_treated_as_remote_public():
    """DB 中无此 slug → 视为外部公共仓库 skill，放行。"""
    db = _mk_db([])
    user = _FakeUser("u-1", current_org_id="org-A")
    await gene_service._assert_user_can_view_gene_by_slug(db, "remote-skill", user)


@pytest.mark.asyncio
async def test_public_gene_allowed_for_anyone():
    """public 可见性对任何登录用户放行。"""
    db = _mk_db([_FakeGene(visibility="public", org_id="org-X")])
    user = _FakeUser("u-1", current_org_id="org-A")
    await gene_service._assert_user_can_view_gene_by_slug(db, "pub", user)


@pytest.mark.asyncio
async def test_personal_gene_allowed_for_owner():
    """personal scope 仅 owner 可见。"""
    db = _mk_db([_FakeGene(visibility="personal", created_by="u-1")])
    user = _FakeUser("u-1")
    await gene_service._assert_user_can_view_gene_by_slug(db, "my", user)


@pytest.mark.asyncio
async def test_personal_gene_denied_for_non_owner():
    """personal scope 对非 owner 拒绝。"""
    db = _mk_db([_FakeGene(visibility="personal", created_by="u-other")])
    user = _FakeUser("u-1")
    with pytest.raises(ForbiddenError):
        await gene_service._assert_user_can_view_gene_by_slug(db, "other-personal", user)


@pytest.mark.asyncio
async def test_org_private_allowed_for_same_org():
    """org_private 对同组织成员放行。"""
    db = _mk_db([_FakeGene(visibility="org_private", org_id="org-A")])
    user = _FakeUser("u-1", current_org_id="org-A")
    await gene_service._assert_user_can_view_gene_by_slug(db, "team-skill", user)


@pytest.mark.asyncio
async def test_org_private_denied_for_other_org():
    """org_private 对其他组织成员拒绝（核心隔离场景）。"""
    db = _mk_db([_FakeGene(visibility="org_private", org_id="org-A")])
    user = _FakeUser("u-1", current_org_id="org-B")
    with pytest.raises(ForbiddenError) as exc:
        await gene_service._assert_user_can_view_gene_by_slug(db, "team-skill", user)
    assert exc.value.message_key == "errors.gene.cross_org_forbidden"


@pytest.mark.asyncio
async def test_org_private_denied_when_user_has_no_org():
    """无组织用户访问任何 org_private skill 都应拒绝。"""
    db = _mk_db([_FakeGene(visibility="org_private", org_id="org-A")])
    user = _FakeUser("u-1", current_org_id=None)
    with pytest.raises(ForbiddenError):
        await gene_service._assert_user_can_view_gene_by_slug(db, "team-skill", user)


@pytest.mark.asyncio
async def test_multiple_scopes_any_hit_allows():
    """fork 三向架构下同 slug 多 scope 并存，任一可见即放行。
    例：自己 fork 了 public 副本到 personal → 仍可看；另有别人 org 的 org_private 不影响。"""
    db = _mk_db([
        _FakeGene(visibility="org_private", org_id="org-OTHER"),  # 别组的，不可见
        _FakeGene(visibility="personal", created_by="u-1"),       # 自己的，可见
    ])
    user = _FakeUser("u-1", current_org_id="org-MINE")
    await gene_service._assert_user_can_view_gene_by_slug(db, "dup", user)


@pytest.mark.asyncio
async def test_all_scopes_invisible_denied():
    """同 slug 多条全部不属于当前用户 → 拒绝。"""
    db = _mk_db([
        _FakeGene(visibility="org_private", org_id="org-A"),
        _FakeGene(visibility="personal", created_by="u-someone-else"),
    ])
    user = _FakeUser("u-1", current_org_id="org-B")
    with pytest.raises(ForbiddenError):
        await gene_service._assert_user_can_view_gene_by_slug(db, "dup", user)
