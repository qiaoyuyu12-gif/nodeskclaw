"""平台托管 Key 路由 schema 单元测试。

不依赖 DB / FastAPI client，仅校验：
- Pydantic schema 字段定义与默认值
- base_url 自动补 https:// 协议
- 路由数量与方法符合预期
"""

from __future__ import annotations

import sys
from pathlib import Path

# EE 模块依赖 ee/ 目录在 sys.path 中
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ee.backend.api.admin.platform_providers import (  # noqa: E402
    PlatformProviderCreate,
    PlatformProviderUpdate,
    router,
)


class TestPlatformProviderSchema:
    def test_create_normalizes_base_url(self) -> None:
        # 无协议时自动补 https://
        body = PlatformProviderCreate(provider="minimax-openai", api_key="sk-x", base_url="api.example.com/v1")
        assert body.base_url == "https://api.example.com/v1"

    def test_create_preserves_explicit_protocol(self) -> None:
        # 已含协议时保持原样
        body = PlatformProviderCreate(provider="x", api_key="k", base_url="http://internal/api")
        assert body.base_url == "http://internal/api"

    def test_create_allows_optional_fields(self) -> None:
        # 仅 provider + api_key 必填，其他可选
        body = PlatformProviderCreate(provider="openai", api_key="sk-abc")
        assert body.label is None
        assert body.base_url is None
        assert body.skip_ssl_verify is False
        assert body.allowed_models is None

    def test_update_all_fields_optional(self) -> None:
        # 空对象合法
        body = PlatformProviderUpdate()
        assert body.model_dump(exclude_unset=True) == {}

    def test_update_partial_payload(self) -> None:
        # 仅传 allowed_models 时，model_dump(exclude_unset=True) 只含该字段
        body = PlatformProviderUpdate(allowed_models=["m1", "m2"])
        assert body.model_dump(exclude_unset=True) == {"allowed_models": ["m1", "m2"]}


class TestPlatformProviderRoutes:
    def test_router_exposes_four_endpoints(self) -> None:
        # GET/POST 列表 + PATCH/DELETE 单条 = 4 条路由
        methods = {(r.path, tuple(sorted(r.methods))) for r in router.routes}  # type: ignore[attr-defined]
        assert ("/orgs/{org_id}/platform-providers", ("GET",)) in methods
        assert ("/orgs/{org_id}/platform-providers", ("POST",)) in methods
        assert ("/orgs/{org_id}/platform-providers/{key_id}", ("PATCH",)) in methods
        assert ("/orgs/{org_id}/platform-providers/{key_id}", ("DELETE",)) in methods
