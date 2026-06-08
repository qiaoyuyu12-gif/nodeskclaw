"""RBAC FastAPI 依赖：require_perms。

风格对齐 MOM Cloud @RequiresPermission 注解；改用 FastAPI 依赖注入方式，
可直接挂在 router 或 endpoint 的 `dependencies=[...]` 上。

用法：
    @router.post(
        "/{org_id}/workspaces/{workspace_id}/delete",
        dependencies=[Depends(require_perms(
            "workspace:delete",
            scope_type="workspace",
            scope_param="workspace_id",
            parent_org_param="org_id",
        ))],
    )
    async def delete_workspace(...):
        ...

第一期与现有 require_org_admin / require_org_role 等依赖**并存**，不强制替换。
第二期会按 RFC 0001 v2 §12 替换映射表统一切换。
"""

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.rbac.audit import log_decision_async
from app.core.rbac.resolver import has_perms
from app.core.rbac.scope import RbacScope, ScopeType
from app.core.security import get_auth_actor, get_current_user_or_agent


def require_perms(
    perms_code: str,
    *,
    scope_type: ScopeType = "org",
    scope_param: str | None = None,
    parent_org_param: str | None = "org_id",
):
    """生成权限检查 FastAPI 依赖。

    参数：
        perms_code: 权限标识，命名规范 `module:resource:action`
        scope_type: 作用域类型（platform / org / workspace / instance）
        scope_param: 从 path_params 取 scope_id 的键名；platform 时不需要；
                     org scope 未提供时回退到 user.current_org_id
        parent_org_param: workspace / instance scope 检查时，从 path_params 取
                          所属 org_id 的键名，用于让 org_admin 跨级覆盖
    """

    async def _check(
        request: Request,
        db: AsyncSession = Depends(get_db),
        user=Depends(get_current_user_or_agent),
    ) -> None:
        # 优先从 ContextVar 拿 actor（区分 user / agent）；兜底用 user.id
        actor = get_auth_actor()
        actor_type, actor_id = (
            (actor.actor_type, actor.actor_id) if actor else ("user", user.id)
        )

        # 构造目标 scope
        if scope_type == "platform":
            scope = RbacScope.platform()
        else:
            scope_id: str | None = (
                request.path_params.get(scope_param) if scope_param else None
            )
            # org scope 兜底：使用用户当前选中的 org
            if scope_id is None and scope_type == "org":
                scope_id = user.current_org_id

            if not scope_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error_code": 40010,
                        "message_key": "errors.rbac.scope_missing",
                        "message": f"权限检查缺少 {scope_type} 作用域",
                    },
                )

            # 抽取 parent_org_id 以启用 org_admin 跨级覆盖（仅 workspace/instance 有效）
            parent_org_id: str | None = (
                request.path_params.get(parent_org_param)
                if parent_org_param else None
            )
            scope = RbacScope(
                type=scope_type, id=scope_id, parent_org_id=parent_org_id,
            )

        allowed, matched = await has_perms(
            db,
            subject_type=actor_type, subject_id=actor_id,
            perms_code=perms_code, scope=scope,
        )

        # 异步审计：失败不影响主请求；RBAC_AUDIT_ENABLED=False 时直接 no-op
        await log_decision_async(
            subject_type=actor_type, subject_id=actor_id,
            perms_code=perms_code, scope=scope,
            decision="allow" if allowed else "deny",
            reason=matched or "no_matching_role",
            request_id=request.headers.get("X-Request-Id"),
        )

        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error_code": 40330,
                    "message_key": "errors.rbac.permission_denied",
                    "message": f"缺少权限 {perms_code}",
                },
            )

    return _check
