"""RBAC 作用域上下文定义。

DeskClaw 采用四级作用域：platform / org / workspace / instance，
覆盖 MOM Cloud 单层 tenant_id 不足以表达的跨级权限场景。

`parent_org_id`：当目标 scope 是 workspace 或 instance 时，调用方可提供其
所属 org_id；resolver 据此让 org_admin / platform_admin 自动覆盖该 org 下
所有 workspace / instance 的权限检查（与现有 check_workspace_access 的
org-admin bypass 行为对齐）。
"""

from dataclasses import dataclass
from typing import Literal

# 作用域类型枚举（与 subject_roles.scope_type / menus 视图等保持一致）
ScopeType = Literal["platform", "org", "workspace", "instance"]


@dataclass(frozen=True)
class RbacScope:
    """权限检查的作用域上下文。

    - platform：全局作用域，id 固定为 None
    - org：组织作用域，id = org_id
    - workspace：工作区作用域，id = workspace_id，可附带 parent_org_id 启用跨级 bypass
    - instance：实例作用域，id = instance_id，同上
    """

    # 作用域类型
    type: ScopeType
    # 作用域具体 ID；platform 时为 None
    id: str | None = None
    # 当 type 为 workspace / instance 时，所属 org_id；用于 org_admin 跨级覆盖
    parent_org_id: str | None = None

    @classmethod
    def platform(cls) -> "RbacScope":
        """构造全局作用域。"""
        return cls(type="platform", id=None)

    @classmethod
    def org(cls, org_id: str) -> "RbacScope":
        """构造组织作用域。"""
        return cls(type="org", id=org_id)

    @classmethod
    def workspace(cls, workspace_id: str, *, org_id: str | None = None) -> "RbacScope":
        """构造工作区作用域；建议同时提供 org_id 以启用 org_admin 跨级覆盖。"""
        return cls(type="workspace", id=workspace_id, parent_org_id=org_id)

    @classmethod
    def instance(cls, instance_id: str, *, org_id: str | None = None) -> "RbacScope":
        """构造实例作用域；建议同时提供 org_id 以启用 org_admin 跨级覆盖。"""
        return cls(type="instance", id=instance_id, parent_org_id=org_id)
