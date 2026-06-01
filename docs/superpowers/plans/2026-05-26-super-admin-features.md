# 超管后台功能丰富 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 EE 版超管后台从只能 CRUD 组织扩展为完整运维控制台，覆盖组织/用户/Feature override/审计四大能力，附带最低安全审计与 90 天保留期清理 Job。

**Architecture:** 后端 endpoint 极薄（仅参数解析 + service 调用 + 响应组装），全部业务规则（自我保护、级联软删、override 合并、审计落库）下沉到 `ee/backend/services/admin/*`；前端采用 AdminLayout 侧边栏 + 嵌套路由，Feature 视图按 feature 主轴 + 抽屉显示 override，避免全矩阵加载。

**Tech Stack:** Backend: Python 3.12 + FastAPI + SQLAlchemy(asyncpg) + Alembic + pytest；Frontend: Vue 3 + TypeScript + Tailwind + lucide-vue-next + vitest；审计复用 `operation_audit_logs` 表。

**Source spec:** `docs/superpowers/specs/2026-05-26-super-admin-features-design.md`

---

## 阶段总览

| 阶段 | 任务 | 范围 |
|---|---|---|
| 1 基础 | T1–T4 | 迁移 / Model / Enum / 审计 service |
| 2 后端服务 | T5–T10 | feature / org / user / 自我保护 |
| 3 后端 API | T11–T16 | endpoint refactor + 新增 |
| 4 安全审计 | T17–T18 | auth 审计 + 保留期 Job |
| 5 前端基础 | T19–T20 | adminApi 扩展 + AdminLayout + 路由 |
| 6 前端页面 | T21–T26 | 6 个视图 |
| 7 i18n + 文档 | T27–T28 | 词条 + 操作手册 |

---

## Phase 1 — 基础

### Task 1: 新增 Alembic 迁移 — `organization_feature_overrides` 表 + `users.deleted_by`

**Files:**
- Create: `nodeskclaw-backend/alembic/versions/<auto>_super_admin_features.py`（由 autogenerate 生成）
- Modify: `nodeskclaw-backend/app/models/user.py` — 增加 `deleted_by` 字段
- Create: `nodeskclaw-backend/app/models/organization_feature_override.py`

- [ ] **Step 1: 编写 `OrganizationFeatureOverride` 模型（用于让 autogenerate 检测）**

```python
# nodeskclaw-backend/app/models/organization_feature_override.py
"""组织级 Feature 覆盖 — 在 edition_features 默认之上叠加 override。"""

from sqlalchemy import Boolean, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class OrganizationFeatureOverride(BaseModel):
    """单条 (org_id, feature_id) 覆盖记录；软删 + Partial Unique Index 保唯一。"""

    __tablename__ = "organization_feature_overrides"
    __table_args__ = (
        Index(
            "uq_org_feature",
            "org_id",
            "feature_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    # 目标组织 id
    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"), nullable=False, index=True)
    # 目标 feature_id（与 features.yaml 中 id 对应）
    feature_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # 强制启用 / 强制关闭
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # 设置原因（可空，便于事后追溯）
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 操作超管 user_id
    set_by_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
```

- [ ] **Step 2: 在 `nodeskclaw-backend/app/models/__init__.py` 中导入新模型**

打开文件，在合适位置追加：
```python
# 导入：让 alembic autogenerate 能发现该模型
from app.models.organization_feature_override import OrganizationFeatureOverride  # noqa: F401
```

- [ ] **Step 3: 在 `app/models/user.py` 中追加 `deleted_by`**

Read `nodeskclaw-backend/app/models/user.py`，在合适位置（与 `is_active` 等字段同区）追加：
```python
    # 软删时记录是哪个超管删除的（仅 users 表特有；其他表本期不引入）
    deleted_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
```

- [ ] **Step 4: 生成迁移**

```bash
cd nodeskclaw-backend
uv run alembic revision --autogenerate -m "add organization_feature_overrides and users.deleted_by"
```

Expected: `alembic/versions/<hash>_add_organization_feature_overrides_and_users_deleted_by.py` 生成。

- [ ] **Step 5: 审查迁移文件**

打开生成文件，确认 upgrade() 只包含：
- `op.create_table("organization_feature_overrides", ...)` 含 `uq_org_feature` partial unique index
- `op.add_column("users", sa.Column("deleted_by", sa.String(36), nullable=True))`

无其他无关 diff（如果检测到无关 column drop，必须人工删除）。

- [ ] **Step 6: 升级测试库验证迁移**

```bash
cd nodeskclaw-backend
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic upgrade head
```

Expected: 三次执行均成功，无异常。

- [ ] **Step 7: Commit**

```bash
git add nodeskclaw-backend/app/models/organization_feature_override.py \
        nodeskclaw-backend/app/models/__init__.py \
        nodeskclaw-backend/app/models/user.py \
        nodeskclaw-backend/alembic/versions/
git commit -m "feat(db): 新增 organization_feature_overrides 表与 users.deleted_by 字段"
```

---

### Task 2: `AdminAction` Enum

**Files:**
- Create: `nodeskclaw-backend/app/models/admin_action.py`
- Create: `nodeskclaw-backend/tests/models/test_admin_action.py`

- [ ] **Step 1: 写失败测试**

```python
# nodeskclaw-backend/tests/models/test_admin_action.py
"""AdminAction enum 校验测试。"""

import pytest

from app.models.admin_action import AdminAction


def test_all_actions_use_domain_dot_verb_format():
    """枚举值必须为 domain.verb 字符串格式。"""
    for action in AdminAction:
        assert "." in action.value, f"{action.name} 值缺少域分隔符: {action.value}"


def test_known_admin_actions_present():
    """关键超管动作必须存在（防误删）。"""
    expected = {
        "org.create", "org.update", "org.delete",
        "org_member.add", "org_member.update", "org_member.remove",
        "user.update", "user.reset_password", "user.delete",
        "feature_override.set", "feature_override.clear",
        "auth.login_success", "auth.login_failed", "auth.logout",
    }
    values = {a.value for a in AdminAction}
    missing = expected - values
    assert not missing, f"缺少枚举值: {missing}"


def test_enum_is_str():
    """AdminAction 必须继承 str，用于直接序列化为审计行的 action 列。"""
    assert isinstance(AdminAction.ORG_CREATE, str)
    assert AdminAction.ORG_CREATE == "org.create"
```

- [ ] **Step 2: 验证测试失败**

```bash
cd nodeskclaw-backend
uv run pytest tests/models/test_admin_action.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.models.admin_action'`

- [ ] **Step 3: 实现 enum**

```python
# nodeskclaw-backend/app/models/admin_action.py
"""超管审计动作枚举 — 所有审计写入必须走 enum，禁止裸字符串。"""

from enum import Enum


class AdminAction(str, Enum):
    """domain.verb 风格的审计动作值。

    新增枚举值时必须同步：
      1. 本 enum
      2. 前端 i18n（zh-CN + en）的 `admin.audit.actions.<value>`
      3. 审计单测（覆盖 service 路径）
    """

    # 组织
    ORG_CREATE = "org.create"
    ORG_UPDATE = "org.update"
    ORG_DELETE = "org.delete"
    # 组织成员
    ORG_MEMBER_ADD = "org_member.add"
    ORG_MEMBER_UPDATE = "org_member.update"
    ORG_MEMBER_REMOVE = "org_member.remove"
    # 用户
    USER_UPDATE = "user.update"
    USER_RESET_PASSWORD = "user.reset_password"
    USER_DELETE = "user.delete"
    # Feature override
    FEATURE_OVERRIDE_SET = "feature_override.set"
    FEATURE_OVERRIDE_CLEAR = "feature_override.clear"
    # 安全（最低审计）
    AUTH_LOGIN_SUCCESS = "auth.login_success"
    AUTH_LOGIN_FAILED = "auth.login_failed"
    AUTH_LOGOUT = "auth.logout"
```

- [ ] **Step 4: 验证测试通过**

```bash
uv run pytest tests/models/test_admin_action.py -v
```

Expected: PASS（3 项）

- [ ] **Step 5: Commit**

```bash
git add nodeskclaw-backend/app/models/admin_action.py \
        nodeskclaw-backend/tests/models/test_admin_action.py
git commit -m "feat(audit): 新增 AdminAction 枚举强约束审计动作"
```

---

### Task 3: 错误码常量与统一异常工厂

**Files:**
- Create: `ee/backend/services/admin/__init__.py`（空）
- Create: `ee/backend/services/admin/errors.py`
- Create: `ee/backend/services/admin/test_errors.py`

- [ ] **Step 1: 写失败测试**

```python
# ee/backend/services/admin/test_errors.py
"""错误码与异常工厂测试。"""

import pytest
from fastapi import HTTPException

from ee.backend.services.admin.errors import (
    AdminErrorCode,
    raise_admin_error,
)


def test_error_code_ranges():
    """检查 enum 区段分配与设计文档一致。"""
    assert 40901 <= AdminErrorCode.SELF_DEACTIVATE_FORBIDDEN.value <= 40919
    assert 40920 <= AdminErrorCode.ORG_SLUG_CONFLICT.value <= 40939
    assert 40940 <= AdminErrorCode.USER_NOT_FOUND.value <= 40959
    assert 40960 <= AdminErrorCode.FEATURE_ID_UNKNOWN.value <= 40979
    assert 40980 <= AdminErrorCode.AUDIT_ACTION_INVALID.value <= 40999


def test_raise_admin_error_builds_http_exception():
    with pytest.raises(HTTPException) as exc:
        raise_admin_error(
            AdminErrorCode.SELF_DEACTIVATE_FORBIDDEN,
            message_key="errors.admin.self_deactivate_forbidden",
            message="Cannot deactivate yourself",
        )
    assert exc.value.status_code == 409
    assert exc.value.detail == {
        "error_code": 40901,
        "message_key": "errors.admin.self_deactivate_forbidden",
        "message": "Cannot deactivate yourself",
    }
```

- [ ] **Step 2: 运行测试验证失败**

```bash
uv run pytest ee/backend/services/admin/test_errors.py -v
```

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现**

```python
# ee/backend/services/admin/__init__.py
# 留空，作为包标识
```

```python
# ee/backend/services/admin/errors.py
"""超管 admin 域错误码与异常工厂。

设计参考 docs/superpowers/specs/2026-05-26-super-admin-features-design.md §5.0。
所有 admin endpoint 失败统一抛 HTTPException(409)，前端按 message_key 显示本地化提示。
"""

from __future__ import annotations

from enum import IntEnum

from fastapi import HTTPException, status


class AdminErrorCode(IntEnum):
    """错误码段位：
      40901–40919 自我保护类
      40920–40939 组织管理类
      40940–40959 用户管理类
      40960–40979 Feature override 类
      40980–40999 审计类
    """

    # 自我保护
    SELF_DEACTIVATE_FORBIDDEN = 40901
    SELF_DEMOTE_SUPER_ADMIN_FORBIDDEN = 40902
    SELF_DELETE_FORBIDDEN = 40903
    LAST_SUPER_ADMIN_FORBIDDEN = 40904

    # 组织
    ORG_SLUG_CONFLICT = 40920
    ORG_HAS_RUNNING_INSTANCES = 40921
    ORG_LAST_ADMIN_FORBIDDEN = 40922
    ORG_NOT_FOUND = 40923
    ORG_MEMBER_DUPLICATE = 40924

    # 用户
    USER_NOT_FOUND = 40940
    USER_EMAIL_CONFLICT = 40941
    USER_ALREADY_DELETED = 40942

    # Feature override
    FEATURE_ID_UNKNOWN = 40960
    FEATURE_OVERRIDE_NOT_FOUND = 40961

    # 审计
    AUDIT_ACTION_INVALID = 40980
    AUDIT_TIME_RANGE_INVALID = 40981


def raise_admin_error(code: AdminErrorCode, *, message_key: str, message: str) -> None:
    """统一错误抛出（409 Conflict）。所有 admin 业务规则失败走此入口。"""
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "error_code": int(code),
            "message_key": message_key,
            "message": message,
        },
    )
```

- [ ] **Step 4: 验证测试通过**

```bash
uv run pytest ee/backend/services/admin/test_errors.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ee/backend/services/admin/
git commit -m "feat(admin): 引入 admin 域错误码枚举与统一异常工厂"
```

---

### Task 4: 审计服务 `audit_service.with_audit`

**Files:**
- Create: `ee/backend/services/admin/audit_service.py`
- Create: `ee/backend/services/admin/test_audit_service.py`

- [ ] **Step 1: 写失败测试**

```python
# ee/backend/services/admin/test_audit_service.py
"""audit_service.with_audit 行为测试。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models.admin_action import AdminAction
from app.models.operation_audit_log import OperationAuditLog
from ee.backend.services.admin import audit_service


@pytest.mark.asyncio
async def test_with_audit_success_writes_row(db_session, super_admin_user):
    async with audit_service.with_audit(
        db_session,
        action=AdminAction.ORG_CREATE,
        actor=super_admin_user,
        target_type="org",
        target_id="org-1",
        before=None,
        after={"name": "foo"},
        details={"reason": "test"},
    ):
        pass
    rows = (await db_session.execute(select(OperationAuditLog))).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.action == "org.create"
    assert row.target_type == "org"
    assert row.target_id == "org-1"
    assert row.actor_id == super_admin_user.id
    assert row.details["after"] == {"name": "foo"}
    assert row.details["reason"] == "test"


@pytest.mark.asyncio
async def test_with_audit_failure_writes_failure_row(db_session, super_admin_user):
    with pytest.raises(RuntimeError):
        async with audit_service.with_audit(
            db_session,
            action=AdminAction.ORG_DELETE,
            actor=super_admin_user,
            target_type="org",
            target_id="org-1",
        ):
            raise RuntimeError("boom")
    rows = (await db_session.execute(select(OperationAuditLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].details["status"] == "failed"
    assert "boom" in rows[0].details["error"]


@pytest.mark.asyncio
async def test_only_enum_action_accepted(db_session, super_admin_user):
    """字符串 action 必须被类型检查 / 运行时校验拦截。"""
    with pytest.raises((TypeError, ValueError)):
        async with audit_service.with_audit(
            db_session,
            action="org.create",  # 故意传裸字符串
            actor=super_admin_user,
            target_type="org",
            target_id="x",
        ):
            pass
```

- [ ] **Step 2: 准备测试 fixtures（如尚无）**

确认 `nodeskclaw-backend/tests/conftest.py` 或对应位置已提供：
- `db_session` — async SQLAlchemy session
- `super_admin_user` — 已落库的 `is_super_admin=True` 用户

如缺失，新增对应 fixture（参考已有 backend 测试），不在此处展开。

- [ ] **Step 3: 验证测试失败**

```bash
uv run pytest ee/backend/services/admin/test_audit_service.py -v
```

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 4: 实现**

```python
# ee/backend/services/admin/audit_service.py
"""审计服务 — 统一封装 with_audit 异步上下文管理器与查询函数。

设计目标：
  1. 所有超管动作走 with_audit，禁止 service 直接 db.add(OperationAuditLog)
  2. 失败抛异常时仍写一条 "失败" 审计，details.status="failed"
  3. action 参数仅接受 AdminAction enum，运行时校验拦截裸字符串
"""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_action import AdminAction
from app.models.operation_audit_log import OperationAuditLog
from app.models.user import User

logger = logging.getLogger(__name__)


@asynccontextmanager
async def with_audit(
    db: AsyncSession,
    *,
    action: AdminAction,
    actor: User | None,
    target_type: str,
    target_id: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
    org_id: str | None = None,
    actor_ip: str | None = None,
    actor_user_agent: str | None = None,
) -> AsyncIterator[None]:
    """包裹 service 方法体；成功写入成功审计，异常写入失败审计后重新抛出。

    Args:
        db: 当前事务 session
        action: AdminAction enum（运行时校验）
        actor: 操作人；登录失败等 anonymous 路径传 None
        target_type / target_id: 目标资源
        before / after: 状态快照（reset_password 不可写明文）
        details: 附加字段
    """
    if not isinstance(action, AdminAction):
        raise TypeError(
            f"with_audit 仅接受 AdminAction enum；收到 {type(action).__name__}={action!r}"
        )

    payload: dict[str, Any] = {
        "before": before,
        "after": after,
    }
    if details:
        payload.update(details)

    try:
        yield
    except Exception as exc:  # noqa: BLE001
        payload["status"] = "failed"
        payload["error"] = str(exc)[:500]
        await _write(
            db,
            action=action,
            actor=actor,
            target_type=target_type,
            target_id=target_id,
            details=payload,
            org_id=org_id,
            actor_ip=actor_ip,
            actor_user_agent=actor_user_agent,
        )
        raise
    else:
        payload.setdefault("status", "success")
        await _write(
            db,
            action=action,
            actor=actor,
            target_type=target_type,
            target_id=target_id,
            details=payload,
            org_id=org_id,
            actor_ip=actor_ip,
            actor_user_agent=actor_user_agent,
        )


async def _write(
    db: AsyncSession,
    *,
    action: AdminAction,
    actor: User | None,
    target_type: str,
    target_id: str,
    details: dict[str, Any],
    org_id: str | None,
    actor_ip: str | None,
    actor_user_agent: str | None,
) -> None:
    # 登录失败等匿名路径：actor_id 用 "anonymous" 占位（NOT NULL 列要求）
    actor_id = actor.id if actor else "anonymous"
    actor_type = "user" if actor else "anonymous"
    actor_name = actor.email if actor else None
    if actor_ip:
        details["ip"] = actor_ip
    if actor_user_agent:
        details["user_agent"] = actor_user_agent

    row = OperationAuditLog(
        id=str(uuid.uuid4()),
        org_id=org_id,
        action=action.value,
        target_type=target_type,
        target_id=target_id,
        actor_type=actor_type,
        actor_id=actor_id,
        actor_name=actor_name,
        details=details,
    )
    db.add(row)
    # 不在此处 commit；让外层事务一并提交，保证 with_audit 与业务变更原子
    await db.flush()


async def query_audit_logs(
    db: AsyncSession,
    *,
    actor_id: str | None = None,
    action: AdminAction | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[OperationAuditLog], int]:
    """审计日志查询。返回 (rows, total)。"""
    from sqlalchemy import func as sa_func

    stmt = select(OperationAuditLog)
    count_stmt = select(sa_func.count(OperationAuditLog.id))

    if actor_id:
        stmt = stmt.where(OperationAuditLog.actor_id == actor_id)
        count_stmt = count_stmt.where(OperationAuditLog.actor_id == actor_id)
    if action is not None:
        stmt = stmt.where(OperationAuditLog.action == action.value)
        count_stmt = count_stmt.where(OperationAuditLog.action == action.value)
    if from_dt:
        stmt = stmt.where(OperationAuditLog.created_at >= from_dt)
        count_stmt = count_stmt.where(OperationAuditLog.created_at >= from_dt)
    if to_dt:
        stmt = stmt.where(OperationAuditLog.created_at <= to_dt)
        count_stmt = count_stmt.where(OperationAuditLog.created_at <= to_dt)

    total = (await db.execute(count_stmt)).scalar_one()
    rows = (
        await db.execute(
            stmt.order_by(OperationAuditLog.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return list(rows), total
```

- [ ] **Step 5: 验证测试通过**

```bash
uv run pytest ee/backend/services/admin/test_audit_service.py -v
```

Expected: PASS（3 项）

- [ ] **Step 6: Commit**

```bash
git add ee/backend/services/admin/audit_service.py \
        ee/backend/services/admin/test_audit_service.py
git commit -m "feat(audit): 新增 audit_service.with_audit 上下文管理器与查询接口"
```

---

## Phase 2 — 后端服务

### Task 5: `feature_admin_service` + FeatureGate 组织级 override

**Files:**
- Modify: `nodeskclaw-backend/app/core/feature_gate.py` — 增加 `is_enabled_for_org` 异步路径
- Create: `ee/backend/services/admin/feature_admin_service.py`
- Create: `ee/backend/services/admin/test_feature_admin_service.py`

- [ ] **Step 1: 写失败测试**

```python
# ee/backend/services/admin/test_feature_admin_service.py
"""feature_admin_service 行为测试。"""

import pytest

from ee.backend.services.admin import feature_admin_service
from ee.backend.services.admin.errors import AdminErrorCode
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_set_override_creates_row(db_session, super_admin_user, sample_org):
    await feature_admin_service.set_override(
        db_session,
        admin=super_admin_user,
        org_id=sample_org.id,
        feature_id="knowledge_base",
        enabled=True,
        reason="试点",
    )
    await db_session.commit()
    state = await feature_admin_service.resolve_org_feature(
        db_session, org_id=sample_org.id, feature_id="knowledge_base"
    )
    assert state["enabled"] is True
    assert state["source"] == "override"
    assert state["reason"] == "试点"


@pytest.mark.asyncio
async def test_set_override_unknown_feature_id_rejected(db_session, super_admin_user, sample_org):
    with pytest.raises(HTTPException) as exc:
        await feature_admin_service.set_override(
            db_session,
            admin=super_admin_user,
            org_id=sample_org.id,
            feature_id="not_a_real_feature_id_zzz",
            enabled=True,
            reason=None,
        )
    assert exc.value.detail["error_code"] == int(AdminErrorCode.FEATURE_ID_UNKNOWN)


@pytest.mark.asyncio
async def test_clear_override_softdeletes_row(db_session, super_admin_user, sample_org):
    await feature_admin_service.set_override(
        db_session, admin=super_admin_user, org_id=sample_org.id,
        feature_id="knowledge_base", enabled=True, reason=None,
    )
    await db_session.commit()
    await feature_admin_service.clear_override(
        db_session, admin=super_admin_user, org_id=sample_org.id, feature_id="knowledge_base",
    )
    await db_session.commit()
    state = await feature_admin_service.resolve_org_feature(
        db_session, org_id=sample_org.id, feature_id="knowledge_base"
    )
    assert state["source"] == "default"


@pytest.mark.asyncio
async def test_resolve_default_when_no_override(db_session, sample_org):
    state = await feature_admin_service.resolve_org_feature(
        db_session, org_id=sample_org.id, feature_id="knowledge_base"
    )
    assert state["source"] == "default"
    assert "default_enabled" in state
```

- [ ] **Step 2: 验证测试失败**

```bash
uv run pytest ee/backend/services/admin/test_feature_admin_service.py -v
```

Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现 service**

```python
# ee/backend/services/admin/feature_admin_service.py
"""Feature override 服务：组织级覆盖 + FeatureGate 合并。"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.feature_gate import feature_gate
from app.models.admin_action import AdminAction
from app.models.organization_feature_override import OrganizationFeatureOverride
from app.models.user import User
from ee.backend.services.admin import audit_service
from ee.backend.services.admin.errors import AdminErrorCode, raise_admin_error

logger = logging.getLogger(__name__)


def _all_feature_ids() -> set[str]:
    """从 FeatureGate 拿到所有合法 feature_id（features.yaml + ee/features.yaml）。"""
    return {f["id"] for f in feature_gate.all_features()}


def _default_enabled(feature_id: str) -> bool:
    """edition_features 默认值。"""
    return feature_gate.is_enabled(feature_id)


async def resolve_org_feature(
    db: AsyncSession, *, org_id: str, feature_id: str
) -> dict[str, Any]:
    """返回 {feature_id, enabled, source, default_enabled, reason?, set_by_user_id?, set_at?}."""
    row = (
        await db.execute(
            select(OrganizationFeatureOverride).where(
                OrganizationFeatureOverride.org_id == org_id,
                OrganizationFeatureOverride.feature_id == feature_id,
                OrganizationFeatureOverride.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    default = _default_enabled(feature_id)
    if row is None:
        return {
            "feature_id": feature_id,
            "enabled": default,
            "source": "default",
            "default_enabled": default,
        }
    return {
        "feature_id": feature_id,
        "enabled": row.enabled,
        "source": "override",
        "default_enabled": default,
        "reason": row.reason,
        "set_by_user_id": row.set_by_user_id,
        "set_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def list_org_features(db: AsyncSession, *, org_id: str) -> list[dict[str, Any]]:
    """该组织所有 feature 的 effective 状态（前端 AdminOrgDetail Features tab 使用）。"""
    return [
        await resolve_org_feature(db, org_id=org_id, feature_id=fid)
        for fid in sorted(_all_feature_ids())
    ]


async def list_features_with_override_count(db: AsyncSession) -> list[dict[str, Any]]:
    """所有 feature + 覆盖计数（前端 AdminFeatureList 使用）。"""
    counts = dict(
        (
            await db.execute(
                select(
                    OrganizationFeatureOverride.feature_id,
                    sa_func.count(OrganizationFeatureOverride.id),
                )
                .where(OrganizationFeatureOverride.deleted_at.is_(None))
                .group_by(OrganizationFeatureOverride.feature_id)
            )
        ).all()
    )
    out: list[dict[str, Any]] = []
    for f in feature_gate.all_features():
        out.append({
            "feature_id": f["id"],
            "name": f.get("name", f["id"]),
            "description": f.get("description", ""),
            "default_enabled": _default_enabled(f["id"]),
            "override_count": counts.get(f["id"], 0),
        })
    return out


async def list_overrides_for_feature(
    db: AsyncSession, *, feature_id: str, page: int = 1, page_size: int = 20
) -> tuple[list[OrganizationFeatureOverride], int]:
    """某 feature 上的所有 override（分页）。"""
    if feature_id not in _all_feature_ids():
        raise_admin_error(
            AdminErrorCode.FEATURE_ID_UNKNOWN,
            message_key="errors.admin.feature_id_unknown",
            message=f"Unknown feature_id: {feature_id}",
        )
    base = select(OrganizationFeatureOverride).where(
        OrganizationFeatureOverride.feature_id == feature_id,
        OrganizationFeatureOverride.deleted_at.is_(None),
    )
    total = (
        await db.execute(
            select(sa_func.count(OrganizationFeatureOverride.id)).where(
                OrganizationFeatureOverride.feature_id == feature_id,
                OrganizationFeatureOverride.deleted_at.is_(None),
            )
        )
    ).scalar_one()
    rows = (
        await db.execute(
            base.order_by(OrganizationFeatureOverride.updated_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return list(rows), total


async def set_override(
    db: AsyncSession,
    *,
    admin: User,
    org_id: str,
    feature_id: str,
    enabled: bool,
    reason: str | None,
) -> OrganizationFeatureOverride:
    if feature_id not in _all_feature_ids():
        raise_admin_error(
            AdminErrorCode.FEATURE_ID_UNKNOWN,
            message_key="errors.admin.feature_id_unknown",
            message=f"Unknown feature_id: {feature_id}",
        )
    existing = (
        await db.execute(
            select(OrganizationFeatureOverride).where(
                OrganizationFeatureOverride.org_id == org_id,
                OrganizationFeatureOverride.feature_id == feature_id,
                OrganizationFeatureOverride.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    before = {
        "enabled": existing.enabled if existing else _default_enabled(feature_id),
        "source": "override" if existing else "default",
    }
    async with audit_service.with_audit(
        db,
        action=AdminAction.FEATURE_OVERRIDE_SET,
        actor=admin,
        target_type="feature_override",
        target_id=f"{org_id}:{feature_id}",
        org_id=org_id,
        before=before,
        after={"enabled": enabled, "reason": reason},
    ):
        if existing:
            existing.enabled = enabled
            existing.reason = reason
            existing.set_by_user_id = admin.id
            row = existing
        else:
            row = OrganizationFeatureOverride(
                org_id=org_id,
                feature_id=feature_id,
                enabled=enabled,
                reason=reason,
                set_by_user_id=admin.id,
            )
            db.add(row)
        await db.flush()
    return row


async def clear_override(
    db: AsyncSession, *, admin: User, org_id: str, feature_id: str
) -> None:
    existing = (
        await db.execute(
            select(OrganizationFeatureOverride).where(
                OrganizationFeatureOverride.org_id == org_id,
                OrganizationFeatureOverride.feature_id == feature_id,
                OrganizationFeatureOverride.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if not existing:
        raise_admin_error(
            AdminErrorCode.FEATURE_OVERRIDE_NOT_FOUND,
            message_key="errors.admin.feature_override_not_found",
            message="Override not found",
        )
    before = {"enabled": existing.enabled, "reason": existing.reason}
    async with audit_service.with_audit(
        db,
        action=AdminAction.FEATURE_OVERRIDE_CLEAR,
        actor=admin,
        target_type="feature_override",
        target_id=f"{org_id}:{feature_id}",
        org_id=org_id,
        before=before,
        after={"enabled": _default_enabled(feature_id), "source": "default"},
    ):
        existing.deleted_at = datetime.utcnow()
        await db.flush()
```

- [ ] **Step 4: 验证测试通过**

```bash
uv run pytest ee/backend/services/admin/test_feature_admin_service.py -v
```

Expected: PASS（4 项）

- [ ] **Step 5: 改造 `app/core/feature_gate.py` 增加异步 org 路径（保持 sync 入口向后兼容）**

在文件末尾追加（不修改已有同步 `is_enabled`）：
```python
async def is_enabled_for_org(feature_id: str, org_id: str | None, db) -> bool:
    """组织级 override 优先；无 override 回落到 edition 默认。

    db: AsyncSession（运行时传入，避免在模块顶部循环依赖）。
    """
    if org_id is None:
        return feature_gate.is_enabled(feature_id)
    # 延迟 import 防循环
    from app.models.organization_feature_override import OrganizationFeatureOverride
    from sqlalchemy import select as _select
    row = await db.execute(
        _select(OrganizationFeatureOverride.enabled).where(
            OrganizationFeatureOverride.org_id == org_id,
            OrganizationFeatureOverride.feature_id == feature_id,
            OrganizationFeatureOverride.deleted_at.is_(None),
        )
    )
    v = row.scalar_one_or_none()
    if v is not None:
        return v
    return feature_gate.is_enabled(feature_id)
```

- [ ] **Step 6: 启动期孤儿告警**

在 `FeatureGate._load` 末尾或独立异步钩子（不强求迁移期完成；先 TODO 注释保留）：
```python
        # TODO(super-admin): 启动期对 organization_feature_overrides 中
        # 不属于 self._ee_feature_ids 的孤儿行输出告警日志。
        # 实施位置：app/main.py lifespan 启动钩子，调用一次性 audit。
```

- [ ] **Step 7: Commit**

```bash
git add nodeskclaw-backend/app/core/feature_gate.py \
        ee/backend/services/admin/feature_admin_service.py \
        ee/backend/services/admin/test_feature_admin_service.py
git commit -m "feat(feature): 新增组织级 Feature override 服务与 FeatureGate 异步合并"
```

---

### Task 6: `org_admin_service` — 组织 CRUD

**Files:**
- Create: `ee/backend/services/admin/org_admin_service.py`
- Create: `ee/backend/services/admin/test_org_admin_service.py`

- [ ] **Step 1: 写失败测试**

```python
# ee/backend/services/admin/test_org_admin_service.py
"""org_admin_service CRUD + 成员管理测试。"""

import pytest
from fastapi import HTTPException

from ee.backend.services.admin import org_admin_service
from ee.backend.services.admin.errors import AdminErrorCode


@pytest.mark.asyncio
async def test_create_org_slug_conflict(db_session, super_admin_user, sample_org):
    with pytest.raises(HTTPException) as exc:
        await org_admin_service.create_org(
            db_session, admin=super_admin_user,
            name="dup", slug=sample_org.slug, plan="free",
            max_instances=1, max_cpu_total="4", max_mem_total="8Gi",
            max_storage_total="500Gi", max_collaboration_depth=3, cluster_id=None,
        )
    assert exc.value.detail["error_code"] == int(AdminErrorCode.ORG_SLUG_CONFLICT)


@pytest.mark.asyncio
async def test_delete_org_with_running_instances_blocked(db_session, super_admin_user, sample_org_with_running_instance):
    with pytest.raises(HTTPException) as exc:
        await org_admin_service.delete_org(
            db_session, admin=super_admin_user, org_id=sample_org_with_running_instance.id,
        )
    assert exc.value.detail["error_code"] == int(AdminErrorCode.ORG_HAS_RUNNING_INSTANCES)


@pytest.mark.asyncio
async def test_create_org_writes_audit(db_session, super_admin_user):
    from sqlalchemy import select
    from app.models.operation_audit_log import OperationAuditLog
    org = await org_admin_service.create_org(
        db_session, admin=super_admin_user,
        name="new", slug="new-org-1", plan="free",
        max_instances=1, max_cpu_total="4", max_mem_total="8Gi",
        max_storage_total="500Gi", max_collaboration_depth=3, cluster_id=None,
    )
    await db_session.commit()
    audits = (await db_session.execute(
        select(OperationAuditLog).where(OperationAuditLog.target_id == org.id)
    )).scalars().all()
    assert any(a.action == "org.create" for a in audits)
```

- [ ] **Step 2: 验证测试失败**

```bash
uv run pytest ee/backend/services/admin/test_org_admin_service.py -v
```

Expected: FAIL

- [ ] **Step 3: 实现**

```python
# ee/backend/services/admin/org_admin_service.py
"""组织管理 service：CRUD + 实例校验 + 审计。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_action import AdminAction
from app.models.instance import Instance, InstanceStatus
from app.models.organization import Organization
from app.models.user import User
from ee.backend.services.admin import audit_service
from ee.backend.services.admin.errors import AdminErrorCode, raise_admin_error


async def create_org(
    db: AsyncSession,
    *,
    admin: User,
    name: str,
    slug: str,
    plan: str,
    max_instances: int,
    max_cpu_total: str,
    max_mem_total: str,
    max_storage_total: str,
    max_collaboration_depth: int,
    cluster_id: str | None,
) -> Organization:
    dup = (
        await db.execute(
            select(Organization).where(
                Organization.slug == slug,
                Organization.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if dup:
        raise_admin_error(
            AdminErrorCode.ORG_SLUG_CONFLICT,
            message_key="errors.admin.org_slug_conflict",
            message=f"Slug already exists: {slug}",
        )

    org = Organization(
        name=name,
        slug=slug,
        plan=plan,
        max_instances=max_instances,
        max_cpu_total=max_cpu_total,
        max_mem_total=max_mem_total,
        max_storage_total=max_storage_total,
        max_collaboration_depth=max_collaboration_depth,
        cluster_id=cluster_id,
        is_active=True,
    )
    db.add(org)
    await db.flush()

    async with audit_service.with_audit(
        db,
        action=AdminAction.ORG_CREATE,
        actor=admin,
        target_type="org",
        target_id=org.id,
        org_id=org.id,
        before=None,
        after={"name": name, "slug": slug, "plan": plan},
    ):
        pass
    return org


async def update_org(
    db: AsyncSession, *, admin: User, org_id: str, patch: dict[str, Any]
) -> Organization:
    org = await _get_org_or_404(db, org_id)
    before = {k: getattr(org, k) for k in patch.keys()}
    async with audit_service.with_audit(
        db,
        action=AdminAction.ORG_UPDATE,
        actor=admin,
        target_type="org",
        target_id=org.id,
        org_id=org.id,
        before=before,
        after=patch,
    ):
        for k, v in patch.items():
            setattr(org, k, v)
        await db.flush()
    return org


async def delete_org(db: AsyncSession, *, admin: User, org_id: str) -> None:
    org = await _get_org_or_404(db, org_id)
    running = (
        await db.execute(
            select(sa_func.count(Instance.id)).where(
                Instance.org_id == org_id,
                Instance.deleted_at.is_(None),
                Instance.status.in_([InstanceStatus.running, InstanceStatus.deploying]),
            )
        )
    ).scalar_one()
    if running:
        raise_admin_error(
            AdminErrorCode.ORG_HAS_RUNNING_INSTANCES,
            message_key="errors.admin.org_has_running_instances",
            message="Cannot delete org with running instances",
        )

    async with audit_service.with_audit(
        db,
        action=AdminAction.ORG_DELETE,
        actor=admin,
        target_type="org",
        target_id=org.id,
        org_id=org.id,
        before={"name": org.name, "slug": org.slug},
        after=None,
    ):
        org.deleted_at = datetime.utcnow()
        await db.flush()


async def _get_org_or_404(db: AsyncSession, org_id: str) -> Organization:
    org = (
        await db.execute(
            select(Organization).where(
                Organization.id == org_id, Organization.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if not org:
        raise_admin_error(
            AdminErrorCode.ORG_NOT_FOUND,
            message_key="errors.admin.org_not_found",
            message="Organization not found",
        )
    return org
```

- [ ] **Step 4: 验证测试通过**

```bash
uv run pytest ee/backend/services/admin/test_org_admin_service.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ee/backend/services/admin/org_admin_service.py \
        ee/backend/services/admin/test_org_admin_service.py
git commit -m "feat(admin): 新增组织管理 service（CRUD + 审计 + 实例校验）"
```

---

### Task 7: `org_admin_service` — 成员管理（追加到同文件）

**Files:**
- Modify: `ee/backend/services/admin/org_admin_service.py`
- Modify: `ee/backend/services/admin/test_org_admin_service.py`

- [ ] **Step 1: 追加失败测试**

```python
# 在 test_org_admin_service.py 追加
@pytest.mark.asyncio
async def test_add_member_duplicate_rejected(db_session, super_admin_user, sample_org, sample_user):
    await org_admin_service.add_member(
        db_session, admin=super_admin_user, org_id=sample_org.id,
        user_id=sample_user.id, role="member",
    )
    await db_session.commit()
    with pytest.raises(HTTPException) as exc:
        await org_admin_service.add_member(
            db_session, admin=super_admin_user, org_id=sample_org.id,
            user_id=sample_user.id, role="member",
        )
    assert exc.value.detail["error_code"] == int(AdminErrorCode.ORG_MEMBER_DUPLICATE)


@pytest.mark.asyncio
async def test_remove_last_org_admin_rejected(db_session, super_admin_user, sample_org_with_single_admin):
    org, admin_user = sample_org_with_single_admin
    with pytest.raises(HTTPException) as exc:
        await org_admin_service.remove_member(
            db_session, admin=super_admin_user, org_id=org.id, user_id=admin_user.id,
        )
    assert exc.value.detail["error_code"] == int(AdminErrorCode.ORG_LAST_ADMIN_FORBIDDEN)
```

- [ ] **Step 2: 验证失败**

```bash
uv run pytest ee/backend/services/admin/test_org_admin_service.py -v
```

Expected: 新增测试 FAIL（`add_member` / `remove_member` 不存在）

- [ ] **Step 3: 实现成员管理**

```python
# 在 ee/backend/services/admin/org_admin_service.py 追加
from app.models.org_membership import OrgMembership  # 在文件顶部追加


async def list_members(db: AsyncSession, *, org_id: str) -> list[OrgMembership]:
    return list(
        (
            await db.execute(
                select(OrgMembership).where(
                    OrgMembership.org_id == org_id,
                    OrgMembership.deleted_at.is_(None),
                )
            )
        ).scalars().all()
    )


async def add_member(
    db: AsyncSession, *, admin: User, org_id: str, user_id: str, role: str
) -> OrgMembership:
    await _get_org_or_404(db, org_id)
    await _ensure_user_exists(db, user_id)
    dup = (
        await db.execute(
            select(OrgMembership).where(
                OrgMembership.org_id == org_id,
                OrgMembership.user_id == user_id,
                OrgMembership.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if dup:
        raise_admin_error(
            AdminErrorCode.ORG_MEMBER_DUPLICATE,
            message_key="errors.admin.org_member_duplicate",
            message="Member already exists",
        )
    m = OrgMembership(org_id=org_id, user_id=user_id, role=role)
    db.add(m)
    await db.flush()
    async with audit_service.with_audit(
        db,
        action=AdminAction.ORG_MEMBER_ADD,
        actor=admin,
        target_type="org_member",
        target_id=f"{org_id}:{user_id}",
        org_id=org_id,
        before=None,
        after={"role": role},
    ):
        pass
    return m


async def update_member_role(
    db: AsyncSession, *, admin: User, org_id: str, user_id: str, role: str
) -> OrgMembership:
    m = await _get_member_or_404(db, org_id, user_id)
    # 若降级唯一 admin 须拒绝
    if m.role == "admin" and role != "admin":
        await _ensure_not_last_admin(db, org_id, user_id)
    before = {"role": m.role}
    async with audit_service.with_audit(
        db,
        action=AdminAction.ORG_MEMBER_UPDATE,
        actor=admin,
        target_type="org_member",
        target_id=f"{org_id}:{user_id}",
        org_id=org_id,
        before=before,
        after={"role": role},
    ):
        m.role = role
        await db.flush()
    return m


async def remove_member(
    db: AsyncSession, *, admin: User, org_id: str, user_id: str
) -> None:
    m = await _get_member_or_404(db, org_id, user_id)
    if m.role == "admin":
        await _ensure_not_last_admin(db, org_id, user_id)
    async with audit_service.with_audit(
        db,
        action=AdminAction.ORG_MEMBER_REMOVE,
        actor=admin,
        target_type="org_member",
        target_id=f"{org_id}:{user_id}",
        org_id=org_id,
        before={"role": m.role},
        after=None,
    ):
        m.deleted_at = datetime.utcnow()
        await db.flush()


async def _ensure_user_exists(db: AsyncSession, user_id: str) -> None:
    u = (
        await db.execute(
            select(User).where(User.id == user_id, User.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if not u:
        raise_admin_error(
            AdminErrorCode.USER_NOT_FOUND,
            message_key="errors.admin.user_not_found",
            message="User not found",
        )


async def _get_member_or_404(db: AsyncSession, org_id: str, user_id: str) -> OrgMembership:
    m = (
        await db.execute(
            select(OrgMembership).where(
                OrgMembership.org_id == org_id,
                OrgMembership.user_id == user_id,
                OrgMembership.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if not m:
        raise_admin_error(
            AdminErrorCode.ORG_MEMBER_DUPLICATE,
            message_key="errors.admin.org_member_not_found",
            message="Org member not found",
        )
    return m


async def _ensure_not_last_admin(db: AsyncSession, org_id: str, user_id: str) -> None:
    count = (
        await db.execute(
            select(sa_func.count(OrgMembership.id)).where(
                OrgMembership.org_id == org_id,
                OrgMembership.role == "admin",
                OrgMembership.deleted_at.is_(None),
                OrgMembership.user_id != user_id,
            )
        )
    ).scalar_one()
    if count == 0:
        raise_admin_error(
            AdminErrorCode.ORG_LAST_ADMIN_FORBIDDEN,
            message_key="errors.admin.org_last_admin_forbidden",
            message="Cannot remove the last admin of org",
        )
```

- [ ] **Step 4: 验证通过**

```bash
uv run pytest ee/backend/services/admin/test_org_admin_service.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ee/backend/services/admin/org_admin_service.py \
        ee/backend/services/admin/test_org_admin_service.py
git commit -m "feat(admin): 组织成员管理 service（增/改/删 + 最后 admin 守卫）"
```

---

### Task 8: `user_admin_service` — update_user + 自我保护 + 最后超管

**Files:**
- Create: `ee/backend/services/admin/user_admin_service.py`
- Create: `ee/backend/services/admin/test_user_admin_service.py`

- [ ] **Step 1: 写失败测试**

```python
# ee/backend/services/admin/test_user_admin_service.py
"""user_admin_service 自我保护与最后超管守卫。"""

import pytest
from fastapi import HTTPException

from ee.backend.services.admin import user_admin_service
from ee.backend.services.admin.errors import AdminErrorCode


@pytest.mark.asyncio
async def test_cannot_deactivate_self(db_session, super_admin_user):
    with pytest.raises(HTTPException) as exc:
        await user_admin_service.update_user(
            db_session, admin=super_admin_user, user_id=super_admin_user.id,
            patch={"is_active": False},
        )
    assert exc.value.detail["error_code"] == int(AdminErrorCode.SELF_DEACTIVATE_FORBIDDEN)


@pytest.mark.asyncio
async def test_cannot_demote_self_super_admin(db_session, super_admin_user):
    with pytest.raises(HTTPException) as exc:
        await user_admin_service.update_user(
            db_session, admin=super_admin_user, user_id=super_admin_user.id,
            patch={"is_super_admin": False},
        )
    assert exc.value.detail["error_code"] == int(AdminErrorCode.SELF_DEMOTE_SUPER_ADMIN_FORBIDDEN)


@pytest.mark.asyncio
async def test_cannot_remove_last_super_admin(
    db_session, super_admin_user, another_super_admin_user
):
    # 撤销另一个超管，让 super_admin_user 变成 "最后一个"
    await user_admin_service.update_user(
        db_session, admin=super_admin_user, user_id=another_super_admin_user.id,
        patch={"is_super_admin": False},
    )
    await db_session.commit()
    # 再次尝试撤销 super_admin_user 自己 → 自我保护拦截
    with pytest.raises(HTTPException) as exc:
        await user_admin_service.update_user(
            db_session, admin=super_admin_user, user_id=super_admin_user.id,
            patch={"is_super_admin": False},
        )
    assert exc.value.detail["error_code"] in (
        int(AdminErrorCode.SELF_DEMOTE_SUPER_ADMIN_FORBIDDEN),
        int(AdminErrorCode.LAST_SUPER_ADMIN_FORBIDDEN),
    )


@pytest.mark.asyncio
async def test_update_user_writes_audit(db_session, super_admin_user, sample_user):
    from sqlalchemy import select
    from app.models.operation_audit_log import OperationAuditLog
    await user_admin_service.update_user(
        db_session, admin=super_admin_user, user_id=sample_user.id,
        patch={"is_active": False},
    )
    await db_session.commit()
    audits = (await db_session.execute(
        select(OperationAuditLog).where(OperationAuditLog.target_id == sample_user.id)
    )).scalars().all()
    assert any(a.action == "user.update" for a in audits)
```

- [ ] **Step 2: 验证失败**

```bash
uv run pytest ee/backend/services/admin/test_user_admin_service.py -v
```

Expected: FAIL

- [ ] **Step 3: 实现**

```python
# ee/backend/services/admin/user_admin_service.py
"""用户管理 service：标志切换、密码重置、级联软删；含自我保护 + 最后超管守卫。"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime
from typing import Any

from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.admin_action import AdminAction
from app.models.admin_membership import AdminMembership
from app.models.org_membership import OrgMembership
from app.models.user import User
from app.models.user_llm_config import UserLLMConfig
from app.models.user_llm_key import UserLLMKey
from ee.backend.services.admin import audit_service
from ee.backend.services.admin.errors import AdminErrorCode, raise_admin_error

logger = logging.getLogger(__name__)


async def update_user(
    db: AsyncSession, *, admin: User, user_id: str, patch: dict[str, Any]
) -> User:
    user = await _get_user_or_404(db, user_id)
    _enforce_self_protection(admin, user, patch)
    if patch.get("is_super_admin") is False and user.is_super_admin:
        await _ensure_not_last_super_admin(db, user.id)

    before = {k: getattr(user, k) for k in patch.keys()}
    async with audit_service.with_audit(
        db,
        action=AdminAction.USER_UPDATE,
        actor=admin,
        target_type="user",
        target_id=user.id,
        before=before,
        after=patch,
    ):
        for k, v in patch.items():
            setattr(user, k, v)
        await db.flush()
    return user


async def reset_password(
    db: AsyncSession, *, admin: User, user_id: str
) -> str:
    """返回明文 temp_password；不写入 before/after。"""
    user = await _get_user_or_404(db, user_id)
    temp = secrets.token_urlsafe(12)
    user.password_hash = hash_password(temp)
    user.must_change_password = True
    async with audit_service.with_audit(
        db,
        action=AdminAction.USER_RESET_PASSWORD,
        actor=admin,
        target_type="user",
        target_id=user.id,
        before=None,
        after=None,
        details={"note": "password reset; plaintext intentionally excluded"},
    ):
        await db.flush()
    return temp


async def delete_user(
    db: AsyncSession, *, admin: User, user_id: str
) -> None:
    user = await _get_user_or_404(db, user_id)
    if user.id == admin.id:
        raise_admin_error(
            AdminErrorCode.SELF_DELETE_FORBIDDEN,
            message_key="errors.admin.self_delete_forbidden",
            message="Cannot delete yourself",
        )
    if user.is_super_admin:
        await _ensure_not_last_super_admin(db, user.id)

    now = datetime.utcnow()
    async with audit_service.with_audit(
        db,
        action=AdminAction.USER_DELETE,
        actor=admin,
        target_type="user",
        target_id=user.id,
        before={"email": user.email, "is_super_admin": user.is_super_admin},
        after=None,
        details={"cascade": ["org_membership", "admin_membership", "user_llm_key", "user_llm_config"]},
    ):
        user.deleted_at = now
        user.deleted_by = admin.id
        # 级联软删白名单（按设计 §4.3）
        for table in (OrgMembership, AdminMembership, UserLLMKey, UserLLMConfig):
            rows = (
                await db.execute(
                    select(table).where(
                        table.user_id == user.id,
                        table.deleted_at.is_(None),
                    )
                )
            ).scalars().all()
            for r in rows:
                r.deleted_at = now
        await db.flush()


def _enforce_self_protection(admin: User, target: User, patch: dict[str, Any]) -> None:
    if target.id != admin.id:
        return
    if patch.get("is_active") is False:
        raise_admin_error(
            AdminErrorCode.SELF_DEACTIVATE_FORBIDDEN,
            message_key="errors.admin.self_deactivate_forbidden",
            message="Cannot deactivate yourself",
        )
    if patch.get("is_super_admin") is False:
        raise_admin_error(
            AdminErrorCode.SELF_DEMOTE_SUPER_ADMIN_FORBIDDEN,
            message_key="errors.admin.self_demote_super_admin_forbidden",
            message="Cannot revoke your own super admin",
        )


async def _ensure_not_last_super_admin(db: AsyncSession, exclude_user_id: str) -> None:
    count = (
        await db.execute(
            select(sa_func.count(User.id)).where(
                User.is_super_admin.is_(True),
                User.deleted_at.is_(None),
                User.id != exclude_user_id,
            )
        )
    ).scalar_one()
    if count == 0:
        raise_admin_error(
            AdminErrorCode.LAST_SUPER_ADMIN_FORBIDDEN,
            message_key="errors.admin.last_super_admin_forbidden",
            message="Cannot remove the last super admin",
        )


async def _get_user_or_404(db: AsyncSession, user_id: str) -> User:
    u = (
        await db.execute(
            select(User).where(User.id == user_id, User.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if not u:
        raise_admin_error(
            AdminErrorCode.USER_NOT_FOUND,
            message_key="errors.admin.user_not_found",
            message="User not found",
        )
    return u
```

- [ ] **Step 4: 验证通过**

```bash
uv run pytest ee/backend/services/admin/test_user_admin_service.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ee/backend/services/admin/user_admin_service.py \
        ee/backend/services/admin/test_user_admin_service.py
git commit -m "feat(admin): 新增用户管理 service（自我保护+最后超管+级联软删+密码重置）"
```

---

### Task 9: `user_admin_service` — reset_password + delete_user 测试加固

**Files:**
- Modify: `ee/backend/services/admin/test_user_admin_service.py`

- [ ] **Step 1: 追加测试**

```python
@pytest.mark.asyncio
async def test_reset_password_returns_plaintext_and_sets_must_change(
    db_session, super_admin_user, sample_user
):
    from app.core.security import verify_password
    temp = await user_admin_service.reset_password(
        db_session, admin=super_admin_user, user_id=sample_user.id,
    )
    await db_session.commit()
    await db_session.refresh(sample_user)
    assert temp and len(temp) >= 12
    assert verify_password(temp, sample_user.password_hash)
    assert sample_user.must_change_password is True


@pytest.mark.asyncio
async def test_reset_password_audit_excludes_plaintext(
    db_session, super_admin_user, sample_user
):
    from sqlalchemy import select
    from app.models.operation_audit_log import OperationAuditLog
    temp = await user_admin_service.reset_password(
        db_session, admin=super_admin_user, user_id=sample_user.id,
    )
    await db_session.commit()
    audits = (await db_session.execute(
        select(OperationAuditLog).where(
            OperationAuditLog.action == "user.reset_password",
            OperationAuditLog.target_id == sample_user.id,
        )
    )).scalars().all()
    assert audits
    payload_text = str(audits[0].details)
    assert temp not in payload_text, "明文密码绝不可写入审计"


@pytest.mark.asyncio
async def test_delete_user_softdeletes_and_cascades(
    db_session, super_admin_user, sample_user_with_memberships
):
    from sqlalchemy import select
    from app.models.org_membership import OrgMembership
    target = sample_user_with_memberships
    await user_admin_service.delete_user(
        db_session, admin=super_admin_user, user_id=target.id,
    )
    await db_session.commit()
    await db_session.refresh(target)
    assert target.deleted_at is not None
    assert target.deleted_by == super_admin_user.id
    # OrgMembership 级联软删
    memberships = (await db_session.execute(
        select(OrgMembership).where(
            OrgMembership.user_id == target.id,
            OrgMembership.deleted_at.is_(None),
        )
    )).scalars().all()
    assert memberships == []
```

- [ ] **Step 2: 验证通过**

```bash
uv run pytest ee/backend/services/admin/test_user_admin_service.py -v
```

Expected: PASS（新增 3 项）

- [ ] **Step 3: Commit**

```bash
git add ee/backend/services/admin/test_user_admin_service.py
git commit -m "test(admin): 加固密码重置与级联软删测试覆盖"
```

---

### Task 10: 服务层小整理 — `__init__.py` 重新导出

**Files:**
- Modify: `ee/backend/services/admin/__init__.py`

- [ ] **Step 1: 整理导出**

```python
# ee/backend/services/admin/__init__.py
"""超管 service 包。"""

from ee.backend.services.admin import (
    audit_service,
    feature_admin_service,
    org_admin_service,
    user_admin_service,
)
from ee.backend.services.admin.errors import AdminErrorCode, raise_admin_error

__all__ = [
    "audit_service",
    "feature_admin_service",
    "org_admin_service",
    "user_admin_service",
    "AdminErrorCode",
    "raise_admin_error",
]
```

- [ ] **Step 2: 运行全套 admin service 测试确认未破坏导入**

```bash
uv run pytest ee/backend/services/admin/ -v
```

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add ee/backend/services/admin/__init__.py
git commit -m "chore(admin): 服务包统一导出入口"
```

---

## Phase 3 — 后端 API

### Task 11: Refactor `ee/backend/api/admin/organizations.py` 使用 service

**Files:**
- Modify: `ee/backend/api/admin/organizations.py`
- Create: `ee/backend/api/admin/test_organizations_api.py`

- [ ] **Step 1: 写 happy-path + 鉴权 403 测试**

```python
# ee/backend/api/admin/test_organizations_api.py
"""组织 admin endpoint happy-path 与鉴权测试（业务规则不在 endpoint 层重复）。"""

import pytest


@pytest.mark.asyncio
async def test_create_org_happy(async_client, super_admin_token):
    resp = await async_client.post(
        "/admin/orgs",
        json={"name": "t", "slug": "t1", "plan": "free"},
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["slug"] == "t1"


@pytest.mark.asyncio
async def test_create_org_403_for_non_admin(async_client, normal_user_token):
    resp = await async_client.post(
        "/admin/orgs",
        json={"name": "t", "slug": "t1"},
        headers={"Authorization": f"Bearer {normal_user_token}"},
    )
    assert resp.status_code == 403
```

- [ ] **Step 2: 验证失败**

```bash
uv run pytest ee/backend/api/admin/test_organizations_api.py -v
```

Expected: FAIL（endpoint 仍返回旧格式 / 响应不带 data 包装）

- [ ] **Step 3: Refactor endpoint，所有规则下沉到 service**

替换 `ee/backend/api/admin/organizations.py` 中各 endpoint 主体：
```python
from app.schemas.common import ApiResponse
from ee.backend.services.admin import org_admin_service


@router.post("", response_model=ApiResponse[AdminOrgInfo])
async def create_org(
    body: AdminOrgCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    """超管创建组织（业务规则全部在 service 层）。"""
    org = await org_admin_service.create_org(
        db,
        admin=admin,
        name=body.name,
        slug=body.slug,
        plan=body.plan,
        max_instances=body.max_instances,
        max_cpu_total=body.max_cpu_total,
        max_mem_total=body.max_mem_total,
        max_storage_total=body.max_storage_total,
        max_collaboration_depth=body.max_collaboration_depth,
        cluster_id=body.cluster_id,
    )
    await db.commit()
    await db.refresh(org)
    return ApiResponse[AdminOrgInfo](data=AdminOrgInfo.model_validate(org))


@router.put("/{org_id}", response_model=ApiResponse[AdminOrgInfo])
async def update_org(
    org_id: str,
    body: AdminOrgUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    org = await org_admin_service.update_org(
        db, admin=admin, org_id=org_id, patch=body.model_dump(exclude_unset=True)
    )
    await db.commit()
    await db.refresh(org)
    return ApiResponse[AdminOrgInfo](data=AdminOrgInfo.model_validate(org))


@router.delete("/{org_id}", response_model=ApiResponse[dict])
async def delete_org(
    org_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    await org_admin_service.delete_org(db, admin=admin, org_id=org_id)
    await db.commit()
    return ApiResponse[dict](data={"deleted": True})
```

`list_all_orgs` 与 `get_org` 保留聚合统计逻辑（实例数 / 资源用量计算属于查询装饰，不属于业务规则，留在 endpoint 即可），但响应统一包装为 `ApiResponse[list[AdminOrgInfo]]` / `ApiResponse[AdminOrgInfo]`。

- [ ] **Step 4: 验证通过**

```bash
uv run pytest ee/backend/api/admin/test_organizations_api.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ee/backend/api/admin/organizations.py \
        ee/backend/api/admin/test_organizations_api.py
git commit -m "refactor(admin): 组织 endpoint 下沉规则到 service 并统一 ApiResponse 包装"
```

---

### Task 12: `admin/organizations.py` — 成员端点

**Files:**
- Modify: `ee/backend/api/admin/organizations.py`
- Modify: `ee/backend/api/admin/test_organizations_api.py`

- [ ] **Step 1: 写测试**

```python
@pytest.mark.asyncio
async def test_add_member_happy(async_client, super_admin_token, sample_org, sample_user):
    resp = await async_client.post(
        f"/admin/orgs/{sample_org.id}/members",
        json={"user_id": sample_user.id, "role": "member"},
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["role"] == "member"
```

- [ ] **Step 2: 实现 endpoint**

在 `organizations.py` 追加：
```python
class AdminOrgMemberIn(BaseModel):
    user_id: str
    role: str = Field(..., pattern=r"^(admin|operator|member)$")


class AdminOrgMemberPatch(BaseModel):
    role: str = Field(..., pattern=r"^(admin|operator|member)$")


class AdminOrgMemberInfo(BaseModel):
    user_id: str
    role: str
    joined_at: datetime | None = None
    user_email: str | None = None
    user_name: str | None = None

    model_config = {"from_attributes": True}


@router.get("/{org_id}/members", response_model=ApiResponse[list[AdminOrgMemberInfo]])
async def list_org_members(
    org_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    members = await org_admin_service.list_members(db, org_id=org_id)
    return ApiResponse[list[AdminOrgMemberInfo]](
        data=[AdminOrgMemberInfo.model_validate(m) for m in members]
    )


@router.post("/{org_id}/members", response_model=ApiResponse[AdminOrgMemberInfo])
async def add_org_member(
    org_id: str,
    body: AdminOrgMemberIn,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    m = await org_admin_service.add_member(
        db, admin=admin, org_id=org_id, user_id=body.user_id, role=body.role,
    )
    await db.commit()
    return ApiResponse[AdminOrgMemberInfo](data=AdminOrgMemberInfo.model_validate(m))


@router.put("/{org_id}/members/{user_id}", response_model=ApiResponse[AdminOrgMemberInfo])
async def update_org_member(
    org_id: str,
    user_id: str,
    body: AdminOrgMemberPatch,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    m = await org_admin_service.update_member_role(
        db, admin=admin, org_id=org_id, user_id=user_id, role=body.role,
    )
    await db.commit()
    return ApiResponse[AdminOrgMemberInfo](data=AdminOrgMemberInfo.model_validate(m))


@router.delete("/{org_id}/members/{user_id}", response_model=ApiResponse[dict])
async def remove_org_member(
    org_id: str,
    user_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    await org_admin_service.remove_member(db, admin=admin, org_id=org_id, user_id=user_id)
    await db.commit()
    return ApiResponse[dict](data={"deleted": True})
```

- [ ] **Step 3: 验证通过**

```bash
uv run pytest ee/backend/api/admin/test_organizations_api.py -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add ee/backend/api/admin/organizations.py \
        ee/backend/api/admin/test_organizations_api.py
git commit -m "feat(admin): 组织成员管理 endpoint"
```

---

### Task 13: `admin/users.py`

**Files:**
- Create: `ee/backend/api/admin/users.py`
- Create: `ee/backend/api/admin/test_users_api.py`

- [ ] **Step 1: 写测试**

```python
# ee/backend/api/admin/test_users_api.py
import pytest


@pytest.mark.asyncio
async def test_list_users_paginated(async_client, super_admin_token):
    resp = await async_client.get(
        "/admin/users?page=1&page_size=10",
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "pagination" in body
    assert body["pagination"]["page"] == 1


@pytest.mark.asyncio
async def test_reset_password_returns_temp(async_client, super_admin_token, sample_user):
    resp = await async_client.post(
        f"/admin/users/{sample_user.id}/reset-password",
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["temp_password"]


@pytest.mark.asyncio
async def test_update_user_403_for_normal(async_client, normal_user_token, sample_user):
    resp = await async_client.put(
        f"/admin/users/{sample_user.id}",
        json={"is_active": False},
        headers={"Authorization": f"Bearer {normal_user_token}"},
    )
    assert resp.status_code == 403
```

- [ ] **Step 2: 实现 endpoint**

```python
# ee/backend/api/admin/users.py
"""超管全局用户管理 endpoint。所有规则在 user_admin_service。"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func as sa_func
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_super_admin_dep
from app.models.org_membership import OrgMembership
from app.models.user import User
from app.schemas.common import ApiResponse, PaginatedResponse, Pagination
from ee.backend.services.admin import user_admin_service

router = APIRouter()


class AdminUserInfo(BaseModel):
    id: str
    email: str
    name: str | None = None
    is_active: bool
    is_super_admin: bool
    must_change_password: bool
    created_at: datetime
    org_count: int = 0

    model_config = {"from_attributes": True}


class AdminUserPatch(BaseModel):
    is_active: bool | None = None
    is_super_admin: bool | None = None


@router.get("", response_model=PaginatedResponse[AdminUserInfo])
async def list_users(
    q: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    stmt = select(User).where(User.deleted_at.is_(None))
    count_stmt = select(sa_func.count(User.id)).where(User.deleted_at.is_(None))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(User.email.ilike(like), User.name.ilike(like)))
        count_stmt = count_stmt.where(or_(User.email.ilike(like), User.name.ilike(like)))
    total = (await db.execute(count_stmt)).scalar_one()
    rows = (
        await db.execute(
            stmt.order_by(User.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    # 批量统计每用户的 org_count
    ids = [u.id for u in rows]
    if ids:
        counts = dict(
            (
                await db.execute(
                    select(OrgMembership.user_id, sa_func.count(OrgMembership.id))
                    .where(OrgMembership.user_id.in_(ids), OrgMembership.deleted_at.is_(None))
                    .group_by(OrgMembership.user_id)
                )
            ).all()
        )
    else:
        counts = {}

    data = []
    for u in rows:
        info = AdminUserInfo.model_validate(u)
        info.org_count = counts.get(u.id, 0)
        data.append(info)

    return PaginatedResponse[AdminUserInfo](
        data=data,
        pagination=Pagination(page=page, page_size=page_size, total=total),
    )


@router.get("/{user_id}", response_model=ApiResponse[AdminUserInfo])
async def get_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    u = (
        await db.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
    ).scalar_one_or_none()
    if not u:
        from ee.backend.services.admin.errors import AdminErrorCode, raise_admin_error
        raise_admin_error(
            AdminErrorCode.USER_NOT_FOUND,
            message_key="errors.admin.user_not_found",
            message="User not found",
        )
    return ApiResponse[AdminUserInfo](data=AdminUserInfo.model_validate(u))


@router.put("/{user_id}", response_model=ApiResponse[AdminUserInfo])
async def update_user(
    user_id: str,
    body: AdminUserPatch,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    u = await user_admin_service.update_user(
        db, admin=admin, user_id=user_id, patch=body.model_dump(exclude_unset=True),
    )
    await db.commit()
    await db.refresh(u)
    return ApiResponse[AdminUserInfo](data=AdminUserInfo.model_validate(u))


@router.post("/{user_id}/reset-password", response_model=ApiResponse[dict])
async def reset_password(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    temp = await user_admin_service.reset_password(db, admin=admin, user_id=user_id)
    await db.commit()
    return ApiResponse[dict](data={"temp_password": temp})


@router.delete("/{user_id}", response_model=ApiResponse[dict])
async def delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    await user_admin_service.delete_user(db, admin=admin, user_id=user_id)
    await db.commit()
    return ApiResponse[dict](data={"deleted": True})
```

- [ ] **Step 3: 验证通过**

```bash
uv run pytest ee/backend/api/admin/test_users_api.py -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add ee/backend/api/admin/users.py ee/backend/api/admin/test_users_api.py
git commit -m "feat(admin): 全局用户管理 endpoint"
```

---

### Task 14: `admin/features.py`

**Files:**
- Create: `ee/backend/api/admin/features.py`
- Create: `ee/backend/api/admin/test_features_api.py`

- [ ] **Step 1: 写测试**

```python
# ee/backend/api/admin/test_features_api.py
import pytest


@pytest.mark.asyncio
async def test_list_features_returns_override_count(async_client, super_admin_token):
    resp = await async_client.get(
        "/admin/features",
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    for item in body["data"]:
        assert "feature_id" in item
        assert "default_enabled" in item
        assert "override_count" in item


@pytest.mark.asyncio
async def test_set_then_clear_override(async_client, super_admin_token, sample_org):
    set_resp = await async_client.put(
        f"/admin/orgs/{sample_org.id}/features/knowledge_base",
        json={"enabled": True, "reason": "试点"},
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert set_resp.status_code == 200
    assert set_resp.json()["data"]["source"] == "override"
    clear_resp = await async_client.delete(
        f"/admin/orgs/{sample_org.id}/features/knowledge_base",
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert clear_resp.status_code == 200
```

- [ ] **Step 2: 实现 endpoint**

```python
# ee/backend/api/admin/features.py
"""Feature override endpoint。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_super_admin_dep
from app.models.user import User
from app.schemas.common import ApiResponse, PaginatedResponse, Pagination
from ee.backend.services.admin import feature_admin_service

router = APIRouter()


class FeatureOverrideIn(BaseModel):
    enabled: bool
    reason: str | None = None


@router.get("/features", response_model=ApiResponse[list[dict]])
async def list_features(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    return ApiResponse[list[dict]](
        data=await feature_admin_service.list_features_with_override_count(db)
    )


@router.get(
    "/features/{feature_id}/overrides",
    response_model=PaginatedResponse[dict],
)
async def list_feature_overrides(
    feature_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    rows, total = await feature_admin_service.list_overrides_for_feature(
        db, feature_id=feature_id, page=page, page_size=page_size,
    )
    data = [
        {
            "org_id": r.org_id,
            "enabled": r.enabled,
            "reason": r.reason,
            "set_by_user_id": r.set_by_user_id,
            "set_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]
    return PaginatedResponse[dict](
        data=data,
        pagination=Pagination(page=page, page_size=page_size, total=total),
    )


@router.get("/orgs/{org_id}/features", response_model=ApiResponse[list[dict]])
async def list_org_features(
    org_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    return ApiResponse[list[dict]](
        data=await feature_admin_service.list_org_features(db, org_id=org_id)
    )


@router.put("/orgs/{org_id}/features/{feature_id}", response_model=ApiResponse[dict])
async def set_org_feature(
    org_id: str,
    feature_id: str,
    body: FeatureOverrideIn,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    await feature_admin_service.set_override(
        db, admin=admin, org_id=org_id, feature_id=feature_id,
        enabled=body.enabled, reason=body.reason,
    )
    await db.commit()
    return ApiResponse[dict](
        data=await feature_admin_service.resolve_org_feature(
            db, org_id=org_id, feature_id=feature_id
        )
    )


@router.delete("/orgs/{org_id}/features/{feature_id}", response_model=ApiResponse[dict])
async def clear_org_feature(
    org_id: str,
    feature_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    await feature_admin_service.clear_override(
        db, admin=admin, org_id=org_id, feature_id=feature_id,
    )
    await db.commit()
    return ApiResponse[dict](
        data=await feature_admin_service.resolve_org_feature(
            db, org_id=org_id, feature_id=feature_id
        )
    )
```

- [ ] **Step 3: 验证通过**

```bash
uv run pytest ee/backend/api/admin/test_features_api.py -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add ee/backend/api/admin/features.py ee/backend/api/admin/test_features_api.py
git commit -m "feat(admin): Feature override endpoint"
```

---

### Task 15: `admin/audit.py`

**Files:**
- Create: `ee/backend/api/admin/audit.py`
- Create: `ee/backend/api/admin/test_audit_api.py`

- [ ] **Step 1: 写测试**

```python
# ee/backend/api/admin/test_audit_api.py
import pytest


@pytest.mark.asyncio
async def test_audit_actions_returns_enum_values(async_client, super_admin_token):
    resp = await async_client.get(
        "/admin/audit/actions",
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert resp.status_code == 200
    values = resp.json()["data"]
    assert "org.create" in values
    assert "user.reset_password" in values
    assert "auth.login_failed" in values


@pytest.mark.asyncio
async def test_audit_list_paginated(async_client, super_admin_token):
    resp = await async_client.get(
        "/admin/audit?page=1&page_size=5",
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert resp.status_code == 200
    assert "pagination" in resp.json()


@pytest.mark.asyncio
async def test_audit_invalid_action_rejected(async_client, super_admin_token):
    resp = await async_client.get(
        "/admin/audit?action=not.a.real.action",
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["error_code"] == 40980
```

- [ ] **Step 2: 实现**

```python
# ee/backend/api/admin/audit.py
"""超管审计查询 endpoint。"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_super_admin_dep
from app.models.admin_action import AdminAction
from app.models.user import User
from app.schemas.common import ApiResponse, PaginatedResponse, Pagination
from ee.backend.services.admin import audit_service
from ee.backend.services.admin.errors import AdminErrorCode, raise_admin_error

router = APIRouter()


@router.get("/audit/actions", response_model=ApiResponse[list[str]])
async def list_audit_actions(
    admin: User = Depends(require_super_admin_dep),
):
    """前端筛选下拉数据源：所有 AdminAction enum value。"""
    return ApiResponse[list[str]](data=[a.value for a in AdminAction])


@router.get("/audit", response_model=PaginatedResponse[dict])
async def list_audit(
    actor: str | None = Query(None),
    action: str | None = Query(None),
    from_ts: datetime | None = Query(None, alias="from"),
    to_ts: datetime | None = Query(None, alias="to"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    if from_ts and to_ts and from_ts > to_ts:
        raise_admin_error(
            AdminErrorCode.AUDIT_TIME_RANGE_INVALID,
            message_key="errors.admin.audit_time_range_invalid",
            message="from must be <= to",
        )
    action_enum: AdminAction | None = None
    if action:
        try:
            action_enum = AdminAction(action)
        except ValueError:
            raise_admin_error(
                AdminErrorCode.AUDIT_ACTION_INVALID,
                message_key="errors.admin.audit_action_invalid",
                message=f"Invalid action: {action}",
            )
    rows, total = await audit_service.query_audit_logs(
        db, actor_id=actor, action=action_enum,
        from_dt=from_ts, to_dt=to_ts, page=page, page_size=page_size,
    )
    data = [
        {
            "id": r.id,
            "action": r.action,
            "actor_id": r.actor_id,
            "actor_name": r.actor_name,
            "actor_type": r.actor_type,
            "target_type": r.target_type,
            "target_id": r.target_id,
            "org_id": r.org_id,
            "details": r.details,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
    return PaginatedResponse[dict](
        data=data,
        pagination=Pagination(page=page, page_size=page_size, total=total),
    )
```

- [ ] **Step 3: 验证通过**

```bash
uv run pytest ee/backend/api/admin/test_audit_api.py -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add ee/backend/api/admin/audit.py ee/backend/api/admin/test_audit_api.py
git commit -m "feat(admin): 审计日志查询 endpoint"
```

---

### Task 16: 注册新路由 + 双守卫挂载

**Files:**
- Modify: `ee/backend/router.py`

- [ ] **Step 1: 阅读现有 router 注册**

```bash
cat ee/backend/router.py
```

- [ ] **Step 2: 追加新 router**

```python
# ee/backend/router.py 中新增引用：
from ee.backend.api.admin import audit as admin_audit
from ee.backend.api.admin import features as admin_features
from ee.backend.api.admin import users as admin_users
from app.core.deps import require_feature, require_super_admin_dep
from fastapi import Depends

admin_deps = [
    Depends(require_feature("platform_admin")),
    Depends(require_super_admin_dep),
]

# 已有：admin_organizations
router.include_router(
    admin_users.router,
    prefix="/admin/users",
    tags=["admin-users"],
    dependencies=admin_deps,
)
router.include_router(
    admin_features.router,
    prefix="/admin",  # 内含 /features/* 与 /orgs/:id/features/*
    tags=["admin-features"],
    dependencies=admin_deps,
)
router.include_router(
    admin_audit.router,
    prefix="/admin",
    tags=["admin-audit"],
    dependencies=admin_deps,
)
```

并把已有 `admin_organizations` 的注册改为带 `dependencies=admin_deps`（如原本只挂了 `require_super_admin_dep`，补 `require_feature("platform_admin")`）。

- [ ] **Step 3: 启动 backend，浏览 `/docs` 验证新 endpoint 出现**

```bash
cd nodeskclaw-backend
uv run uvicorn app.main:app --reload --port 4510
# 另开终端 curl
curl -s http://localhost:4510/docs | head -1
```

Expected: HTTP 200。endpoint 出现在 OpenAPI schema。

- [ ] **Step 4: Commit**

```bash
git add ee/backend/router.py
git commit -m "feat(admin): 挂载用户/Feature/审计 admin 路由 + 双守卫"
```

---

## Phase 4 — 最低安全审计 + 保留期 Job

### Task 17: Auth 路径登录成功/失败/登出审计

**Files:**
- Modify: `nodeskclaw-backend/app/api/auth.py`
- Create: `nodeskclaw-backend/tests/api/test_auth_audit.py`

- [ ] **Step 1: 阅读现有 auth 登录路径**

```bash
ls nodeskclaw-backend/app/api/auth.py
```

Read `nodeskclaw-backend/app/api/auth.py`，找到登录、登录失败、登出三个分支位置。

- [ ] **Step 2: 写失败测试**

```python
# nodeskclaw-backend/tests/api/test_auth_audit.py
"""auth 审计落库测试。"""

import pytest
from sqlalchemy import select

from app.models.operation_audit_log import OperationAuditLog


@pytest.mark.asyncio
async def test_login_success_writes_audit(async_client, db_session, registered_user):
    await async_client.post("/auth/login", json={
        "email": registered_user.email, "password": "correct-password",
    })
    rows = (await db_session.execute(
        select(OperationAuditLog).where(OperationAuditLog.action == "auth.login_success")
    )).scalars().all()
    assert rows
    assert rows[-1].actor_id == registered_user.id


@pytest.mark.asyncio
async def test_login_failure_writes_audit_without_password(
    async_client, db_session, registered_user
):
    await async_client.post("/auth/login", json={
        "email": registered_user.email, "password": "wrong-password",
    })
    rows = (await db_session.execute(
        select(OperationAuditLog).where(OperationAuditLog.action == "auth.login_failed")
    )).scalars().all()
    assert rows
    row = rows[-1]
    assert row.actor_type == "anonymous"
    assert row.actor_id == "anonymous"
    assert row.details.get("attempted_email") == registered_user.email
    payload = str(row.details)
    assert "wrong-password" not in payload  # 严禁记录密码


@pytest.mark.asyncio
async def test_logout_writes_audit(async_client, db_session, super_admin_token, super_admin_user):
    await async_client.post(
        "/auth/logout", headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    rows = (await db_session.execute(
        select(OperationAuditLog).where(OperationAuditLog.action == "auth.logout")
    )).scalars().all()
    assert rows
    assert rows[-1].actor_id == super_admin_user.id
```

- [ ] **Step 3: 验证失败**

```bash
uv run pytest tests/api/test_auth_audit.py -v
```

Expected: FAIL

- [ ] **Step 4: 在 auth endpoint 三个分支插入审计调用**

在 `app/api/auth.py` 登录成功路径（commit user 之后）追加：
```python
from app.models.admin_action import AdminAction
from ee.backend.services.admin import audit_service

# 登录成功后
async with audit_service.with_audit(
    db,
    action=AdminAction.AUTH_LOGIN_SUCCESS,
    actor=user,
    target_type="auth",
    target_id=user.id,
    actor_ip=request.client.host if request.client else None,
    actor_user_agent=request.headers.get("user-agent"),
):
    pass
await db.commit()
```

登录失败分支（捕获到错误密码 / user 不存在时，在抛 401 之前）：
```python
async with audit_service.with_audit(
    db,
    action=AdminAction.AUTH_LOGIN_FAILED,
    actor=None,
    target_type="auth",
    target_id=body.email or "unknown",
    details={"attempted_email": body.email, "reason": failure_reason},
    actor_ip=request.client.host if request.client else None,
    actor_user_agent=request.headers.get("user-agent"),
):
    pass
await db.commit()
```

登出分支同样。CE 也运行 backend 这一份代码，但 `audit_service` 来自 ee 包；若 CE 模式启动后无 ee 包，import 会失败 — **改为延迟 import 并 try/except 容错**：

```python
def _audit_safe(*args, **kwargs):
    try:
        from ee.backend.services.admin import audit_service
        return audit_service.with_audit(*args, **kwargs)
    except ImportError:
        from contextlib import nullcontext
        return nullcontext()
```

并把上面三处替换为 `_audit_safe(...)` 上下文管理器形式。这样 CE 不破坏，EE 审计正常。

- [ ] **Step 5: 验证通过**

```bash
uv run pytest tests/api/test_auth_audit.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add nodeskclaw-backend/app/api/auth.py \
        nodeskclaw-backend/tests/api/test_auth_audit.py
git commit -m "feat(audit): 登录成功/失败/登出最低安全审计"
```

---

### Task 18: `AuditRetentionRunner` 90 天清理

**Files:**
- Create: `nodeskclaw-backend/app/services/audit_retention_runner.py`
- Modify: `nodeskclaw-backend/app/main.py` — lifespan 注册 start/stop
- Modify: `nodeskclaw-backend/.env.example` — 增加配置项
- Create: `nodeskclaw-backend/tests/services/test_audit_retention_runner.py`

- [ ] **Step 1: 写失败测试**

```python
# nodeskclaw-backend/tests/services/test_audit_retention_runner.py
"""审计 90 天保留清理测试。"""

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.operation_audit_log import OperationAuditLog
from app.services.audit_retention_runner import purge_expired_audit_logs


@pytest.mark.asyncio
async def test_purge_deletes_older_than_threshold(db_session):
    old = OperationAuditLog(
        id=str(uuid.uuid4()),
        action="org.create", target_type="org", target_id="x",
        actor_type="user", actor_id="u",
        created_at=datetime.utcnow() - timedelta(days=95),
    )
    recent = OperationAuditLog(
        id=str(uuid.uuid4()),
        action="org.create", target_type="org", target_id="y",
        actor_type="user", actor_id="u",
        created_at=datetime.utcnow() - timedelta(days=10),
    )
    db_session.add_all([old, recent])
    await db_session.commit()
    deleted = await purge_expired_audit_logs(db_session, retention_days=90, batch_limit=100_000)
    await db_session.commit()
    rows = (await db_session.execute(select(OperationAuditLog))).scalars().all()
    assert deleted >= 1
    ids = {r.id for r in rows}
    assert recent.id in ids
    assert old.id not in ids
```

- [ ] **Step 2: 验证失败**

```bash
uv run pytest tests/services/test_audit_retention_runner.py -v
```

Expected: FAIL

- [ ] **Step 3: 实现 runner**

```python
# nodeskclaw-backend/app/services/audit_retention_runner.py
"""审计日志保留期清理 — 默认 90 天物理删除，沿用 ScheduleRunner 异步轮询模式。

设计参考 docs/superpowers/specs/2026-05-26-super-admin-features-design.md §7.3。
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.session import async_session_maker
from app.models.operation_audit_log import OperationAuditLog

logger = logging.getLogger(__name__)

_DEFAULT_RETENTION_DAYS = int(os.getenv("AUDIT_RETENTION_DAYS", "90"))
_ENABLED = os.getenv("AUDIT_RETENTION_ENABLED", "true").lower() == "true"
_RUN_HOUR_LOCAL = 3  # 每天 03:00


async def purge_expired_audit_logs(
    db: AsyncSession, *, retention_days: int = _DEFAULT_RETENTION_DAYS, batch_limit: int = 100_000
) -> int:
    """单次清理；返回删除行数。分批避免锁表。"""
    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    total_deleted = 0
    while True:
        ids = (
            await db.execute(
                select(OperationAuditLog.id)
                .where(OperationAuditLog.created_at < cutoff)
                .limit(batch_limit)
            )
        ).scalars().all()
        if not ids:
            break
        result = await db.execute(
            delete(OperationAuditLog).where(OperationAuditLog.id.in_(ids))
        )
        total_deleted += result.rowcount or 0
        await db.flush()
        if len(ids) < batch_limit:
            break
    logger.info("[audit_retention] deleted %d rows older than %dd", total_deleted, retention_days)
    return total_deleted


class AuditRetentionRunner:
    """每天 03:00 本地时间触发清理；通过 asyncio 异步任务驱动。"""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()

    async def _loop(self) -> None:
        while not self._stopping.is_set():
            now = datetime.now()
            target = now.replace(hour=_RUN_HOUR_LOCAL, minute=0, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            try:
                await asyncio.wait_for(
                    self._stopping.wait(),
                    timeout=(target - now).total_seconds(),
                )
                return
            except asyncio.TimeoutError:
                pass
            async with async_session_maker() as db:
                try:
                    await purge_expired_audit_logs(db)
                    await db.commit()
                except Exception as exc:  # noqa: BLE001
                    logger.exception("[audit_retention] purge failed: %s", exc)
                    await db.rollback()

    def start(self) -> None:
        if not _ENABLED:
            logger.info("[audit_retention] disabled via env")
            return
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop())
        logger.info("[audit_retention] started (retention=%dd, hour=%02d)", _DEFAULT_RETENTION_DAYS, _RUN_HOUR_LOCAL)

    async def stop(self) -> None:
        self._stopping.set()
        if self._task:
            await self._task


audit_retention_runner = AuditRetentionRunner()
```

- [ ] **Step 4: 在 `main.py` lifespan 中启动 / 停止**

打开 `nodeskclaw-backend/app/main.py`，找到 `lifespan` 函数；在已有启动钩子区域追加：
```python
from app.services.audit_retention_runner import audit_retention_runner

# 启动段
audit_retention_runner.start()

# 关闭段
await audit_retention_runner.stop()
```

- [ ] **Step 5: 追加 `.env.example` 配置项**

在 `nodeskclaw-backend/.env.example` 末尾追加：
```
# 审计保留期（天），默认 90
AUDIT_RETENTION_DAYS=90
# 是否启用每日清理 job
AUDIT_RETENTION_ENABLED=true
```

- [ ] **Step 6: 验证测试通过**

```bash
uv run pytest tests/services/test_audit_retention_runner.py -v
```

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add nodeskclaw-backend/app/services/audit_retention_runner.py \
        nodeskclaw-backend/app/main.py \
        nodeskclaw-backend/.env.example \
        nodeskclaw-backend/tests/services/test_audit_retention_runner.py
git commit -m "feat(audit): 90 天保留期清理 Job 与启动钩子"
```

---

## Phase 5 — 前端基础

### Task 19: 扩展 `adminApi.ts` — 用户/Feature/Audit 方法

**Files:**
- Modify: `nodeskclaw-portal/src/services/adminApi.ts`

- [ ] **Step 1: 阅读现有 adminApi**

```bash
cat nodeskclaw-portal/src/services/adminApi.ts
```

- [ ] **Step 2: 追加类型与方法**

在 `nodeskclaw-portal/src/services/adminApi.ts` 同文件追加：
```typescript
// ───── 用户 ───────────────────────────────────────
export interface AdminUser {
  id: string
  email: string
  name: string | null
  is_active: boolean
  is_super_admin: boolean
  must_change_password: boolean
  created_at: string
  org_count: number
}

export interface AdminUserPatch {
  is_active?: boolean
  is_super_admin?: boolean
}

// ───── 组织成员 ───────────────────────────────────
export interface AdminOrgMember {
  user_id: string
  role: 'admin' | 'operator' | 'member'
  joined_at: string | null
  user_email: string | null
  user_name: string | null
}

// ───── Feature ───────────────────────────────────
export interface AdminFeatureItem {
  feature_id: string
  name: string
  description: string
  default_enabled: boolean
  override_count: number
}

export interface AdminOrgFeatureState {
  feature_id: string
  enabled: boolean
  source: 'default' | 'override'
  default_enabled: boolean
  reason?: string | null
  set_by_user_id?: string | null
  set_at?: string | null
}

// ───── 审计 ───────────────────────────────────────
export interface AdminAuditRow {
  id: string
  action: string
  actor_id: string
  actor_name: string | null
  actor_type: string
  target_type: string
  target_id: string
  org_id: string | null
  details: Record<string, unknown> | null
  created_at: string
}

// 在 useAdminApi() 内 client 后追加方法：
async function fetchUsers(params: { q?: string; page?: number; pageSize?: number } = {}): Promise<{ data: AdminUser[]; pagination: { page: number; page_size: number; total: number } }> {
  const res = await client.get('/admin/users', {
    params: {
      q: params.q,
      page: params.page ?? 1,
      page_size: params.pageSize ?? 20,
    },
  })
  return { data: res.data.data ?? [], pagination: res.data.pagination }
}

async function fetchUser(id: string): Promise<AdminUser> {
  const res = await client.get(`/admin/users/${id}`)
  return res.data.data
}

async function updateUser(id: string, patch: AdminUserPatch): Promise<AdminUser> {
  const res = await client.put(`/admin/users/${id}`, patch)
  return res.data.data
}

async function resetUserPassword(id: string): Promise<{ temp_password: string }> {
  const res = await client.post(`/admin/users/${id}/reset-password`)
  return res.data.data
}

async function deleteUser(id: string): Promise<void> {
  await client.delete(`/admin/users/${id}`)
}

async function fetchOrgMembers(orgId: string): Promise<AdminOrgMember[]> {
  const res = await client.get(`/admin/orgs/${orgId}/members`)
  return res.data.data ?? []
}

async function addOrgMember(orgId: string, userId: string, role: AdminOrgMember['role']): Promise<AdminOrgMember> {
  const res = await client.post(`/admin/orgs/${orgId}/members`, { user_id: userId, role })
  return res.data.data
}

async function updateOrgMember(orgId: string, userId: string, role: AdminOrgMember['role']): Promise<AdminOrgMember> {
  const res = await client.put(`/admin/orgs/${orgId}/members/${userId}`, { role })
  return res.data.data
}

async function removeOrgMember(orgId: string, userId: string): Promise<void> {
  await client.delete(`/admin/orgs/${orgId}/members/${userId}`)
}

async function fetchFeatures(): Promise<AdminFeatureItem[]> {
  const res = await client.get('/admin/features')
  return res.data.data ?? []
}

async function fetchFeatureOverrides(featureId: string, page = 1, pageSize = 20) {
  const res = await client.get(`/admin/features/${featureId}/overrides`, {
    params: { page, page_size: pageSize },
  })
  return { data: res.data.data ?? [], pagination: res.data.pagination }
}

async function fetchOrgFeatures(orgId: string): Promise<AdminOrgFeatureState[]> {
  const res = await client.get(`/admin/orgs/${orgId}/features`)
  return res.data.data ?? []
}

async function setOrgFeature(orgId: string, featureId: string, enabled: boolean, reason?: string): Promise<AdminOrgFeatureState> {
  const res = await client.put(`/admin/orgs/${orgId}/features/${featureId}`, { enabled, reason })
  return res.data.data
}

async function clearOrgFeature(orgId: string, featureId: string): Promise<AdminOrgFeatureState> {
  const res = await client.delete(`/admin/orgs/${orgId}/features/${featureId}`)
  return res.data.data
}

async function fetchAuditActions(): Promise<string[]> {
  const res = await client.get('/admin/audit/actions')
  return res.data.data ?? []
}

async function fetchAuditLogs(params: {
  actor?: string
  action?: string
  from?: string
  to?: string
  page?: number
  pageSize?: number
} = {}) {
  const res = await client.get('/admin/audit', {
    params: {
      actor: params.actor,
      action: params.action,
      from: params.from,
      to: params.to,
      page: params.page ?? 1,
      page_size: params.pageSize ?? 20,
    },
  })
  return { data: res.data.data as AdminAuditRow[], pagination: res.data.pagination }
}
```

并在 `useAdminApi` 的 return 块中追加上述方法名。

- [ ] **Step 3: TS 类型检查**

```bash
cd nodeskclaw-portal
npm run build
```

Expected: 构建成功，无 TS 错误。

- [ ] **Step 4: Commit**

```bash
git add nodeskclaw-portal/src/services/adminApi.ts
git commit -m "feat(portal): 扩展 adminApi 客户端覆盖 users/features/audit"
```

---

### Task 20: `AdminLayout.vue` + 路由更新

**Files:**
- Create: `nodeskclaw-portal/src/views/admin/AdminLayout.vue`
- Modify: `nodeskclaw-portal/src/router/index.ts`

- [ ] **Step 1: 实现 AdminLayout**

```vue
<!-- nodeskclaw-portal/src/views/admin/AdminLayout.vue -->
<template>
  <div class="admin-layout flex h-screen bg-gray-50">
    <!-- 侧边栏：超管后台一级入口 -->
    <aside class="w-56 border-r bg-white">
      <div class="px-4 py-4 border-b">
        <button class="text-sm text-gray-500 hover:text-gray-900" @click="goPortal">
          <Home :size="14" class="inline mr-1" /> 返回门户
        </button>
      </div>
      <nav class="px-2 py-3">
        <RouterLink
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          class="flex items-center gap-2 px-3 py-2 text-sm rounded hover:bg-gray-100"
          active-class="bg-gray-100 font-medium text-gray-900"
        >
          <component :is="item.icon" :size="16" />
          {{ item.label }}
        </RouterLink>
      </nav>
    </aside>
    <main class="flex-1 overflow-auto">
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { Home, Building2, Users, ToggleLeft, ClipboardList } from 'lucide-vue-next'

interface NavItem {
  to: string
  label: string
  icon: any
}

const navItems: NavItem[] = [
  { to: '/admin/orgs', label: '组织', icon: Building2 },
  { to: '/admin/users', label: '用户', icon: Users },
  { to: '/admin/features', label: '功能开关', icon: ToggleLeft },
  { to: '/admin/audit', label: '审计日志', icon: ClipboardList },
]

const router = useRouter()
function goPortal() { router.push('/') }
</script>
```

- [ ] **Step 2: 修改路由**

打开 `nodeskclaw-portal/src/router/index.ts`，找到 admin 区域，替换为嵌套结构：
```typescript
import AdminLayout from '@/views/admin/AdminLayout.vue'
import AdminOrgList from '@/views/admin/AdminOrgList.vue'
import AdminOrgDetail from '@/views/admin/AdminOrgDetail.vue'
import AdminUserList from '@/views/admin/AdminUserList.vue'
import AdminUserDetail from '@/views/admin/AdminUserDetail.vue'
import AdminFeatureList from '@/views/admin/AdminFeatureList.vue'
import AdminAuditLog from '@/views/admin/AdminAuditLog.vue'

// 已有 router 路由数组中追加：
{
  path: '/admin',
  component: AdminLayout,
  meta: { requiresAuth: true, requiresSuperAdmin: true, edition: 'ee' },
  children: [
    { path: '', redirect: '/admin/orgs' },
    { path: 'orgs', component: AdminOrgList },
    { path: 'orgs/:id', component: AdminOrgDetail, props: true },
    { path: 'users', component: AdminUserList },
    { path: 'users/:id', component: AdminUserDetail, props: true },
    { path: 'features', component: AdminFeatureList },
    { path: 'audit', component: AdminAuditLog },
  ],
},
```

并补全 navigation guard：未登录 → /login；非超管 → /；edition='ce' → /。

- [ ] **Step 3: 构建检查（页面文件尚未创建，先用占位防 build 失败）**

为后续 5 个新视图临时创建占位文件，内容：
```vue
<template><div class="p-6">TODO</div></template>
<script setup lang="ts"></script>
```

文件：
- `nodeskclaw-portal/src/views/admin/AdminOrgDetail.vue`
- `nodeskclaw-portal/src/views/admin/AdminUserList.vue`
- `nodeskclaw-portal/src/views/admin/AdminUserDetail.vue`
- `nodeskclaw-portal/src/views/admin/AdminFeatureList.vue`
- `nodeskclaw-portal/src/views/admin/AdminAuditLog.vue`

```bash
cd nodeskclaw-portal && npm run build
```

Expected: 构建成功。

- [ ] **Step 4: Commit**

```bash
git add nodeskclaw-portal/src/views/admin/ nodeskclaw-portal/src/router/
git commit -m "feat(portal): AdminLayout 侧边栏 + 嵌套路由 + 视图占位"
```

---

## Phase 6 — 前端页面

### Task 21: 增强 `AdminOrgList.vue`（编辑按钮真正工作 + 行点击进详情）

**Files:**
- Modify: `nodeskclaw-portal/src/views/admin/AdminOrgList.vue`
- Create: `nodeskclaw-portal/src/views/admin/AdminOrgList.spec.ts`

- [ ] **Step 1: 写最小渲染测试**

```typescript
// nodeskclaw-portal/src/views/admin/AdminOrgList.spec.ts
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import AdminOrgList from './AdminOrgList.vue'

vi.mock('@/services/adminApi', () => ({
  useAdminApi: () => ({
    fetchOrgs: vi.fn().mockResolvedValue([
      { id: 'o1', name: 'Org1', slug: 'org-1', plan: 'free', is_active: true,
        max_instances: 1, max_cpu_total: '4', max_mem_total: '8Gi',
        max_storage_total: '500Gi', max_collaboration_depth: 3,
        cluster_id: null, cluster_name: null, instance_count: 0,
        total_cpu: '0', total_mem: '0', storage_used: '0',
        created_at: '2026-05-01', updated_at: '2026-05-01' },
    ]),
  }),
}))

describe('AdminOrgList', () => {
  it('renders org rows', async () => {
    const wrapper = mount(AdminOrgList, { global: { stubs: ['router-link'] } })
    await new Promise(r => setTimeout(r))
    expect(wrapper.text()).toContain('Org1')
  })
})
```

- [ ] **Step 2: 修改 `AdminOrgList.vue`**

具体改动：
1. 把"编辑"按钮 onClick 改为打开编辑弹窗（复用现有创建弹窗结构，预填字段）
2. 表格行追加 `@click="router.push('/admin/orgs/' + org.id)"`，按钮区 `@click.stop` 防冒泡

代码片段（伪示意，按现有 AdminOrgList 结构调整）：
```vue
<tr
  v-for="org in orgs"
  :key="org.id"
  class="hover:bg-gray-50 cursor-pointer"
  @click="$router.push(`/admin/orgs/${org.id}`)"
>
  <td>{{ org.name }}</td>
  ...
  <td @click.stop>
    <button @click="openEdit(org)">编辑</button>
    <button @click="confirmDelete(org)">删除</button>
  </td>
</tr>
```

`openEdit(org)` 应预填 `editingOrg.value = { ...org }` 并设 `isEditing.value = true`；提交时调用 `updateOrg(id, payload)` 而非 `createOrg`。

- [ ] **Step 3: 验证测试通过**

```bash
cd nodeskclaw-portal
npm run test -- --run src/views/admin/AdminOrgList.spec.ts
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add nodeskclaw-portal/src/views/admin/AdminOrgList.vue \
        nodeskclaw-portal/src/views/admin/AdminOrgList.spec.ts
git commit -m "feat(portal): AdminOrgList 编辑按钮启用 + 行点击进详情"
```

---

### Task 22: `AdminOrgDetail.vue` — Overview / Members / Features 三 tab

**Files:**
- Modify: `nodeskclaw-portal/src/views/admin/AdminOrgDetail.vue`（替换占位）
- Create: `nodeskclaw-portal/src/views/admin/AdminOrgDetail.spec.ts`

- [ ] **Step 1: 写测试**

```typescript
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import AdminOrgDetail from './AdminOrgDetail.vue'

vi.mock('@/services/adminApi', () => ({
  useAdminApi: () => ({
    fetchOrg: vi.fn().mockResolvedValue({
      id: 'o1', name: 'Org1', slug: 'org-1', plan: 'free', is_active: true,
      max_instances: 1, max_cpu_total: '4', max_mem_total: '8Gi',
      max_storage_total: '500Gi', max_collaboration_depth: 3,
      cluster_id: null, cluster_name: null, instance_count: 0,
      total_cpu: '0', total_mem: '0', storage_used: '0',
      created_at: '2026-05-01', updated_at: '2026-05-01',
    }),
    fetchOrgMembers: vi.fn().mockResolvedValue([]),
    fetchOrgFeatures: vi.fn().mockResolvedValue([]),
  }),
}))

describe('AdminOrgDetail', () => {
  it('renders all three tabs', async () => {
    const wrapper = mount(AdminOrgDetail, {
      props: { id: 'o1' },
      global: { stubs: ['router-link'] },
    })
    await new Promise(r => setTimeout(r, 10))
    expect(wrapper.text()).toContain('概览')
    expect(wrapper.text()).toContain('成员')
    expect(wrapper.text()).toContain('功能开关')
  })
})
```

- [ ] **Step 2: 实现**

```vue
<!-- nodeskclaw-portal/src/views/admin/AdminOrgDetail.vue -->
<template>
  <div class="p-6 space-y-6">
    <div class="flex items-center gap-2">
      <RouterLink to="/admin/orgs" class="text-sm text-gray-500 hover:text-gray-900">
        ← 返回组织列表
      </RouterLink>
    </div>
    <h2 class="text-2xl font-semibold" v-if="org">{{ org.name }}</h2>

    <!-- Tab 切换 -->
    <div class="flex gap-2 border-b">
      <button
        v-for="t in tabs"
        :key="t.value"
        class="px-3 py-2 text-sm"
        :class="active === t.value ? 'border-b-2 border-blue-600 text-blue-600' : 'text-gray-600'"
        @click="active = t.value"
      >
        {{ t.label }}
      </button>
    </div>

    <!-- Overview -->
    <section v-if="active === 'overview'" v-show="org">
      <dl class="grid grid-cols-2 gap-y-2 text-sm">
        <dt>Slug</dt><dd>{{ org?.slug }}</dd>
        <dt>Plan</dt><dd>{{ org?.plan }}</dd>
        <dt>实例数</dt><dd>{{ org?.instance_count }} / {{ org?.max_instances }}</dd>
        <dt>CPU</dt><dd>{{ org?.total_cpu }} / {{ org?.max_cpu_total }}</dd>
        <dt>内存</dt><dd>{{ org?.total_mem }} / {{ org?.max_mem_total }}</dd>
        <dt>存储</dt><dd>{{ org?.storage_used }} / {{ org?.max_storage_total }}</dd>
      </dl>
    </section>

    <!-- Members -->
    <section v-else-if="active === 'members'">
      <table class="w-full text-sm">
        <thead><tr><th>用户</th><th>角色</th><th>加入时间</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="m in members" :key="m.user_id">
            <td>{{ m.user_email || m.user_id }}</td>
            <td>
              <select :value="m.role" @change="onRoleChange(m, $event)">
                <option value="admin">admin</option>
                <option value="operator">operator</option>
                <option value="member">member</option>
              </select>
            </td>
            <td>{{ m.joined_at }}</td>
            <td><button @click="onRemove(m)">移除</button></td>
          </tr>
        </tbody>
      </table>
      <!-- 添加成员表单 略，下一 task 完成 -->
    </section>

    <!-- Features -->
    <section v-else>
      <table class="w-full text-sm">
        <thead><tr><th>Feature</th><th>状态</th><th>来源</th><th>原因</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="f in features" :key="f.feature_id">
            <td>{{ f.feature_id }}</td>
            <td>{{ f.enabled ? '开' : '关' }}</td>
            <td>{{ f.source }}（默认 {{ f.default_enabled ? '开' : '关' }}）</td>
            <td>{{ f.reason ?? '-' }}</td>
            <td>
              <button @click="onSetFeature(f, true)">强制开</button>
              <button @click="onSetFeature(f, false)">强制关</button>
              <button v-if="f.source === 'override'" @click="onClearFeature(f)">恢复默认</button>
            </td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useAdminApi, type AdminOrg, type AdminOrgMember, type AdminOrgFeatureState } from '@/services/adminApi'

interface Props { id: string }
const props = defineProps<Props>()
const api = useAdminApi()

const tabs = [
  { value: 'overview', label: '概览' },
  { value: 'members', label: '成员' },
  { value: 'features', label: '功能开关' },
]
const active = ref<'overview' | 'members' | 'features'>('overview')

const org = ref<AdminOrg | null>(null)
const members = ref<AdminOrgMember[]>([])
const features = ref<AdminOrgFeatureState[]>([])

onMounted(async () => {
  org.value = await api.fetchOrg(props.id)
  members.value = await api.fetchOrgMembers(props.id)
  features.value = await api.fetchOrgFeatures(props.id)
})

async function onRoleChange(m: AdminOrgMember, ev: Event) {
  const role = (ev.target as HTMLSelectElement).value as AdminOrgMember['role']
  await api.updateOrgMember(props.id, m.user_id, role)
  members.value = await api.fetchOrgMembers(props.id)
}
async function onRemove(m: AdminOrgMember) {
  if (!confirm(`移除 ${m.user_email}？`)) return
  await api.removeOrgMember(props.id, m.user_id)
  members.value = await api.fetchOrgMembers(props.id)
}
async function onSetFeature(f: AdminOrgFeatureState, enabled: boolean) {
  const reason = window.prompt('原因（可选）') || undefined
  await api.setOrgFeature(props.id, f.feature_id, enabled, reason)
  features.value = await api.fetchOrgFeatures(props.id)
}
async function onClearFeature(f: AdminOrgFeatureState) {
  await api.clearOrgFeature(props.id, f.feature_id)
  features.value = await api.fetchOrgFeatures(props.id)
}
</script>
```

- [ ] **Step 3: 验证测试通过 + 手测页面**

```bash
npm run test -- --run src/views/admin/AdminOrgDetail.spec.ts
npm run dev  # http://localhost:4517/admin/orgs/<id>
```

Expected: PASS；浏览器 tab 切换正常，无 console error。

- [ ] **Step 4: Commit**

```bash
git add nodeskclaw-portal/src/views/admin/AdminOrgDetail.vue \
        nodeskclaw-portal/src/views/admin/AdminOrgDetail.spec.ts
git commit -m "feat(portal): AdminOrgDetail Overview/Members/Features 三 tab"
```

---

### Task 23: `AdminUserList.vue`

**Files:**
- Modify: `nodeskclaw-portal/src/views/admin/AdminUserList.vue`
- Create: `nodeskclaw-portal/src/views/admin/AdminUserList.spec.ts`

- [ ] **Step 1: 写测试**

```typescript
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import AdminUserList from './AdminUserList.vue'

vi.mock('@/services/adminApi', () => ({
  useAdminApi: () => ({
    fetchUsers: vi.fn().mockResolvedValue({
      data: [{
        id: 'u1', email: 'a@example.com', name: null,
        is_active: true, is_super_admin: false, must_change_password: false,
        created_at: '2026-05-01', org_count: 2,
      }],
      pagination: { page: 1, page_size: 20, total: 1 },
    }),
  }),
}))

describe('AdminUserList', () => {
  it('renders users', async () => {
    const wrapper = mount(AdminUserList, { global: { stubs: ['router-link'] } })
    await new Promise(r => setTimeout(r, 10))
    expect(wrapper.text()).toContain('a@example.com')
  })
})
```

- [ ] **Step 2: 实现**

```vue
<!-- nodeskclaw-portal/src/views/admin/AdminUserList.vue -->
<template>
  <div class="p-6 space-y-4">
    <h2 class="text-2xl font-semibold">用户管理</h2>
    <input
      v-model="q"
      class="border rounded px-2 py-1 text-sm w-64"
      placeholder="按 email/name 搜索"
      @keyup.enter="reload(1)"
    />
    <table class="w-full text-sm">
      <thead><tr>
        <th>Email</th><th>姓名</th><th>超管</th><th>启用</th><th>所属组织数</th><th>创建时间</th><th>操作</th>
      </tr></thead>
      <tbody>
        <tr v-for="u in users" :key="u.id" class="hover:bg-gray-50 cursor-pointer"
            @click="$router.push(`/admin/users/${u.id}`)">
          <td>{{ u.email }}</td>
          <td>{{ u.name ?? '-' }}</td>
          <td>{{ u.is_super_admin ? '是' : '否' }}</td>
          <td>{{ u.is_active ? '是' : '否' }}</td>
          <td>{{ u.org_count }}</td>
          <td>{{ u.created_at }}</td>
          <td @click.stop>
            <button @click="onReset(u)">重置密码</button>
            <button @click="onToggleActive(u)">{{ u.is_active ? '禁用' : '启用' }}</button>
          </td>
        </tr>
      </tbody>
    </table>
    <div class="flex gap-2 items-center">
      <button :disabled="page === 1" @click="reload(page - 1)">上一页</button>
      <span class="text-sm">第 {{ page }} 页 / 共 {{ Math.ceil(total / pageSize) }} 页</span>
      <button :disabled="page * pageSize >= total" @click="reload(page + 1)">下一页</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useAdminApi, type AdminUser } from '@/services/adminApi'

const api = useAdminApi()
const q = ref('')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const users = ref<AdminUser[]>([])

async function reload(p = page.value) {
  page.value = p
  const res = await api.fetchUsers({ q: q.value || undefined, page: p, pageSize: pageSize.value })
  users.value = res.data
  total.value = res.pagination.total
}
onMounted(() => reload(1))

async function onReset(u: AdminUser) {
  if (!confirm(`为 ${u.email} 重置密码？将生成一次性临时密码。`)) return
  const { temp_password } = await api.resetUserPassword(u.id)
  window.alert(`临时密码：${temp_password}\n请复制并交付用户，关闭后无法再次查看。`)
}

async function onToggleActive(u: AdminUser) {
  await api.updateUser(u.id, { is_active: !u.is_active })
  await reload()
}
</script>
```

- [ ] **Step 3: 验证测试 + 手测**

```bash
npm run test -- --run src/views/admin/AdminUserList.spec.ts
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add nodeskclaw-portal/src/views/admin/AdminUserList.vue \
        nodeskclaw-portal/src/views/admin/AdminUserList.spec.ts
git commit -m "feat(portal): AdminUserList 全局用户列表 + 搜索 + 分页"
```

---

### Task 24: `AdminUserDetail.vue`

**Files:**
- Modify: `nodeskclaw-portal/src/views/admin/AdminUserDetail.vue`
- Create: `nodeskclaw-portal/src/views/admin/AdminUserDetail.spec.ts`

- [ ] **Step 1: 写测试**

```typescript
import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import AdminUserDetail from './AdminUserDetail.vue'

vi.mock('@/services/adminApi', () => ({
  useAdminApi: () => ({
    fetchUser: vi.fn().mockResolvedValue({
      id: 'u1', email: 'a@example.com', name: 'Alice',
      is_active: true, is_super_admin: false, must_change_password: false,
      created_at: '2026-05-01', org_count: 2,
    }),
    resetUserPassword: vi.fn().mockResolvedValue({ temp_password: 'TEMPpwd1234' }),
    updateUser: vi.fn().mockResolvedValue({}),
  }),
}))

describe('AdminUserDetail', () => {
  it('shows user info and triggers reset password', async () => {
    const wrapper = mount(AdminUserDetail, {
      props: { id: 'u1' }, global: { stubs: ['router-link'] },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('a@example.com')
  })
})
```

- [ ] **Step 2: 实现**

```vue
<!-- nodeskclaw-portal/src/views/admin/AdminUserDetail.vue -->
<template>
  <div class="p-6 space-y-6 max-w-2xl">
    <RouterLink to="/admin/users" class="text-sm text-gray-500">← 返回用户列表</RouterLink>
    <h2 class="text-2xl font-semibold" v-if="user">{{ user.email }}</h2>
    <dl v-if="user" class="grid grid-cols-2 gap-y-2 text-sm">
      <dt>姓名</dt><dd>{{ user.name ?? '-' }}</dd>
      <dt>创建时间</dt><dd>{{ user.created_at }}</dd>
      <dt>所属组织数</dt><dd>{{ user.org_count }}</dd>
      <dt>需强制改密</dt><dd>{{ user.must_change_password ? '是' : '否' }}</dd>
    </dl>
    <div class="flex gap-3 items-center" v-if="user">
      <label class="flex items-center gap-2 text-sm">
        <input type="checkbox" :checked="user.is_active" @change="toggle('is_active')" />
        启用
      </label>
      <label class="flex items-center gap-2 text-sm">
        <input type="checkbox" :checked="user.is_super_admin" @change="toggle('is_super_admin')" />
        超管
      </label>
    </div>
    <button class="border px-3 py-1 rounded" @click="onReset" v-if="user">重置密码</button>

    <!-- 临时密码弹窗 -->
    <div v-if="tempPwd" class="fixed inset-0 bg-black/40 flex items-center justify-center">
      <div class="bg-white p-6 rounded shadow w-96 space-y-3">
        <h3 class="text-lg font-semibold">临时密码（仅本次可见）</h3>
        <pre class="bg-gray-100 px-3 py-2 select-all">{{ tempPwd }}</pre>
        <div class="flex gap-2">
          <button @click="copy" class="border px-3 py-1 rounded">复制</button>
          <button @click="close" :disabled="!copied" class="border px-3 py-1 rounded">
            我已记下
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useAdminApi, type AdminUser } from '@/services/adminApi'

interface Props { id: string }
const props = defineProps<Props>()
const api = useAdminApi()
const user = ref<AdminUser | null>(null)
const tempPwd = ref<string | null>(null)
const copied = ref(false)

onMounted(async () => { user.value = await api.fetchUser(props.id) })

async function toggle(key: 'is_active' | 'is_super_admin') {
  if (!user.value) return
  const newVal = !user.value[key]
  if (!confirm(`确认将 ${key}=${newVal}？`)) return
  await api.updateUser(user.value.id, { [key]: newVal } as any)
  user.value = await api.fetchUser(props.id)
}
async function onReset() {
  if (!user.value) return
  if (!confirm(`为 ${user.value.email} 重置密码？`)) return
  const r = await api.resetUserPassword(user.value.id)
  tempPwd.value = r.temp_password
  copied.value = false
}
async function copy() {
  if (!tempPwd.value) return
  await navigator.clipboard.writeText(tempPwd.value)
  copied.value = true
}
function close() { tempPwd.value = null }
</script>
```

- [ ] **Step 3: 验证测试 + 手测**

```bash
npm run test -- --run src/views/admin/AdminUserDetail.spec.ts
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add nodeskclaw-portal/src/views/admin/AdminUserDetail.vue \
        nodeskclaw-portal/src/views/admin/AdminUserDetail.spec.ts
git commit -m "feat(portal): AdminUserDetail 状态切换 + 重置密码弹窗"
```

---

### Task 25: `AdminFeatureList.vue` + 抽屉

**Files:**
- Modify: `nodeskclaw-portal/src/views/admin/AdminFeatureList.vue`
- Create: `nodeskclaw-portal/src/views/admin/AdminFeatureList.spec.ts`

- [ ] **Step 1: 写测试**

```typescript
import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import AdminFeatureList from './AdminFeatureList.vue'

vi.mock('@/services/adminApi', () => ({
  useAdminApi: () => ({
    fetchFeatures: vi.fn().mockResolvedValue([{
      feature_id: 'knowledge_base', name: 'KB', description: '...',
      default_enabled: false, override_count: 2,
    }]),
    fetchFeatureOverrides: vi.fn().mockResolvedValue({
      data: [], pagination: { page: 1, page_size: 20, total: 0 },
    }),
  }),
}))

describe('AdminFeatureList', () => {
  it('renders feature rows with override count', async () => {
    const wrapper = mount(AdminFeatureList, { global: { stubs: ['router-link'] } })
    await flushPromises()
    expect(wrapper.text()).toContain('knowledge_base')
    expect(wrapper.text()).toContain('2')
  })
})
```

- [ ] **Step 2: 实现**

```vue
<!-- nodeskclaw-portal/src/views/admin/AdminFeatureList.vue -->
<template>
  <div class="p-6 space-y-4">
    <h2 class="text-2xl font-semibold">功能开关</h2>
    <table class="w-full text-sm">
      <thead><tr><th>Feature</th><th>名称</th><th>描述</th><th>默认</th><th>覆盖</th></tr></thead>
      <tbody>
        <tr v-for="f in features" :key="f.feature_id"
            class="hover:bg-gray-50 cursor-pointer"
            @click="openDrawer(f)">
          <td>{{ f.feature_id }}</td>
          <td>{{ f.name }}</td>
          <td>{{ f.description }}</td>
          <td>{{ f.default_enabled ? '开' : '关' }}</td>
          <td>{{ f.override_count }} 个组织</td>
        </tr>
      </tbody>
    </table>

    <aside v-if="drawerFeature" class="fixed top-0 right-0 h-full w-[480px] bg-white shadow-xl border-l p-6 overflow-auto">
      <div class="flex justify-between items-center mb-4">
        <h3 class="text-lg font-semibold">{{ drawerFeature.feature_id }} 的组织覆盖</h3>
        <button @click="drawerFeature = null">关闭</button>
      </div>
      <table class="w-full text-sm">
        <thead><tr><th>组织</th><th>状态</th><th>理由</th><th>时间</th><th></th></tr></thead>
        <tbody>
          <tr v-for="o in overrides" :key="o.org_id">
            <td>{{ o.org_id }}</td>
            <td>{{ o.enabled ? '强制开' : '强制关' }}</td>
            <td>{{ o.reason ?? '-' }}</td>
            <td>{{ o.set_at }}</td>
            <td><button @click="onClear(o)">清除</button></td>
          </tr>
        </tbody>
      </table>
    </aside>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useAdminApi, type AdminFeatureItem } from '@/services/adminApi'

const api = useAdminApi()
const features = ref<AdminFeatureItem[]>([])
const drawerFeature = ref<AdminFeatureItem | null>(null)
const overrides = ref<any[]>([])

onMounted(async () => { features.value = await api.fetchFeatures() })

async function openDrawer(f: AdminFeatureItem) {
  drawerFeature.value = f
  const res = await api.fetchFeatureOverrides(f.feature_id)
  overrides.value = res.data
}
async function onClear(o: any) {
  if (!drawerFeature.value) return
  if (!confirm('清除 override？')) return
  await api.clearOrgFeature(o.org_id, drawerFeature.value.feature_id)
  await openDrawer(drawerFeature.value)
  features.value = await api.fetchFeatures()
}
</script>
```

- [ ] **Step 3: 验证测试 + 手测**

```bash
npm run test -- --run src/views/admin/AdminFeatureList.spec.ts
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add nodeskclaw-portal/src/views/admin/AdminFeatureList.vue \
        nodeskclaw-portal/src/views/admin/AdminFeatureList.spec.ts
git commit -m "feat(portal): AdminFeatureList 主轴视图 + 覆盖抽屉"
```

---

### Task 26: `AdminAuditLog.vue`

**Files:**
- Modify: `nodeskclaw-portal/src/views/admin/AdminAuditLog.vue`
- Create: `nodeskclaw-portal/src/views/admin/AdminAuditLog.spec.ts`

- [ ] **Step 1: 写测试**

```typescript
import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import AdminAuditLog from './AdminAuditLog.vue'

vi.mock('@/services/adminApi', () => ({
  useAdminApi: () => ({
    fetchAuditActions: vi.fn().mockResolvedValue(['org.create', 'user.update']),
    fetchAuditLogs: vi.fn().mockResolvedValue({
      data: [{
        id: 'a1', action: 'org.create',
        actor_id: 'u1', actor_name: 'admin@example.com', actor_type: 'user',
        target_type: 'org', target_id: 'o1', org_id: 'o1',
        details: { status: 'success' },
        created_at: '2026-05-01T10:00:00Z',
      }],
      pagination: { page: 1, page_size: 20, total: 1 },
    }),
  }),
}))

describe('AdminAuditLog', () => {
  it('renders rows', async () => {
    const wrapper = mount(AdminAuditLog, { global: { stubs: ['router-link'] } })
    await flushPromises()
    expect(wrapper.text()).toContain('org.create')
    expect(wrapper.text()).toContain('admin@example.com')
  })
})
```

- [ ] **Step 2: 实现**

```vue
<!-- nodeskclaw-portal/src/views/admin/AdminAuditLog.vue -->
<template>
  <div class="p-6 space-y-4">
    <h2 class="text-2xl font-semibold">审计日志</h2>
    <div class="flex gap-2 text-sm">
      <input v-model="actor" placeholder="actor_id" class="border rounded px-2 py-1" />
      <select v-model="action" class="border rounded px-2 py-1">
        <option value="">所有动作</option>
        <option v-for="a in actionOptions" :key="a" :value="a">{{ a }}</option>
      </select>
      <input v-model="fromTs" type="datetime-local" class="border rounded px-2 py-1" />
      <input v-model="toTs" type="datetime-local" class="border rounded px-2 py-1" />
      <button @click="reload(1)" class="border px-3 py-1 rounded">查询</button>
    </div>
    <table class="w-full text-sm">
      <thead><tr><th>时间</th><th>操作人</th><th>动作</th><th>目标</th><th>状态</th></tr></thead>
      <tbody>
        <template v-for="r in rows" :key="r.id">
          <tr class="hover:bg-gray-50 cursor-pointer" @click="toggle(r.id)">
            <td>{{ r.created_at }}</td>
            <td>{{ r.actor_name ?? r.actor_id }}</td>
            <td>{{ r.action }}</td>
            <td>{{ r.target_type }}:{{ r.target_id }}</td>
            <td>{{ r.details?.status ?? '-' }}</td>
          </tr>
          <tr v-if="expanded.has(r.id)">
            <td colspan="5">
              <pre class="bg-gray-50 p-3 text-xs">{{ JSON.stringify(r.details, null, 2) }}</pre>
            </td>
          </tr>
        </template>
      </tbody>
    </table>
    <div class="flex gap-2 items-center">
      <button :disabled="page === 1" @click="reload(page - 1)">上一页</button>
      <span class="text-sm">第 {{ page }} 页 / {{ Math.ceil(total / pageSize) }}</span>
      <button :disabled="page * pageSize >= total" @click="reload(page + 1)">下一页</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useAdminApi, type AdminAuditRow } from '@/services/adminApi'

const api = useAdminApi()
const actor = ref('')
const action = ref('')
const fromTs = ref('')
const toTs = ref('')
const actionOptions = ref<string[]>([])
const rows = ref<AdminAuditRow[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const expanded = ref<Set<string>>(new Set())

async function reload(p = page.value) {
  page.value = p
  const res = await api.fetchAuditLogs({
    actor: actor.value || undefined,
    action: action.value || undefined,
    from: fromTs.value || undefined,
    to: toTs.value || undefined,
    page: p, pageSize: pageSize.value,
  })
  rows.value = res.data
  total.value = res.pagination.total
}
function toggle(id: string) {
  const next = new Set(expanded.value)
  next.has(id) ? next.delete(id) : next.add(id)
  expanded.value = next
}
onMounted(async () => {
  actionOptions.value = await api.fetchAuditActions()
  await reload(1)
})
</script>
```

- [ ] **Step 3: 验证测试 + 手测**

```bash
npm run test -- --run src/views/admin/AdminAuditLog.spec.ts
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add nodeskclaw-portal/src/views/admin/AdminAuditLog.vue \
        nodeskclaw-portal/src/views/admin/AdminAuditLog.spec.ts
git commit -m "feat(portal): AdminAuditLog 审计日志查询 + 展开详情"
```

---

## Phase 7 — i18n + 文档

### Task 27: i18n 词条补齐（zh-CN + en）

**Files:**
- Modify: `nodeskclaw-portal/src/i18n/locales/zh-CN.json`（或对应位置）
- Modify: `nodeskclaw-portal/src/i18n/locales/en.json`

- [ ] **Step 1: 定位 i18n 文件**

```bash
ls nodeskclaw-portal/src/i18n/ 2>/dev/null || grep -r "i18n" nodeskclaw-portal/src/ --include="*.ts" -l | head -5
```

定位到 zh-CN / en 资源文件实际路径。

- [ ] **Step 2: 追加 admin 命名空间词条**

zh-CN：
```jsonc
{
  "admin": {
    "nav": {
      "orgs": "组织", "users": "用户", "features": "功能开关", "audit": "审计日志"
    },
    "audit": {
      "actions": {
        "org.create": "创建组织",
        "org.update": "修改组织",
        "org.delete": "删除组织",
        "org_member.add": "添加组织成员",
        "org_member.update": "修改成员角色",
        "org_member.remove": "移除组织成员",
        "user.update": "修改用户标志",
        "user.reset_password": "重置用户密码",
        "user.delete": "删除用户",
        "feature_override.set": "设置 Feature 覆盖",
        "feature_override.clear": "清除 Feature 覆盖",
        "auth.login_success": "登录成功",
        "auth.login_failed": "登录失败",
        "auth.logout": "登出"
      }
    }
  },
  "errors": {
    "admin": {
      "self_deactivate_forbidden": "不能停用自己",
      "self_demote_super_admin_forbidden": "不能撤销自己的超管身份",
      "self_delete_forbidden": "不能删除自己",
      "last_super_admin_forbidden": "不能撤销系统最后一个超管",
      "org_slug_conflict": "Slug 已存在",
      "org_has_running_instances": "组织下仍有运行中的实例，请先删除",
      "org_last_admin_forbidden": "不能移除组织最后一个管理员",
      "org_not_found": "组织不存在",
      "org_member_duplicate": "成员已存在",
      "org_member_not_found": "成员不存在",
      "user_not_found": "用户不存在",
      "user_email_conflict": "Email 已存在",
      "user_already_deleted": "用户已被删除",
      "feature_id_unknown": "未知的 Feature ID",
      "feature_override_not_found": "Override 不存在",
      "audit_action_invalid": "审计 action 非法",
      "audit_time_range_invalid": "审计时间区间非法"
    }
  }
}
```

en：将每一条翻译为对应英文。

- [ ] **Step 3: TS / 构建检查**

```bash
cd nodeskclaw-portal && npm run build
```

Expected: 构建成功。

- [ ] **Step 4: Commit**

```bash
git add nodeskclaw-portal/src/i18n/
git commit -m "i18n(portal): 超管后台 + admin 错误码 zh-CN/en 词条"
```

---

### Task 28: 操作手册 `docs/admin/super-admin-guide.md`（独立 PR）

**Files:**
- Create: `docs/admin/super-admin-guide.md`

- [ ] **Step 1: 写文档**

```markdown
# 超管后台操作手册

> 适用范围：EE 版部署超管角色。位置：`/admin`。

## 入口

- 仅 `is_super_admin=true` 用户可见 `/admin` 入口。
- CE 版本不提供本手册涉及的功能。

## 组织管理

- `/admin/orgs` — 组织列表，支持创建 / 编辑 / 软删
- 行点击进入 `/admin/orgs/:id` 查看 Overview / 成员 / 功能开关
- 删除前必须先停止组织下的所有运行中实例

## 用户管理

- `/admin/users` — 全局用户搜索（按 email/name），分页
- 行点击进入 `/admin/users/:id`
- 禁用 / 启用：二次确认；不能停用自己
- 撤销超管：不能撤销自己；不能撤销最后一个超管
- 重置密码：弹窗显示临时密码 + 复制按钮；用户下次登录强制改密；明文不入审计

## 功能开关（Feature Override）

- `/admin/features` — 列表显示 features.yaml 全集 + 各自被覆盖的组织数
- 点击某 feature → 右侧抽屉显示该 feature 上的所有 override（分页）
- 反向入口：组织详情页 Features tab 以组织为主轴查看 / 切换
- 强制开 / 强制关：写入 reason 留待审计追溯
- 恢复默认：删除 override，回落 edition_features 默认

## 审计日志

- `/admin/audit` — 时间倒序
- 筛选：actor_id / action（来自 enum）/ 时间区间
- 行展开看 before/after JSON
- 保留期 90 天；超期物理删除（job 每天 03:00 运行）

## 安全约定

- 临时密码仅一次性返回，关闭弹窗后无再查口令
- 登录成功 / 失败 / 登出全部入审计
- 失败 actor 写 `anonymous`，details.attempted_email 用于排查爆破
- 数据删除一律软删 + 级联白名单（详见设计文档 §4.3）
```

- [ ] **Step 2: Commit（独立 PR 推荐放最后）**

```bash
git add docs/admin/super-admin-guide.md
git commit -m "docs(admin): 新增超管后台操作手册"
```

---

## 验收清单（实施完毕统一回看）

- [ ] Alembic 升级 / 降级双向通过
- [ ] `pytest ee/backend/services/admin/` 全 PASS（80%+ 覆盖率）
- [ ] `pytest ee/backend/api/admin/` happy + 403 全 PASS
- [ ] `pytest tests/api/test_auth_audit.py` PASS（含密码不入审计断言）
- [ ] `pytest tests/services/test_audit_retention_runner.py` PASS
- [ ] `npm run build` 通过；`npm run test` 所有新 spec PASS
- [ ] 浏览器访问 `/admin/*` 六个视图均可正常加载与操作
- [ ] i18n 词条 zh-CN / en 已补齐，无回退到 message_key 字面值
- [ ] 操作手册已上传到 `docs/admin/`

---

## 自查（spec coverage）

| 设计章节 | 任务覆盖 |
|---|---|
| §3.1 前端目录 | T20–T26 |
| §3.2 前端路由 | T20 |
| §3.3 后端目录（services） | T4–T10 |
| §3.4 鉴权链 | T16 |
| §4.1 organization_feature_overrides | T1 |
| §4.2.1 users.deleted_by | T1 |
| §4.3 软删级联 | T8/T9 + 测试覆盖 |
| §4.4 Alembic 迁移 | T1 |
| §4.5 FeatureGate 改造 | T5 |
| §5.0 响应契约（ApiResponse / PaginatedResponse） | T11–T15 |
| §5.1 组织成员 | T7 + T12 |
| §5.2 全局用户 | T8/T9 + T13 |
| §5.3 Feature 控制 | T5 + T14 |
| §5.4 审计 | T15 |
| §5.5 密码重置实现要点 | T8/T9 |
| §5.6 自我保护守卫 | T8 |
| §5.7 Service 层契约 | T5–T9 |
| §6.1 AdminLayout | T20 |
| §6.2 AdminOrgList | T21 |
| §6.3 AdminOrgDetail | T22 |
| §6.4 AdminUserList | T23 |
| §6.5 AdminUserDetail | T24 |
| §6.6 AdminFeatureList | T25 |
| §6.7 AdminAuditLog | T26 |
| §6.8 adminApi.ts | T19 |
| §6.9 i18n | T27 |
| §7.1 审计动作清单 | T4 + 所有 service 任务 |
| §7.1.1 AdminAction Enum | T2 |
| §7.2 临时密码安全 | T8/T9 + T24 |
| §7.3 审计保留期与 Job | T18 |
| §8 测试策略 | 各 task 内嵌 TDD |
| §9 发布与回退 | T1 仅加表 + 列；T16 路由可摘 |
