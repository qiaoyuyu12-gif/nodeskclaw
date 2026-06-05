"""平台托管 Key 守卫的单元测试。

验证 OrgModelProvider 行被标记 is_platform_managed=True 时，组织端 PATCH/DELETE
的拦截行为；并验证 BYOK 行（is_platform_managed=False）不受影响。
"""

from __future__ import annotations

import pytest

from app.api.llm_keys import (
    _PLATFORM_MANAGED_LOCKED_FIELDS,
    assert_platform_managed_delete_allowed,
    assert_platform_managed_update_allowed,
)
from app.core.exceptions import ForbiddenError
from app.models.org_llm_key import OrgModelProvider


def _make_key(is_platform_managed: bool) -> OrgModelProvider:
    """构造一个内存态 OrgModelProvider 用于守卫测试，不依赖数据库会话。"""
    key = OrgModelProvider()
    key.is_platform_managed = is_platform_managed
    return key


class TestPlatformManagedUpdateGuard:
    def test_byok_row_allows_any_field(self) -> None:
        # BYOK 行（is_platform_managed=False）：所有字段都应放行
        key = _make_key(False)
        assert_platform_managed_update_allowed(
            key, set(_PLATFORM_MANAGED_LOCKED_FIELDS) | {"allowed_models", "is_active"}
        )

    @pytest.mark.parametrize("field", sorted(_PLATFORM_MANAGED_LOCKED_FIELDS))
    def test_platform_row_rejects_locked_field(self, field: str) -> None:
        # 平台托管行：任意单一受锁字段都该被拦截
        key = _make_key(True)
        with pytest.raises(ForbiddenError) as exc:
            assert_platform_managed_update_allowed(key, {field})
        assert exc.value.message_key == "errors.model_provider.platform_managed_locked"
        assert exc.value.status_code == 403

    def test_platform_row_allows_unlocked_fields(self) -> None:
        # 平台托管行：仅 allowed_models / is_active 可改
        key = _make_key(True)
        assert_platform_managed_update_allowed(key, {"allowed_models"})
        assert_platform_managed_update_allowed(key, {"is_active"})
        assert_platform_managed_update_allowed(key, {"allowed_models", "is_active"})

    def test_platform_row_rejects_mixed_payload(self) -> None:
        # 平台托管行：合法 + 非法字段混合，整体仍被拒
        key = _make_key(True)
        with pytest.raises(ForbiddenError):
            assert_platform_managed_update_allowed(key, {"allowed_models", "api_key"})


class TestPlatformManagedDeleteGuard:
    def test_byok_row_can_be_deleted(self) -> None:
        # BYOK 行可正常删除（不抛异常即通过）
        key = _make_key(False)
        assert_platform_managed_delete_allowed(key)

    def test_platform_row_rejects_delete(self) -> None:
        # 平台托管行拒绝组织端删除
        key = _make_key(True)
        with pytest.raises(ForbiddenError) as exc:
            assert_platform_managed_delete_allowed(key)
        assert exc.value.message_key == "errors.model_provider.platform_managed_no_delete"
        assert exc.value.status_code == 403
