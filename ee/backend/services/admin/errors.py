"""超管 admin 域错误码与异常工厂。

设计参考 docs/superpowers/specs/2026-05-26-super-admin-features-design.md §5.0。
所有 admin endpoint 失败统一抛 HTTPException(409)，前端按 message_key 显示本地化提示。
"""

from __future__ import annotations

from enum import IntEnum

from fastapi import HTTPException, status


class AdminErrorCode(IntEnum):
    """错误码段位：
      40901–40919 自我保护类
      40920–40939 组织管理类
      40940–40959 用户管理类
      40960–40979 Feature override 类
      40980–40999 审计类
    """

    # 自我保护
    SELF_DEACTIVATE_FORBIDDEN = 40901
    SELF_DEMOTE_SUPER_ADMIN_FORBIDDEN = 40902
    SELF_DELETE_FORBIDDEN = 40903
    LAST_SUPER_ADMIN_FORBIDDEN = 40904

    # 组织
    ORG_SLUG_CONFLICT = 40920
    ORG_HAS_RUNNING_INSTANCES = 40921
    ORG_LAST_ADMIN_FORBIDDEN = 40922
    ORG_NOT_FOUND = 40923
    ORG_MEMBER_DUPLICATE = 40924
    ORG_MEMBER_NOT_FOUND = 40925  # 组织成员不存在

    # 用户
    USER_NOT_FOUND = 40940
    USER_EMAIL_CONFLICT = 40941
    USER_ALREADY_DELETED = 40942

    # Feature override
    FEATURE_ID_UNKNOWN = 40960
    FEATURE_OVERRIDE_NOT_FOUND = 40961

    # 审计
    AUDIT_ACTION_INVALID = 40980
    AUDIT_TIME_RANGE_INVALID = 40981


def raise_admin_error(code: AdminErrorCode, *, message_key: str, message: str) -> None:
    """统一错误抛出（409 Conflict）。所有 admin 业务规则失败走此入口。"""
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "error_code": int(code),
            "message_key": message_key,
            "message": message,
        },
    )
