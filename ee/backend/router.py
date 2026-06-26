"""EE Backend Router — 超管专属 API 路由。

main.py 会从 ee.backend.router 导入 ee_api_router 和 ee_admin_router，
EE 通过此模块向 admin_router 追加超管专属端点。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

# 导入守卫依赖
from app.core.deps import require_feature, require_super_admin_dep

logger = logging.getLogger(__name__)

# 超管专属路由（EE only）
ee_admin_router = APIRouter()

# EE API 路由（如有需要可以扩展）
ee_api_router = APIRouter()


def _register_ee_admin_routes():
    """将 EE 超管路由注册到 ee_admin_router。"""
    if not ee_admin_router.routes:
        # 双守卫：require_feature("platform_admin") + require_super_admin_dep
        admin_deps = [
            Depends(require_feature("platform_admin")),
            Depends(require_super_admin_dep),
        ]

        _registered: list[str] = []
        _failed: list[str] = []

        def _try_include(import_path: str, prefix: str, tags: list[str]) -> None:
            module_name, attr = import_path.rsplit(".", 1)
            try:
                import importlib
                mod = importlib.import_module(module_name)
                router_obj = getattr(mod, attr)
                ee_admin_router.include_router(
                    router_obj,
                    prefix=prefix,
                    tags=tags,
                    dependencies=admin_deps,
                )
                _registered.append(module_name)
            except (ImportError, AttributeError) as e:
                logger.warning("无法加载 EE 超管路由 [%s]: %s", module_name, e)
                _failed.append(module_name)

        _try_include("ee.backend.api.admin.organizations.router", "/orgs", ["EE - 超管组织管理"])
        _try_include("ee.backend.api.admin.plans.router", "/plans", ["EE - 超管套餐管理"])
        _try_include("ee.backend.api.admin.users.router", "/users", ["EE - 超管用户管理"])
        # Feature override 管理：路由内已含完整路径 /features 和 /orgs/.../features
        _try_include("ee.backend.api.admin.features.router", "", ["EE - 超管功能开关"])
        # 审计日志查询
        _try_include("ee.backend.api.admin.audit.router", "", ["EE - 超管审计"])
        # 平台托管 Key 下发：路由内已含完整路径 /orgs/{org_id}/platform-providers
        _try_include("ee.backend.api.admin.platform_providers.router", "", ["EE - 超管平台模型 Key"])

        if _registered:
            logger.info("EE 超管路由已注册到 ee_admin_router: %s", _registered)
        if _failed:
            logger.warning("以下 EE 超管路由未能加载（功能不可用）: %s", _failed)


# 立即注册（模块导入时执行）
_register_ee_admin_routes()
