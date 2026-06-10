"""RBAC 权限决策审计日志表 `permission_audit_logs`。

独立于既有 `operation_audit_logs`（业务动作日志）。本表记录的是
「权限决策」事件 —— 即每次 has_perms / require_perms 检查的结果。

第一期**默认关闭**，仅当 `settings.RBAC_AUDIT_ENABLED=True` 时写入，避免
baseline 阶段产生大量写放大。建议生产环境上线 1-2 周后再灰度开启。

字段不继承 BaseModel 的 deleted_at（审计日志不软删，靠 TTL 清理）。
"""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PermissionAuditLog(Base):
    """权限决策审计记录。"""

    __tablename__ = "permission_audit_logs"
    __table_args__ = (
        # 按主体 + 时间倒序查询（最常用的反查路径）
        Index(
            "ix_pal_subject",
            "subject_type",
            "subject_id",
            "created_at",
        ),
        # 按决策结果统计 deny 比例
        Index("ix_pal_decision", "decision"),
        # 按时间清理过期日志
        Index("ix_pal_created_at", "created_at"),
    )

    # UUID 主键（不继承 BaseModel，故手动定义）
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4()),
    )
    # 主体类型：user / agent
    subject_type: Mapped[str] = mapped_column(String(8), nullable=False)
    # 主体 ID
    subject_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # 被检查的权限标识，例如 gene:publish
    perms_code: Mapped[str] = mapped_column(String(100), nullable=False)
    # 作用域类型
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # 作用域 ID，platform 时为 NULL
    scope_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # 决策结果：allow / deny
    decision: Mapped[str] = mapped_column(String(8), nullable=False)
    # 决策原因：命中的 role_key 或拒绝原因（no_matching_role / no_matching_perms）
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 关联 HTTP 请求的 X-Request-Id（若有）
    request_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # 决策发生时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
