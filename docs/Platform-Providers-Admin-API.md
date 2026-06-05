# 平台托管 LLM Key Admin API 契约

> 适用范围：EE 平台超管下发/维护组织级"平台托管" LLM Key（`is_platform_managed=True`）。
> 关联改造：Working Plan 与"模型提供商"两入口融合（commits 5e084e4..780f2ce + 15df9b2）。

## 背景

CE 与 EE 共用同一张 `org_llm_keys` 表存放组织的 LLM Key。本次改造新增 `is_platform_managed` 字段：

- `false`（默认）：组织 BYOK 自带 Key，组织管理员可在 portal 全字段编辑/删除
- `true`：平台超管下发的"官方代付"Key（原 Working Plan 形态），portal 端可见但仅允许勾选 `allowed_models` 与切换 `is_active`，敏感字段（api_key / base_url / api_type / label / *_token_limit / skip_ssl_verify）只能通过本文档描述的 admin API 维护

组织 portal 端在 `nodeskclaw-portal/src/views/OrgSettingsLlmKeys.vue` 通过 `is_platform_managed` 渲染紫色"平台管理"徽章、锁定输入框、隐藏删除按钮。

## 路由清单

所有路由前缀 `/api/v1/admin`，需要：
- `Authorization: Bearer <JWT>`
- 当前用户 `is_super_admin=True`
- 已启用 `platform_admin` feature（`ee_admin_router` 双守卫）

| Method | 路径 | 行为 |
|--------|------|------|
| GET    | `/orgs/{org_id}/platform-providers`         | 列出某组织全部平台托管 Key |
| POST   | `/orgs/{org_id}/platform-providers`         | 下发新平台托管 Key（含软删行复活路径） |
| PATCH  | `/orgs/{org_id}/platform-providers/{key_id}`| 更新任意字段；`is_platform_managed` 强制保持 True |
| DELETE | `/orgs/{org_id}/platform-providers/{key_id}`| 软删（设置 `deleted_at`） |

### POST 请求体（`PlatformProviderCreate`）

```jsonc
{
  "provider": "minimax-openai",      // 必填，max 32 chars
  "label": "MiniMax OpenAI 兼容",     // 可选，max 128 chars
  "api_key": "sk-xxxxxxxx",          // 必填
  "base_url": "api.minimaxi.com/v1", // 可选，无协议时自动补 https://
  "api_type": "openai-completions",  // 可选；openai-completions / anthropic-messages
  "org_token_limit": null,           // 可选，组织级配额（EE 维度）
  "system_token_limit": null,        // 可选，全局配额
  "skip_ssl_verify": false,
  "allowed_models": ["abab6", "MiniMax-Text-01"]  // 可选
}
```

### PATCH 请求体（`PlatformProviderUpdate`）

全字段可选（仅传需要修改的字段）。`is_platform_managed` 不暴露，路由内防御性兜底保持 True。

### 响应（`OrgModelProviderInfo`）

与 portal `GET /orgs/{org_id}/model-providers` 同形态。`api_key_masked` 已脱敏；`usage_total_tokens` 在 admin 视图中固定为 0（admin 不关心组织实时用量）。

## 错误码

| HTTP | code | message_key | 触发条件 |
|------|------|-------------|----------|
| 404 | 40400 | `errors.common.not_found` | 组织或 key_id 不存在/软删 |
| 409 | 40900 | `errors.platform_provider.already_exists` | POST 时同 `(org_id, provider)` 已有活跃行（请改用 PATCH） |
| 403 | 40310 | `errors.org.super_admin_required` | 调用方非超管 |

> 注：POST 命中同 `(org_id, provider)` 的**软删**行时自动复活（清 `deleted_at` + 覆写字段），不返回 409。这是为了避免唯一约束 race。

组织 portal 侧守卫（`nodeskclaw-backend/app/api/llm_keys.py`）：
- `PATCH /orgs/{id}/model-providers/{key_id}` 触碰受锁字段 → 403 `errors.model_provider.platform_managed_locked`
- `DELETE /orgs/{id}/model-providers/{key_id}` 命中平台行 → 403 `errors.model_provider.platform_managed_no_delete`

受锁字段清单：`api_key / base_url / api_type / label / org_token_limit / system_token_limit / skip_ssl_verify`。

## 审计

所有写操作进 `operation_audit` hook，`action` 取值：
- `platform_provider.created`
- `platform_provider.updated`
- `platform_provider.deleted`

组织端 PATCH/DELETE 仍走原 `model_provider.{updated,deleted}` action，区分管理来源。

## curl 端到端示例

```bash
ADMIN_JWT="..."  # 平台超管 JWT
ORG_ID="org_abc"
BASE="https://nodeskclaw.example.com/api/v1"

# 1. 列出当前组织已下发的平台 Key
curl -s -H "Authorization: Bearer $ADMIN_JWT" \
  "$BASE/admin/orgs/$ORG_ID/platform-providers"

# 2. 下发 MiniMax OpenAI 兼容通道
curl -s -X POST -H "Authorization: Bearer $ADMIN_JWT" \
  -H "Content-Type: application/json" \
  "$BASE/admin/orgs/$ORG_ID/platform-providers" \
  -d '{
    "provider": "minimax-openai",
    "api_key": "sk-xxxxxxxx",
    "base_url": "https://api.minimaxi.com/v1",
    "api_type": "openai-completions",
    "allowed_models": ["abab6", "MiniMax-Text-01"]
  }'

# 3. 更新允许模型
curl -s -X PATCH -H "Authorization: Bearer $ADMIN_JWT" \
  -H "Content-Type: application/json" \
  "$BASE/admin/orgs/$ORG_ID/platform-providers/<key_id>" \
  -d '{"allowed_models": ["MiniMax-Text-01"]}'

# 4. 软删
curl -s -X DELETE -H "Authorization: Bearer $ADMIN_JWT" \
  "$BASE/admin/orgs/$ORG_ID/platform-providers/<key_id>"

# 5. 验证组织 portal 端可见但锁字段
curl -s -H "Authorization: Bearer <org_admin_jwt>" \
  "$BASE/orgs/$ORG_ID/model-providers"
# 返回里该行应有 "is_platform_managed": true
```

## 私有仓接手指引

### 后端模块

`ee/backend/api/admin/platform_providers.py` 在本 CE 仓被 `.gitignore` 排除（`ee/backend/api/admin/*` 仅放行 `__init__.py`）。本节附完整实现，私有仓直接落盘即可：

```python
"""Admin - Platform-managed Model Provider Keys (EE).

平台超管为指定组织下发/维护 LLM Key（is_platform_managed=True）。
组织 portal 端可见但只能勾选 allowed_models / 切换 is_active，敏感字段由本路由维护。

设计要点：
- 路由前缀已含完整 /orgs/{org_id}/platform-providers，挂载到 ee_admin_router
- 双守卫：上层 ee_admin_router 提供 require_feature(platform_admin) + require_super_admin_dep
- 唯一约束 (org_id, provider) WHERE deleted_at IS NULL：POST 若已存在软删行则复活，避免 race 409
- 所有写操作进 operation_audit，action 命名 platform_provider.{created/updated/deleted}
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import hooks
from app.core.deps import get_db
from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import get_current_user
from app.models.base import not_deleted
from app.models.org_llm_key import OrgModelProvider
from app.models.organization import Organization
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.llm import OrgModelProviderInfo
from app.services.codex_provider import mask_personal_key

logger = logging.getLogger(__name__)

router = APIRouter()


def _normalize_base_url(v: str | None) -> str | None:
    if not v or not v.strip():
        return v
    v = v.strip()
    if not v.startswith(("http://", "https://")):
        v = f"https://{v}"
    return v


class PlatformProviderCreate(BaseModel):
    provider: str = Field(..., max_length=32)
    label: str | None = Field(None, max_length=128)
    api_key: str
    base_url: str | None = None
    api_type: str | None = None
    org_token_limit: int | None = None
    system_token_limit: int | None = None
    skip_ssl_verify: bool = False
    allowed_models: list[str] | None = None
    _normalize_base_url_field = field_validator("base_url", mode="before")(_normalize_base_url)


class PlatformProviderUpdate(BaseModel):
    label: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    api_type: str | None = None
    org_token_limit: int | None = None
    system_token_limit: int | None = None
    is_active: bool | None = None
    allowed_models: list[str] | None = None
    skip_ssl_verify: bool | None = None
    _normalize_base_url_field = field_validator("base_url", mode="before")(_normalize_base_url)


def _mask(provider: str, key: str) -> str:
    return mask_personal_key(provider, key)


def _to_info(k: OrgModelProvider) -> OrgModelProviderInfo:
    return OrgModelProviderInfo(
        id=k.id, org_id=k.org_id, provider=k.provider, label=k.label,
        api_key_masked=_mask(k.provider, k.api_key), base_url=k.base_url,
        api_type=k.api_type, org_token_limit=k.org_token_limit,
        system_token_limit=k.system_token_limit, is_active=k.is_active,
        skip_ssl_verify=k.skip_ssl_verify, allowed_models=k.allowed_models,
        is_platform_managed=k.is_platform_managed, usage_total_tokens=0,
        created_by=k.created_by,
    )


async def _get_org_or_404(db: AsyncSession, org_id: str) -> Organization:
    res = await db.execute(
        select(Organization).where(
            Organization.id == org_id, Organization.deleted_at.is_(None),
        )
    )
    org = res.scalar_one_or_none()
    if org is None:
        raise NotFoundError("组织不存在")
    return org


async def _find_existing_row(
    db: AsyncSession, org_id: str, provider: str, include_deleted: bool = False,
) -> OrgModelProvider | None:
    stmt = select(OrgModelProvider).where(
        OrgModelProvider.org_id == org_id, OrgModelProvider.provider == provider,
    )
    if not include_deleted:
        stmt = stmt.where(not_deleted(OrgModelProvider))
    res = await db.execute(stmt.limit(1))
    return res.scalar_one_or_none()


@router.get(
    "/orgs/{org_id}/platform-providers",
    response_model=ApiResponse[list[OrgModelProviderInfo]],
)
async def list_platform_providers(
    org_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_user),
):
    await _get_org_or_404(db, org_id)
    res = await db.execute(
        select(OrgModelProvider)
        .where(
            OrgModelProvider.org_id == org_id,
            OrgModelProvider.is_platform_managed.is_(True),
            not_deleted(OrgModelProvider),
        )
        .order_by(OrgModelProvider.created_at)
    )
    return ApiResponse(data=[_to_info(k) for k in res.scalars().all()])


@router.post(
    "/orgs/{org_id}/platform-providers",
    response_model=ApiResponse[OrgModelProviderInfo],
)
async def create_platform_provider(
    org_id: str,
    body: PlatformProviderCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_user),
):
    await _get_org_or_404(db, org_id)
    active = await _find_existing_row(db, org_id, body.provider, include_deleted=False)
    if active is not None:
        raise ConflictError(
            f"{body.provider} 已存在平台托管或组织自带 Key，请改用 PATCH 更新",
            "errors.platform_provider.already_exists",
        )

    soft_deleted = await _find_existing_row(db, org_id, body.provider, include_deleted=True)
    if soft_deleted is not None:
        soft_deleted.deleted_at = None
        soft_deleted.label = body.label
        soft_deleted.api_key = body.api_key
        soft_deleted.base_url = body.base_url
        soft_deleted.api_type = body.api_type
        soft_deleted.org_token_limit = body.org_token_limit
        soft_deleted.system_token_limit = body.system_token_limit
        soft_deleted.skip_ssl_verify = body.skip_ssl_verify
        soft_deleted.allowed_models = body.allowed_models
        soft_deleted.is_platform_managed = True
        soft_deleted.is_active = True
        soft_deleted.created_by = admin.id
        key = soft_deleted
        revived = True
    else:
        key = OrgModelProvider(
            org_id=org_id, provider=body.provider, label=body.label,
            api_key=body.api_key, base_url=body.base_url, api_type=body.api_type,
            org_token_limit=body.org_token_limit,
            system_token_limit=body.system_token_limit,
            skip_ssl_verify=body.skip_ssl_verify, allowed_models=body.allowed_models,
            is_platform_managed=True, created_by=admin.id,
        )
        db.add(key)
        revived = False

    await db.commit()
    await db.refresh(key)
    logger.info(
        "平台 Key 下发: org=%s provider=%s revived=%s by=%s",
        org_id, body.provider, revived, admin.id,
    )
    await hooks.emit(
        "operation_audit", action="platform_provider.created",
        target_type="model_provider", target_id=key.id,
        actor_id=admin.id, org_id=org_id,
    )
    return ApiResponse(data=_to_info(key))


@router.patch(
    "/orgs/{org_id}/platform-providers/{key_id}",
    response_model=ApiResponse[OrgModelProviderInfo],
)
async def update_platform_provider(
    org_id: str,
    key_id: str,
    body: PlatformProviderUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_user),
):
    await _get_org_or_404(db, org_id)
    res = await db.execute(
        select(OrgModelProvider).where(
            OrgModelProvider.id == key_id,
            OrgModelProvider.org_id == org_id,
            OrgModelProvider.is_platform_managed.is_(True),
            not_deleted(OrgModelProvider),
        )
    )
    key = res.scalar_one_or_none()
    if key is None:
        raise NotFoundError("平台托管 Key 不存在")

    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(key, field, val)
    key.is_platform_managed = True  # 防御性兜底

    await db.commit()
    await db.refresh(key)
    logger.info("平台 Key 更新: org=%s key=%s by=%s", org_id, key_id, admin.id)
    await hooks.emit(
        "operation_audit", action="platform_provider.updated",
        target_type="model_provider", target_id=key_id,
        actor_id=admin.id, org_id=org_id,
    )
    return ApiResponse(data=_to_info(key))


@router.delete(
    "/orgs/{org_id}/platform-providers/{key_id}",
    response_model=ApiResponse,
)
async def delete_platform_provider(
    org_id: str,
    key_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_user),
):
    await _get_org_or_404(db, org_id)
    res = await db.execute(
        select(OrgModelProvider).where(
            OrgModelProvider.id == key_id,
            OrgModelProvider.org_id == org_id,
            OrgModelProvider.is_platform_managed.is_(True),
            not_deleted(OrgModelProvider),
        )
    )
    key = res.scalar_one_or_none()
    if key is None:
        raise NotFoundError("平台托管 Key 不存在")

    key.soft_delete()
    await db.commit()
    logger.info("平台 Key 软删: org=%s key=%s by=%s", org_id, key_id, admin.id)
    await hooks.emit(
        "operation_audit", action="platform_provider.deleted",
        target_type="model_provider", target_id=key_id,
        actor_id=admin.id, org_id=org_id,
    )
    return ApiResponse(message="已删除")
```

### 单元测试

放在 `ee/backend/api/admin/test_platform_providers.py`：

```python
"""平台托管 Key 路由 schema 单元测试。"""
from __future__ import annotations
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ee.backend.api.admin.platform_providers import (  # noqa: E402
    PlatformProviderCreate, PlatformProviderUpdate, router,
)


class TestPlatformProviderSchema:
    def test_create_normalizes_base_url(self) -> None:
        body = PlatformProviderCreate(provider="x", api_key="k", base_url="api.example.com/v1")
        assert body.base_url == "https://api.example.com/v1"

    def test_create_preserves_explicit_protocol(self) -> None:
        body = PlatformProviderCreate(provider="x", api_key="k", base_url="http://internal/api")
        assert body.base_url == "http://internal/api"

    def test_create_allows_optional_fields(self) -> None:
        body = PlatformProviderCreate(provider="openai", api_key="sk-abc")
        assert body.label is None
        assert body.base_url is None
        assert body.skip_ssl_verify is False

    def test_update_all_fields_optional(self) -> None:
        assert PlatformProviderUpdate().model_dump(exclude_unset=True) == {}

    def test_update_partial_payload(self) -> None:
        body = PlatformProviderUpdate(allowed_models=["m1", "m2"])
        assert body.model_dump(exclude_unset=True) == {"allowed_models": ["m1", "m2"]}


class TestPlatformProviderRoutes:
    def test_router_exposes_four_endpoints(self) -> None:
        methods = {(r.path, tuple(sorted(r.methods))) for r in router.routes}  # type: ignore[attr-defined]
        assert ("/orgs/{org_id}/platform-providers", ("GET",)) in methods
        assert ("/orgs/{org_id}/platform-providers", ("POST",)) in methods
        assert ("/orgs/{org_id}/platform-providers/{key_id}", ("PATCH",)) in methods
        assert ("/orgs/{org_id}/platform-providers/{key_id}", ("DELETE",)) in methods
```

### 路由注册（已在公开仓 commit）

`ee/backend/router.py` 已在 commit `15df9b2` 注册：

```python
from ee.backend.api.admin.platform_providers import router as ee_platform_provider_router
ee_admin_router.include_router(
    ee_platform_provider_router,
    prefix="",
    tags=["EE - 超管平台模型 Key"],
    dependencies=admin_deps,
)
```

ImportError 已 try/except 兜底；CE 运行时该模块缺失只会打 warning，不影响启动。

### Admin 前端实现建议

EE admin 前端（`ee/nodeskclaw-frontend` / 私有仓）建议新增页面 `views/admin/PlatformProviders.vue`，挂在某个组织详情页的子标签。关键差异：

- 表单字段：**全部可编辑**（含 `api_key` 明文输入），不锁字段
- 列表展示：admin 关心 `created_by` 实际姓名 + 创建时间，组织端不关心
- 复用 `ee_backup/nodeskclaw-frontend/src/views/admin/OrgList.vue` 的列表/表单风格
- API 调用路径：`/api/v1/admin/orgs/{org_id}/platform-providers[/{key_id}]`
- 调用方式参考 `nodeskclaw-portal/src/views/OrgSettingsLlmKeys.vue` 中的 `openConfigure / handleSave` 函数

### 验证步骤

完成私有仓落盘后：

1. `./dev.sh ee` 启动 EE 模式
2. 用平台超管账号 curl POST 下发一行 `minimax-openai`
3. 切组织 admin 账号打开"组织设置 → 模型提供商"
4. 检查清单：
   - minimax-openai 主网格出现并置顶，紫色"平台管理"徽章
   - 点设置：`api_key / base_url / api_type / token_limit / skip_ssl_verify` 输入框 disabled，顶部提示"密钥与连接信息由平台维护"
   - 弹窗内能勾选 `allowed_models` 并保存成功
   - 卡片删除按钮不渲染；尝试调 DELETE 直接返回 403
5. 创建使用 minimax-openai 的 AI 员工实例 → deploy 成功 → 实际能调用模型（运行时路径未变）
6. admin 端 DELETE 后组织 portal 看到该行消失

### 现有 minimax 行的回填

数据库迁移 `4971d0b79e17` 已 UPDATE 历史 `provider LIKE 'minimax-%'` 行的 `is_platform_managed=true`。私有仓接手时无需额外脚本，旧数据已按"平台托管"语义自动迁移。
