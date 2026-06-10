"""RBAC 只读 Debug API（参考 docs/rfcs/0001-rbac-phase1.md §15）。

提供给平台超管的运维接口：
- 列出指定主体的全部 subject_roles 记录（含 role_key / scope_type / scope_id）
- 列出指定主体聚合后的 role_keys / perms / app_codes（与 /auth/me.rbac 一致）

仅 require_super_admin_dep，避免组织管理员越权查看跨 org 的授权情况。
"""

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_super_admin_dep
from app.models.rbac.role import Role
from app.models.rbac.subject_role import SubjectRole
from app.schemas.common import ApiResponse
from app.services.rbac_context_service import get_login_rbac

router = APIRouter()


@router.get(
    "/subjects/{subject_id}",
    response_model=ApiResponse[dict],
    dependencies=[Depends(require_super_admin_dep)],
)
async def get_subject_rbac(
    subject_id: str,
    subject_type: str = "user",
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """查看指定主体的 RBAC 授权全貌。

    返回：
        {
          "subject_type": "user",
          "subject_id": "...",
          "grants": [
            {"role_key": "org_admin", "scope_type": "org", "scope_id": "org-1",
             "granted_reason": "seed:org_membership", "expires_at": null},
            ...
          ],
          "aggregate": {
            "role_keys": [...],
            "perms": [...],
            "app_codes": [...]
          }
        }
    """
    rows = (await db.execute(
        select(
            Role.role_key,
            SubjectRole.scope_type,
            SubjectRole.scope_id,
            SubjectRole.granted_by,
            SubjectRole.granted_reason,
            SubjectRole.expires_at,
            SubjectRole.created_at,
        )
        .join(SubjectRole, SubjectRole.role_id == Role.id)
        .where(
            SubjectRole.subject_type == subject_type,
            SubjectRole.subject_id == subject_id,
            SubjectRole.deleted_at.is_(None),
            Role.deleted_at.is_(None),
        )
        .order_by(
            Role.role_sort.asc(),
            SubjectRole.created_at.asc(),
        )
    )).all()

    grants: list[dict[str, Any]] = [
        {
            "role_key": r.role_key,
            "scope_type": r.scope_type,
            "scope_id": r.scope_id,
            "granted_by": r.granted_by,
            "granted_reason": r.granted_reason,
            "expires_at": r.expires_at.isoformat() if r.expires_at else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    aggregate = await get_login_rbac(
        db, subject_type=subject_type, subject_id=subject_id,
    )

    return ApiResponse(data={
        "subject_type": subject_type,
        "subject_id": subject_id,
        "grants": grants,
        "aggregate": aggregate,
    })
