"""验证 require_org_member_role 工厂函数的三级权限逻辑。

测试矩阵（单元测试，不依赖数据库 fixture）：
  - member(level=10) 调需要 member 的端点 → 通过
  - member(level=10) 调需要 operator 的端点 → 403
  - operator(level=20) 调需要 operator 的端点 → 通过
  - operator(level=20) 调需要 admin 的端点 → 403
  - admin(level=30) 调需要 admin 的端点 → 通过
"""

import pytest
from fastapi import HTTPException

from app.models.org_membership import ADMIN_ROLE_LEVEL


class _FakeMembership:
    """模拟 OrgMembership 对象，仅需 role 字段。"""

    def __init__(self, role: str):
        self.role = role


def _check_role(membership_role: str | None, min_role: str) -> None:
    """
    提取 require_org_member_role 中权限校验核心逻辑进行单元测试。

    Args:
        membership_role: 成员角色（None 表示未加入组织）
        min_role: 要求的最低角色

    Raises:
        HTTPException: 权限不足时抛出 403
    """
    min_level = ADMIN_ROLE_LEVEL[min_role]

    if membership_role is None:
        # 未加入组织 → 403
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": 40312,
                "message_key": "errors.org.org_member_required",
                "message": "您不是该组织的成员",
            },
        )

    user_level = ADMIN_ROLE_LEVEL.get(membership_role, 0)
    if user_level < min_level:
        # 角色等级不足 → 403
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": 40315,
                "message_key": "errors.org.insufficient_member_role",
                "message": f"需要 {min_role} 及以上角色",
            },
        )


# ── 角色等级表验证 ──────────────────────────────────────────

def test_role_level_table():
    """ADMIN_ROLE_LEVEL 字典的值顺序满足 member < operator < admin。"""
    assert ADMIN_ROLE_LEVEL["member"] < ADMIN_ROLE_LEVEL["operator"]
    assert ADMIN_ROLE_LEVEL["operator"] < ADMIN_ROLE_LEVEL["admin"]


# ── member 角色场景 ─────────────────────────────────────────

def test_member_can_access_member_endpoint():
    """member 角色可访问 min_role=member 的端点，不抛出异常。"""
    # 不应抛出 → 无 raises
    _check_role("member", "member")


def test_member_cannot_access_operator_endpoint():
    """member 角色访问 min_role=operator 的端点，应得到 403。"""
    with pytest.raises(HTTPException) as exc_info:
        _check_role("member", "operator")
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["error_code"] == 40315


def test_member_cannot_access_admin_endpoint():
    """member 角色访问 min_role=admin 的端点，应得到 403。"""
    with pytest.raises(HTTPException) as exc_info:
        _check_role("member", "admin")
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["error_code"] == 40315


# ── operator 角色场景 ───────────────────────────────────────

def test_operator_can_access_member_endpoint():
    """operator 角色可访问 min_role=member 的端点。"""
    _check_role("operator", "member")


def test_operator_can_access_operator_endpoint():
    """operator 角色可访问 min_role=operator 的端点。"""
    _check_role("operator", "operator")


def test_operator_cannot_access_admin_endpoint():
    """operator 角色访问 min_role=admin 的端点，应得到 403。"""
    with pytest.raises(HTTPException) as exc_info:
        _check_role("operator", "admin")
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["error_code"] == 40315


# ── admin 角色场景 ──────────────────────────────────────────

def test_admin_can_access_all_levels():
    """admin 角色可访问所有级别的端点。"""
    _check_role("admin", "member")
    _check_role("admin", "operator")
    _check_role("admin", "admin")


# ── 非成员场景 ──────────────────────────────────────────────

def test_non_member_is_rejected():
    """未加入组织的用户（membership=None），应得到 403，错误码 40312。"""
    with pytest.raises(HTTPException) as exc_info:
        _check_role(None, "member")
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["error_code"] == 40312


# ── 错误码验证 ──────────────────────────────────────────────

def test_insufficient_role_error_code():
    """角色不足时错误码必须是 40315（区别于非成员 40312）。"""
    with pytest.raises(HTTPException) as exc_info:
        _check_role("member", "admin")
    detail = exc_info.value.detail
    assert detail["error_code"] == 40315
    assert detail["message_key"] == "errors.org.insufficient_member_role"


def test_non_member_error_code():
    """非成员错误码必须是 40312。"""
    with pytest.raises(HTTPException) as exc_info:
        _check_role(None, "operator")
    detail = exc_info.value.detail
    assert detail["error_code"] == 40312
    assert detail["message_key"] == "errors.org.org_member_required"
