"""EE Backend Router — 超管专属 API 路由。

main.py 会从 ee.backend.router 导入 ee_api_router 和 ee_admin_router，
EE 通过此模块向 admin_router 追加超管专属端点。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)

# 超管专属路由（EE only）
ee_admin_router = APIRouter()

# EE API 路由（如有需要可以扩展）
ee_api_router = APIRouter()


def _register_ee_admin_routes():
    """将 EE 超管路由注册到 ee_admin_router。"""
    if not ee_admin_router.routes:
        try:
            from ee.backend.api.admin.organizations import router as ee_org_router
            from ee.backend.api.admin.plans import router as ee_plans_router
            from ee.backend.api.admin.users import router as ee_users_router

            ee_admin_router.include_router(
                ee_org_router,
                prefix="/orgs",
                tags=["EE - 超管组织管理"],
            )
            ee_admin_router.include_router(
                ee_plans_router,
                prefix="/plans",
                tags=["EE - 超管套餐管理"],
            )
            # 全局用户管理（T13）
            ee_admin_router.include_router(
                ee_users_router,
                prefix="/users",
                tags=["EE - 超管用户管理"],
            )
            logger.info("EE 超管路由已注册到 ee_admin_router")
        except ImportError as e:
            logger.warning("无法加载 EE 超管路由: %s", e)


# 立即注册（模块导入时执行）
_register_ee_admin_routes()