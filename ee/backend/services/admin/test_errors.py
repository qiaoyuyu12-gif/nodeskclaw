"""错误码与异常工厂测试。"""

import pytest
from fastapi import HTTPException

from ee.backend.services.admin.errors import (
    AdminErrorCode,
    raise_admin_error,
)


def test_error_code_ranges():
    """检查 enum 区段分配与设计文档一致。"""
    assert 40901 <= AdminErrorCode.SELF_DEACTIVATE_FORBIDDEN.value <= 40919
    assert 40920 <= AdminErrorCode.ORG_SLUG_CONFLICT.value <= 40939
    assert 40940 <= AdminErrorCode.USER_NOT_FOUND.value <= 40959
    assert 40960 <= AdminErrorCode.FEATURE_ID_UNKNOWN.value <= 40979
    assert 40980 <= AdminErrorCode.AUDIT_ACTION_INVALID.value <= 40999


def test_raise_admin_error_builds_http_exception():
    """测试 raise_admin_error 抛出正确的 HTTPException。"""
    with pytest.raises(HTTPException) as exc:
        raise_admin_error(
            AdminErrorCode.SELF_DEACTIVATE_FORBIDDEN,
            message_key="errors.admin.self_deactivate_forbidden",
            message="Cannot deactivate yourself",
        )
    assert exc.value.status_code == 409
    assert exc.value.detail == {
        "error_code": 40901,
        "message_key": "errors.admin.self_deactivate_forbidden",
        "message": "Cannot deactivate yourself",
    }
