"""RBAC 专用异常 re-export。

PermissionDeniedError 实际定义在 app/core/exceptions.py 以避免双重定义，
此处 re-export 以保持 `from app.core.rbac.exceptions import ...` 语义可用。
"""

from app.core.exceptions import PermissionDeniedError  # noqa: F401
