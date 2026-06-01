"""超管 service 包。"""

import sys
import importlib


def __getattr__(name: str):
    """惰性导入 service 模块和异常类。"""
    # 模块名映射
    modules_map = {
        "audit_service": "ee.backend.services.admin.audit_service",
        "feature_admin_service": "ee.backend.services.admin.feature_admin_service",
        "org_admin_service": "ee.backend.services.admin.org_admin_service",
        "user_admin_service": "ee.backend.services.admin.user_admin_service",
    }

    if name in modules_map:
        module_path = modules_map[name]
        # 动态导入模块，避免循环导入
        return importlib.import_module(module_path)
    elif name == "AdminErrorCode":
        from ee.backend.services.admin.errors import AdminErrorCode
        return AdminErrorCode
    elif name == "raise_admin_error":
        from ee.backend.services.admin.errors import raise_admin_error
        return raise_admin_error

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "audit_service",
    "feature_admin_service",
    "org_admin_service",
    "user_admin_service",
    "AdminErrorCode",
    "raise_admin_error",
]
