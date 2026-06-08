"""验证 org_join_request_service 的关键流程：提交、撤回、审核、scoping。

测试风格参考 tests/test_gene_target_fork_review.py：全部 mock，不依赖真实 DB。
对返回身份注入字段（requester_name 等）通过 monkeypatch `_attach_identity` 简化为
直通，专注于流程控制与权限判断。
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.models.org_join_request import OrgJoinRequestStatus
from app.services import org_join_request_service as svc


# ─── 公共 fixtures / 工具 ────────────────────────────────────


class _FakeUser:
    """最小化的用户对象，模仿 User ORM 实例。"""

    def __init__(self, user_id: str, *, is_super_admin: bool = False):
        self.id = user_id
        self.is_super_admin = is_super_admin


class _FakeOrg:
    """最小化的组织对象。"""

    def __init__(
        self,
        org_id: str = "org-1",
        slug: str = "team-alpha",
        is_active: bool = True,
    ):
        self.id = org_id
        self.slug = slug
        self.name = f"name-{org_id}"
        self.is_active = is_active


class _FakeJoinRequest:
    """最小化的 OrgJoinRequest 对象，模仿 ORM 实例的可写属性。"""

    def __init__(
        self,
        req_id: str = "jr-1",
        user_id: str = "u-applicant",
        org_id: str = "org-1",
        status: str = OrgJoinRequestStatus.pending,
        reason: str | None = None,
    ):
        self.id = req_id
        self.user_id = user_id
        self.org_id = org_id
        self.status = status
        self.reason = reason
        self.reviewed_by = None
        self.reviewed_at = None
        self.review_note = None
        self.deleted_at = None
        # JoinRequestInfo schema 要求 created_at 是真实 datetime
        self.created_at = datetime.now(timezone.utc)

    def soft_delete(self):
        # 模仿 BaseModel.soft_delete 行为，写入一个非空值即可
        self.deleted_at = "now"


@pytest.fixture
def stub_attach_identity(monkeypatch):
    """将 _attach_identity 替换为直接返回 JoinRequestInfo 的简化版本，
    避免每个测试都得 mock User/Organization 批量查询。"""
    from app.schemas.org_join_request import JoinRequestInfo

    async def _fake(_db, items):
        result = []
        for it in items:
            # ORM 实例在 mock 环境下 id default lambda 不会触发，兜底给个 uuid
            import uuid as _uuid
            result.append(JoinRequestInfo(
                id=getattr(it, "id", None) or str(_uuid.uuid4()),
                user_id=it.user_id,
                org_id=it.org_id,
                reason=getattr(it, "reason", None),
                status=it.status,
                reviewed_by=getattr(it, "reviewed_by", None),
                reviewed_at=getattr(it, "reviewed_at", None),
                review_note=getattr(it, "review_note", None),
                created_at=getattr(it, "created_at", None) or datetime.now(timezone.utc),
            ))
        return result

    monkeypatch.setattr(svc, "_attach_identity", _fake)


@pytest.fixture
def stub_hooks(monkeypatch):
    """让 hooks.emit / member_hook.on_member_joined 不抛错。"""
    async def _noop(*_a, **_kw):
        return None

    monkeypatch.setattr(svc.hooks, "emit", _noop)

    class _FakeProvider:
        async def on_member_joined(self, *_a, **_kw):
            return None

    monkeypatch.setattr(svc, "get_member_hook", lambda: _FakeProvider())


# ─── create_join_request ─────────────────────────────────────


def _mk_create_db(
    *,
    org: _FakeOrg | None,
    existing_member: object | None = None,
    existing_pending: object | None = None,
) -> AsyncMock:
    """create_join_request 的 execute 顺序：
      1. select Organization by slug（.scalars().first()）
      2. select OrgMembership 现有成员（.scalar_one_or_none()）
      3. select OrgJoinRequest 现有 pending（.scalar_one_or_none()）
    """
    db = AsyncMock()

    # 1. org by slug → scalars().first()
    org_res = MagicMock()
    org_scalars = MagicMock()
    org_scalars.first.return_value = org
    org_res.scalars.return_value = org_scalars

    # 2. membership
    member_res = MagicMock()
    member_res.scalar_one_or_none.return_value = existing_member

    # 3. existing pending
    pending_res = MagicMock()
    pending_res.scalar_one_or_none.return_value = existing_pending

    db.execute = AsyncMock(side_effect=[org_res, member_res, pending_res])
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_create_join_request_happy_path(stub_attach_identity, stub_hooks):
    """正常路径：slug 命中 → 非成员 → 无 pending → 成功创建。"""
    org = _FakeOrg(org_id="org-1", slug="team-alpha", is_active=True)
    db = _mk_create_db(org=org)
    user = _FakeUser("u-applicant")

    result = await svc.create_join_request(db, user=user, org_slug="team-alpha", reason="想加入")

    assert result.user_id == "u-applicant"
    assert result.org_id == "org-1"
    assert result.status == OrgJoinRequestStatus.pending
    db.add.assert_called_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_join_request_empty_slug(stub_attach_identity):
    """空 slug → 400。"""
    db = AsyncMock()
    user = _FakeUser("u-applicant")
    with pytest.raises(HTTPException) as exc:
        await svc.create_join_request(db, user=user, org_slug="   ", reason=None)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_create_join_request_org_not_found(stub_attach_identity):
    """slug 查不到组织 → 404。"""
    db = _mk_create_db(org=None)
    user = _FakeUser("u-applicant")
    with pytest.raises(HTTPException) as exc:
        await svc.create_join_request(db, user=user, org_slug="ghost", reason=None)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_join_request_org_inactive(stub_attach_identity):
    """组织停用 → 403。"""
    org = _FakeOrg(is_active=False)
    db = _mk_create_db(org=org)
    user = _FakeUser("u-applicant")
    with pytest.raises(HTTPException) as exc:
        await svc.create_join_request(db, user=user, org_slug="team-alpha", reason=None)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_create_join_request_already_member(stub_attach_identity):
    """已是该组织成员 → 409。"""
    org = _FakeOrg()
    fake_member = MagicMock()
    db = _mk_create_db(org=org, existing_member=fake_member)
    user = _FakeUser("u-applicant")
    with pytest.raises(HTTPException) as exc:
        await svc.create_join_request(db, user=user, org_slug="team-alpha", reason=None)
    assert exc.value.status_code == 409
    assert exc.value.detail["error_code"] == 40940


@pytest.mark.asyncio
async def test_create_join_request_already_pending(stub_attach_identity):
    """已有 pending 申请 → 409，避免重复打扰审核者。"""
    org = _FakeOrg()
    fake_pending = MagicMock()
    db = _mk_create_db(org=org, existing_pending=fake_pending)
    user = _FakeUser("u-applicant")
    with pytest.raises(HTTPException) as exc:
        await svc.create_join_request(db, user=user, org_slug="team-alpha", reason=None)
    assert exc.value.status_code == 409
    assert exc.value.detail["error_code"] == 40941


# ─── cancel_my_join_request ──────────────────────────────────


def _mk_cancel_db(req: _FakeJoinRequest | None) -> AsyncMock:
    """cancel：仅 1 次 execute 查申请本身。"""
    db = AsyncMock()
    res = MagicMock()
    res.scalar_one_or_none.return_value = req
    db.execute = AsyncMock(return_value=res)
    db.commit = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_cancel_my_join_request_owner_success(stub_hooks):
    """本人撤回 pending 申请：状态置 cancelled、软删。"""
    req = _FakeJoinRequest(user_id="u-applicant", status=OrgJoinRequestStatus.pending)
    db = _mk_cancel_db(req)
    user = _FakeUser("u-applicant")

    await svc.cancel_my_join_request(db, user, "jr-1")

    assert req.status == OrgJoinRequestStatus.cancelled
    assert req.deleted_at is not None
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancel_my_join_request_not_found():
    """申请不存在 → 404。"""
    db = _mk_cancel_db(None)
    user = _FakeUser("u-applicant")
    with pytest.raises(HTTPException) as exc:
        await svc.cancel_my_join_request(db, user, "missing")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_cancel_my_join_request_not_owner():
    """非本人 → 403。"""
    req = _FakeJoinRequest(user_id="u-other", status=OrgJoinRequestStatus.pending)
    db = _mk_cancel_db(req)
    user = _FakeUser("u-applicant")
    with pytest.raises(HTTPException) as exc:
        await svc.cancel_my_join_request(db, user, "jr-1")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_cancel_my_join_request_not_pending():
    """已完结的申请 → 409。"""
    req = _FakeJoinRequest(user_id="u-applicant", status=OrgJoinRequestStatus.approved)
    db = _mk_cancel_db(req)
    user = _FakeUser("u-applicant")
    with pytest.raises(HTTPException) as exc:
        await svc.cancel_my_join_request(db, user, "jr-1")
    assert exc.value.status_code == 409


# ─── list_pending_for_reviewer ───────────────────────────────


def _mk_listing_db(items: list, *, admin_org_ids: list[str] | None = None) -> AsyncMock:
    """list_pending_for_reviewer 的 execute 顺序：
    - 超管路径：仅 1 次 execute（pending 列表 scalars().all()）
    - admin 路径：先查 admin 的 org_id 集合 .all()，再查 pending
    - 普通用户路径：仅查 admin org_id 集合（返回空）→ 提前 return
    """
    db = AsyncMock()
    list_res = MagicMock()
    list_scalars = MagicMock()
    list_scalars.all.return_value = items
    list_res.scalars.return_value = list_scalars

    if admin_org_ids is None:
        db.execute = AsyncMock(return_value=list_res)
    else:
        org_res = MagicMock()
        org_res.all.return_value = [(oid,) for oid in admin_org_ids]
        if not admin_org_ids:
            # 空集合时 service 不会再查 pending list
            db.execute = AsyncMock(return_value=org_res)
        else:
            db.execute = AsyncMock(side_effect=[org_res, list_res])
    return db


@pytest.mark.asyncio
async def test_list_pending_super_admin_sees_all(stub_attach_identity):
    """超管：直接拿全部 pending 列表，不再查 OrgMembership。"""
    items = [_FakeJoinRequest(req_id="jr-1"), _FakeJoinRequest(req_id="jr-2")]
    db = _mk_listing_db(items)
    user = _FakeUser("u-super", is_super_admin=True)

    result = await svc.list_pending_for_reviewer(db, user)
    assert len(result) == 2
    assert db.execute.await_count == 1


@pytest.mark.asyncio
async def test_list_pending_org_admin_scoped(stub_attach_identity):
    """组织 admin：仅返回其管理的 org 下的 pending。"""
    items = [_FakeJoinRequest(req_id="jr-1", org_id="org-A")]
    db = _mk_listing_db(items, admin_org_ids=["org-A"])
    user = _FakeUser("u-admin")

    result = await svc.list_pending_for_reviewer(db, user)
    assert len(result) == 1
    assert db.execute.await_count == 2  # 一次查 admin org_id，一次查 pending


@pytest.mark.asyncio
async def test_list_pending_normal_user_empty(stub_attach_identity):
    """非超管 + 非任何 org admin → 空列表，提前 return（仅查一次 org_id）。"""
    db = _mk_listing_db([], admin_org_ids=[])
    user = _FakeUser("u-normal")

    result = await svc.list_pending_for_reviewer(db, user)
    assert result == []
    assert db.execute.await_count == 1


# ─── review_join_request ─────────────────────────────────────


def _mk_review_db(
    req: _FakeJoinRequest | None,
    *,
    is_org_admin_membership=None,
    target_org: _FakeOrg | None = None,
    existing_member: object | None = None,
    is_super: bool = False,
) -> AsyncMock:
    """review_join_request 的 execute 顺序（非超管 + approve 路径完整）：
      1. select OrgJoinRequest by id
      2. _is_org_admin：select OrgMembership（仅非超管时）
      3. select Organization（仅 approve）
      4. 幂等成员检查：select OrgMembership（仅 approve）
    """
    db = AsyncMock()
    side_effects = []

    # 1. 申请本体
    req_res = MagicMock()
    req_res.scalar_one_or_none.return_value = req
    side_effects.append(req_res)

    # 2. _is_org_admin（仅非超管）
    if not is_super:
        admin_res = MagicMock()
        admin_res.scalar_one_or_none.return_value = is_org_admin_membership
        side_effects.append(admin_res)

    # 3 & 4 仅在 approve 路径下才会被消费；为了避免 side_effect 过度消耗，
    # 这里始终 append，由具体测试控制是否调用到 approve。
    org_res = MagicMock()
    org_res.scalar_one_or_none.return_value = target_org
    side_effects.append(org_res)

    member_res = MagicMock()
    member_res.scalar_one_or_none.return_value = existing_member
    side_effects.append(member_res)

    db.execute = AsyncMock(side_effect=side_effects)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_review_join_request_approve_by_org_admin(stub_attach_identity, stub_hooks):
    """组织 admin approve pending → 创建 OrgMembership，状态置 approved。"""
    req = _FakeJoinRequest(user_id="u-applicant", org_id="org-1")
    org = _FakeOrg(org_id="org-1", is_active=True)
    db = _mk_review_db(
        req,
        is_org_admin_membership=MagicMock(),
        target_org=org,
        existing_member=None,
    )
    reviewer = _FakeUser("u-admin")

    result = await svc.review_join_request(db, reviewer, "jr-1", "approve", note=None)

    assert result.status == OrgJoinRequestStatus.approved
    assert req.reviewed_by == "u-admin"
    db.add.assert_called_once()  # 新建 OrgMembership


@pytest.mark.asyncio
async def test_review_join_request_approve_idempotent_when_already_member(
    stub_attach_identity, stub_hooks,
):
    """并发场景：用户已经是该组织成员 → 不重复 insert，但状态仍置 approved。"""
    req = _FakeJoinRequest()
    org = _FakeOrg(is_active=True)
    db = _mk_review_db(
        req,
        is_org_admin_membership=MagicMock(),
        target_org=org,
        existing_member=MagicMock(),  # 已是成员
    )
    reviewer = _FakeUser("u-admin")

    result = await svc.review_join_request(db, reviewer, "jr-1", "approve", note=None)
    assert result.status == OrgJoinRequestStatus.approved
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_review_join_request_approve_org_inactive(stub_attach_identity, stub_hooks):
    """approve 时目标组织已停用 → 403。"""
    req = _FakeJoinRequest()
    org = _FakeOrg(is_active=False)
    db = _mk_review_db(
        req,
        is_org_admin_membership=MagicMock(),
        target_org=org,
    )
    reviewer = _FakeUser("u-admin")
    with pytest.raises(HTTPException) as exc:
        await svc.review_join_request(db, reviewer, "jr-1", "approve", note=None)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_review_join_request_reject_by_org_admin(stub_attach_identity, stub_hooks):
    """reject 路径：仅状态变化，不创建 OrgMembership，不触发 hook。"""
    req = _FakeJoinRequest()
    db = _mk_review_db(req, is_org_admin_membership=MagicMock())
    reviewer = _FakeUser("u-admin")

    result = await svc.review_join_request(db, reviewer, "jr-1", "reject", note="原因")
    assert result.status == OrgJoinRequestStatus.rejected
    assert req.review_note == "原因"
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_review_join_request_not_org_admin(stub_attach_identity):
    """非该 org 的 admin、非超管 → 403。"""
    req = _FakeJoinRequest()
    db = _mk_review_db(req, is_org_admin_membership=None)
    reviewer = _FakeUser("u-rando")
    with pytest.raises(HTTPException) as exc:
        await svc.review_join_request(db, reviewer, "jr-1", "approve", note=None)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_review_join_request_not_pending(stub_attach_identity):
    """已完结的申请 → 409，不允许重复审核。"""
    req = _FakeJoinRequest(status=OrgJoinRequestStatus.approved)
    db = _mk_review_db(req, is_org_admin_membership=MagicMock())
    reviewer = _FakeUser("u-admin")
    with pytest.raises(HTTPException) as exc:
        await svc.review_join_request(db, reviewer, "jr-1", "approve", note=None)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_review_join_request_invalid_action(stub_attach_identity):
    """非 approve/reject 的 action → 400。"""
    db = AsyncMock()
    reviewer = _FakeUser("u-admin")
    with pytest.raises(HTTPException) as exc:
        await svc.review_join_request(db, reviewer, "jr-1", "delete", note=None)
    assert exc.value.status_code == 400
