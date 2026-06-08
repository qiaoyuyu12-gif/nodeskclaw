"""验证 org_leave_request_service 的关键流程：提交、撤回、审核、自审与唯一 admin 守卫。

测试风格与 test_org_join_request.py 对齐：全部 mock，不依赖真实 DB。
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.models.org_leave_request import OrgLeaveRequestStatus
from app.models.org_membership import OrgRole
from app.services import org_leave_request_service as svc


# ─── 公共 stubs ──────────────────────────────────────────────


class _FakeUser:
    def __init__(self, user_id: str, *, is_super_admin: bool = False):
        self.id = user_id
        self.is_super_admin = is_super_admin


class _FakeOrg:
    def __init__(self, org_id: str = "org-1", is_active: bool = True):
        self.id = org_id
        self.is_active = is_active


class _FakeMember:
    """模仿 OrgMembership，仅暴露 role + soft_delete。"""

    def __init__(self, role: str = OrgRole.member):
        self.role = role
        self.deleted_at = None

    def soft_delete(self):
        self.deleted_at = "now"


class _FakeLeaveRequest:
    def __init__(
        self,
        req_id: str = "lr-1",
        user_id: str = "u-applicant",
        org_id: str = "org-1",
        status: str = OrgLeaveRequestStatus.pending,
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
        self.created_at = datetime.now(timezone.utc)

    def soft_delete(self):
        self.deleted_at = "now"


@pytest.fixture
def stub_attach_identity(monkeypatch):
    """绕开 _attach_identity 的 User/Organization/OrgMembership 三次批量查询。"""
    from app.schemas.org_leave_request import LeaveRequestInfo

    async def _fake(_db, items):
        import uuid as _uuid
        return [
            LeaveRequestInfo(
                id=getattr(it, "id", None) or str(_uuid.uuid4()),
                user_id=it.user_id,
                org_id=it.org_id,
                reason=getattr(it, "reason", None),
                status=it.status,
                reviewed_by=getattr(it, "reviewed_by", None),
                reviewed_at=getattr(it, "reviewed_at", None),
                review_note=getattr(it, "review_note", None),
                created_at=getattr(it, "created_at", None) or datetime.now(timezone.utc),
            )
            for it in items
        ]

    monkeypatch.setattr(svc, "_attach_identity", _fake)


@pytest.fixture
def stub_hooks(monkeypatch):
    """让 hooks.emit / member_hook.on_member_removed 不抛错。"""
    async def _noop(*_a, **_kw):
        return None

    monkeypatch.setattr(svc.hooks, "emit", _noop)

    class _FakeProvider:
        async def on_member_removed(self, *_a, **_kw):
            return None

    monkeypatch.setattr(svc, "get_member_hook", lambda: _FakeProvider())


# ─── create_leave_request ────────────────────────────────────


def _mk_create_db(
    *,
    org: _FakeOrg | None,
    member: _FakeMember | None,
    existing_pending: object | None = None,
) -> AsyncMock:
    """create_leave_request execute 顺序：
      1. select Organization by id（scalar_one_or_none）
      2. select OrgMembership 我是否成员
      3. select OrgLeaveRequest 现有 pending
    """
    db = AsyncMock()

    org_res = MagicMock()
    org_res.scalar_one_or_none.return_value = org

    member_res = MagicMock()
    member_res.scalar_one_or_none.return_value = member

    pending_res = MagicMock()
    pending_res.scalar_one_or_none.return_value = existing_pending

    db.execute = AsyncMock(side_effect=[org_res, member_res, pending_res])
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_create_leave_request_happy_path(stub_attach_identity, stub_hooks):
    db = _mk_create_db(org=_FakeOrg(), member=_FakeMember())
    user = _FakeUser("u-applicant")
    result = await svc.create_leave_request(db, user, "org-1", "想退出")
    assert result.status == OrgLeaveRequestStatus.pending
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_create_leave_request_org_not_found(stub_attach_identity):
    db = _mk_create_db(org=None, member=None)
    user = _FakeUser("u-applicant")
    with pytest.raises(HTTPException) as exc:
        await svc.create_leave_request(db, user, "ghost", None)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_leave_request_not_member(stub_attach_identity):
    """非该组织成员不允许申请退出。"""
    db = _mk_create_db(org=_FakeOrg(), member=None)
    user = _FakeUser("u-outsider")
    with pytest.raises(HTTPException) as exc:
        await svc.create_leave_request(db, user, "org-1", None)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_create_leave_request_already_pending(stub_attach_identity):
    db = _mk_create_db(org=_FakeOrg(), member=_FakeMember(), existing_pending=MagicMock())
    user = _FakeUser("u-applicant")
    with pytest.raises(HTTPException) as exc:
        await svc.create_leave_request(db, user, "org-1", None)
    assert exc.value.status_code == 409


# ─── cancel_my_leave_request ─────────────────────────────────


def _mk_cancel_db(req: _FakeLeaveRequest | None) -> AsyncMock:
    db = AsyncMock()
    res = MagicMock()
    res.scalar_one_or_none.return_value = req
    db.execute = AsyncMock(return_value=res)
    db.commit = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_cancel_my_leave_request_owner_success(stub_hooks):
    req = _FakeLeaveRequest(user_id="u-applicant")
    db = _mk_cancel_db(req)
    await svc.cancel_my_leave_request(db, _FakeUser("u-applicant"), "lr-1")
    assert req.status == OrgLeaveRequestStatus.cancelled
    assert req.deleted_at is not None


@pytest.mark.asyncio
async def test_cancel_my_leave_request_not_found():
    db = _mk_cancel_db(None)
    with pytest.raises(HTTPException) as exc:
        await svc.cancel_my_leave_request(db, _FakeUser("u-applicant"), "missing")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_cancel_my_leave_request_not_owner():
    req = _FakeLeaveRequest(user_id="u-other")
    db = _mk_cancel_db(req)
    with pytest.raises(HTTPException) as exc:
        await svc.cancel_my_leave_request(db, _FakeUser("u-applicant"), "lr-1")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_cancel_my_leave_request_not_pending():
    req = _FakeLeaveRequest(user_id="u-applicant", status=OrgLeaveRequestStatus.approved)
    db = _mk_cancel_db(req)
    with pytest.raises(HTTPException) as exc:
        await svc.cancel_my_leave_request(db, _FakeUser("u-applicant"), "lr-1")
    assert exc.value.status_code == 409


# ─── list_pending_for_reviewer ───────────────────────────────


def _mk_listing_db(items: list, *, admin_org_ids: list[str] | None = None) -> AsyncMock:
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
            db.execute = AsyncMock(return_value=org_res)
        else:
            db.execute = AsyncMock(side_effect=[org_res, list_res])
    return db


@pytest.mark.asyncio
async def test_list_pending_super_admin_sees_all(stub_attach_identity):
    items = [_FakeLeaveRequest(req_id="lr-1"), _FakeLeaveRequest(req_id="lr-2")]
    db = _mk_listing_db(items)
    result = await svc.list_pending_for_reviewer(db, _FakeUser("u-super", is_super_admin=True))
    assert len(result) == 2
    assert db.execute.await_count == 1


@pytest.mark.asyncio
async def test_list_pending_org_admin_scoped(stub_attach_identity):
    items = [_FakeLeaveRequest(req_id="lr-1", org_id="org-A")]
    db = _mk_listing_db(items, admin_org_ids=["org-A"])
    result = await svc.list_pending_for_reviewer(db, _FakeUser("u-admin"))
    assert len(result) == 1
    assert db.execute.await_count == 2


@pytest.mark.asyncio
async def test_list_pending_normal_user_empty(stub_attach_identity):
    db = _mk_listing_db([], admin_org_ids=[])
    result = await svc.list_pending_for_reviewer(db, _FakeUser("u-normal"))
    assert result == []


# ─── review_leave_request ────────────────────────────────────


def _mk_review_db(
    req: _FakeLeaveRequest | None,
    *,
    is_org_admin_membership=None,
    leaving_member: _FakeMember | None = None,
    admin_count: int = 2,  # 默认 admin 数 ≥2，单人 admin 测试时显式传 1
    is_super: bool = False,
) -> AsyncMock:
    """review_leave_request execute 顺序：
      1. select OrgLeaveRequest by id
      2. _is_org_admin（非超管时）
      3. approve 路径：select 申请者 OrgMembership
      4. approve 路径 + 离职者是 admin：select count(admin) 检查唯一 admin
    """
    db = AsyncMock()
    side_effects = []

    req_res = MagicMock()
    req_res.scalar_one_or_none.return_value = req
    side_effects.append(req_res)

    if not is_super:
        admin_res = MagicMock()
        admin_res.scalar_one_or_none.return_value = is_org_admin_membership
        side_effects.append(admin_res)

    member_res = MagicMock()
    member_res.scalar_one_or_none.return_value = leaving_member
    side_effects.append(member_res)

    # 唯一 admin 计数：只有当 leaving_member.role == admin 才会走到这次查询
    count_res = MagicMock()
    count_res.scalar_one.return_value = admin_count
    side_effects.append(count_res)

    db.execute = AsyncMock(side_effect=side_effects)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_review_leave_approve_by_admin(stub_attach_identity, stub_hooks):
    """组织 admin approve 普通成员退出 → 软删 membership，状态 approved。"""
    req = _FakeLeaveRequest(user_id="u-leaving", org_id="org-1")
    leaving = _FakeMember(role=OrgRole.member)
    db = _mk_review_db(
        req,
        is_org_admin_membership=MagicMock(),
        leaving_member=leaving,
    )
    reviewer = _FakeUser("u-admin")

    result = await svc.review_leave_request(db, reviewer, "lr-1", "approve", None)
    assert result.status == OrgLeaveRequestStatus.approved
    assert leaving.deleted_at is not None  # membership 已软删


@pytest.mark.asyncio
async def test_review_leave_approve_last_admin_rejected(stub_attach_identity, stub_hooks):
    """唯一 admin 申请退出 → 守卫拦截，要求先转让 admin。"""
    req = _FakeLeaveRequest(user_id="u-only-admin", org_id="org-1")
    leaving = _FakeMember(role=OrgRole.admin)
    db = _mk_review_db(
        req,
        is_org_admin_membership=MagicMock(),
        leaving_member=leaving,
        admin_count=1,  # 唯一 admin
    )
    reviewer = _FakeUser("u-super", is_super_admin=True)
    # 注意：超管路径下不查 _is_org_admin，所以重新构造 db
    db2 = AsyncMock()
    req_res = MagicMock()
    req_res.scalar_one_or_none.return_value = req
    member_res = MagicMock()
    member_res.scalar_one_or_none.return_value = leaving
    count_res = MagicMock()
    count_res.scalar_one.return_value = 1
    db2.execute = AsyncMock(side_effect=[req_res, member_res, count_res])
    db2.commit = AsyncMock()
    db2.refresh = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await svc.review_leave_request(db2, reviewer, "lr-1", "approve", None)
    assert exc.value.status_code == 409
    assert exc.value.detail["error_code"] == 40952
    # 唯一 admin 守卫触发时 membership 不应被软删
    assert leaving.deleted_at is None


@pytest.mark.asyncio
async def test_review_leave_reject_no_membership_change(stub_attach_identity, stub_hooks):
    """reject 路径：不动 membership、不触发 hook、仅状态变更。"""
    req = _FakeLeaveRequest()
    db = AsyncMock()
    # reject 路径只会走前 2 次 execute（req + _is_org_admin），不查 membership
    req_res = MagicMock()
    req_res.scalar_one_or_none.return_value = req
    admin_res = MagicMock()
    admin_res.scalar_one_or_none.return_value = MagicMock()
    db.execute = AsyncMock(side_effect=[req_res, admin_res])
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    result = await svc.review_leave_request(db, _FakeUser("u-admin"), "lr-1", "reject", "原因")
    assert result.status == OrgLeaveRequestStatus.rejected
    assert req.review_note == "原因"


@pytest.mark.asyncio
async def test_review_leave_self_review_forbidden(stub_attach_identity):
    """审核者不能审核自己提交的退出申请（admin 自批自退陷阱）。"""
    req = _FakeLeaveRequest(user_id="u-admin", org_id="org-1")
    db = AsyncMock()
    req_res = MagicMock()
    req_res.scalar_one_or_none.return_value = req
    admin_res = MagicMock()
    admin_res.scalar_one_or_none.return_value = MagicMock()
    db.execute = AsyncMock(side_effect=[req_res, admin_res])
    db.commit = AsyncMock()

    reviewer = _FakeUser("u-admin")  # 申请者 == 审核者
    with pytest.raises(HTTPException) as exc:
        await svc.review_leave_request(db, reviewer, "lr-1", "approve", None)
    assert exc.value.status_code == 403
    assert exc.value.detail["error_code"] == 40353


@pytest.mark.asyncio
async def test_review_leave_not_org_admin(stub_attach_identity):
    """非该 org admin、非超管 → 403。"""
    req = _FakeLeaveRequest()
    db = AsyncMock()
    req_res = MagicMock()
    req_res.scalar_one_or_none.return_value = req
    admin_res = MagicMock()
    admin_res.scalar_one_or_none.return_value = None  # 不是 admin
    db.execute = AsyncMock(side_effect=[req_res, admin_res])

    with pytest.raises(HTTPException) as exc:
        await svc.review_leave_request(db, _FakeUser("u-rando"), "lr-1", "approve", None)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_review_leave_not_pending(stub_attach_identity):
    """已完结的申请 → 409。"""
    req = _FakeLeaveRequest(status=OrgLeaveRequestStatus.approved)
    db = AsyncMock()
    req_res = MagicMock()
    req_res.scalar_one_or_none.return_value = req
    db.execute = AsyncMock(return_value=req_res)
    with pytest.raises(HTTPException) as exc:
        await svc.review_leave_request(db, _FakeUser("u-admin"), "lr-1", "approve", None)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_review_leave_invalid_action():
    """非 approve/reject 的 action → 400，连查申请都不需要。"""
    with pytest.raises(HTTPException) as exc:
        await svc.review_leave_request(AsyncMock(), _FakeUser("u-admin"), "lr-1", "delete", None)
    assert exc.value.status_code == 400
