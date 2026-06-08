"""RBAC 核心库入口：对外暴露权限解析、依赖注入、超管保护等 API。

使用示例：
    from app.core.rbac import RbacScope, require_perms, has_perms

    @router.post(
        "/{org_id}/genes/{gene_id}/publish",
        dependencies=[Depends(require_perms(
            "gene:publish",
            scope_type="org",
            scope_param="org_id",
        ))],
    )
"""

from app.core.rbac.admin_guard import (  # noqa: F401
    SUPER_ROLE_KEY,
    assert_not_admin_role,
    assert_not_super_admin,
    is_super_admin_user,
)
from app.core.rbac.cache import (  # noqa: F401
    clear_all_caches,
    get_cached_grants,
    invalidate_subject,
    set_cached_grants,
)
from app.core.rbac.decorators import require_perms  # noqa: F401
from app.core.rbac.exceptions import PermissionDeniedError  # noqa: F401
from app.core.rbac.resolver import has_perms  # noqa: F401
from app.core.rbac.scope import RbacScope, ScopeType  # noqa: F401
