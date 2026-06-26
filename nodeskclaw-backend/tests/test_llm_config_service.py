from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import llm_config_service


def test_nodeskclaw_tool_names_are_complete() -> None:
    assert llm_config_service.NODESKCLAW_TOOL_NAMES == (
        "nodeskclaw_blackboard",
        "nodeskclaw_topology",
        "nodeskclaw_performance",
        "nodeskclaw_proposals",
        "nodeskclaw_gene_discovery",
        "nodeskclaw_file_download",
        "nodeskclaw_chat_history",
        "nodeskclaw_shared_files",
    )


async def test_build_hermes_provider_payload_uses_named_custom_provider(monkeypatch) -> None:
    configs = [
        SimpleNamespace(
            provider="test-openai",
            key_source="org",
            selected_models=[{"id": "gpt-4.1", "name": "GPT-4.1"}],
            base_url="https://llm.example.com/v1",
            api_type="openai-completions",
        )
    ]
    org_keys = {
        "test-openai": SimpleNamespace(
            provider="test-openai",
            api_key="secret-key",
            base_url="https://llm.example.com/v1",
            api_type="openai-completions",
        )
    }

    monkeypatch.setattr(llm_config_service.settings, "LLM_PROXY_INTERNAL_URL", "http://llm-proxy.internal:4100")
    monkeypatch.setattr(llm_config_service.settings, "LLM_PROXY_URL", "https://llm-proxy.example.com")
    providers, env_updates, primary = await llm_config_service._build_hermes_provider_payload(
        configs,
        wp_api_key="wp-token",
        user_keys={},
        org_keys=org_keys,
        use_external_proxy=False,
    )

    assert providers == [{
        "name": "nodeskclaw-test-openai",
        "base_url": "http://llm-proxy.internal:4100/test-openai/v1",
        "key_env": "NODESKCLAW_WP_API_KEY",
        "api_mode": "chat_completions",
        "model": "gpt-4.1",
    }]
    assert env_updates == {"NODESKCLAW_WP_API_KEY": "wp-token"}
    assert primary == {
        "provider": "custom:nodeskclaw-test-openai",
        "base_url": "http://llm-proxy.internal:4100/test-openai/v1",
        "model": "gpt-4.1",
    }


async def test_build_hermes_provider_payload_keeps_personal_provider_direct() -> None:
    configs = [
        SimpleNamespace(
            provider="personal-openai",
            key_source="personal",
            selected_models=[{"id": "gpt-4.1-mini", "name": "GPT-4.1 mini"}],
            base_url="https://personal.example.com/v1",
            api_type="openai-completions",
        )
    ]
    user_keys = {
        "personal-openai": SimpleNamespace(
            provider="personal-openai",
            api_key="personal-secret",
            base_url="https://personal.example.com/v1",
            api_type="openai-completions",
        )
    }

    providers, env_updates, primary = await llm_config_service._build_hermes_provider_payload(
        configs,
        wp_api_key="wp-token",
        user_keys=user_keys,
        org_keys={},
        use_external_proxy=False,
    )

    assert providers == [{
        "name": "nodeskclaw-personal-openai",
        "base_url": "https://personal.example.com/v1",
        "key_env": "NODESKCLAW_PERSONAL_OPENAI_API_KEY",
        "api_mode": "chat_completions",
        "model": "gpt-4.1-mini",
    }]
    assert env_updates == {"NODESKCLAW_PERSONAL_OPENAI_API_KEY": "personal-secret"}
    assert primary == {
        "provider": "custom:nodeskclaw-personal-openai",
        "base_url": "https://personal.example.com/v1",
        "model": "gpt-4.1-mini",
    }


async def test_build_hermes_provider_payload_uses_org_gemini_allowed_model(monkeypatch) -> None:
    configs = [
        SimpleNamespace(
            provider="gemini",
            key_source="org",
            selected_models=None,
            base_url=None,
            api_type=None,
        )
    ]
    org_keys = {
        "gemini": SimpleNamespace(
            provider="gemini",
            api_key="org-real-key",
            base_url="https://generativelanguage.googleapis.com",
            api_type="google-generative-ai",
            allowed_models=["gemini-2.5-flash"],
        )
    }

    monkeypatch.setattr(llm_config_service.settings, "LLM_PROXY_INTERNAL_URL", "http://llm-proxy.internal:4100")
    monkeypatch.setattr(llm_config_service.settings, "LLM_PROXY_URL", "https://llm-proxy.example.com")

    providers, env_updates, primary = await llm_config_service._build_hermes_provider_payload(
        configs,
        wp_api_key="wp-token",
        user_keys={},
        org_keys=org_keys,
        use_external_proxy=False,
    )

    assert providers == [{
        "name": "nodeskclaw-gemini",
        "base_url": "http://llm-proxy.internal:4100/gemini",
        "key_env": "NODESKCLAW_WP_API_KEY",
        "api_mode": "chat_completions",
        "model": "gemini-2.5-flash",
    }]
    assert env_updates == {"NODESKCLAW_WP_API_KEY": "wp-token"}
    assert primary == {
        "provider": "custom:nodeskclaw-gemini",
        "base_url": "http://llm-proxy.internal:4100/gemini",
        "model": "gemini-2.5-flash",
    }


async def test_build_hermes_provider_payload_routes_personal_gemini_via_proxy(monkeypatch) -> None:
    configs = [
        SimpleNamespace(
            provider="gemini",
            key_source="personal",
            selected_models=[{"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro"}],
            base_url=None,
            api_type=None,
        )
    ]
    user_keys = {
        "gemini": SimpleNamespace(
            provider="gemini",
            api_key="personal-real-key",
            base_url="https://generativelanguage.googleapis.com",
            api_type="google-generative-ai",
        )
    }

    monkeypatch.setattr(llm_config_service.settings, "LLM_PROXY_INTERNAL_URL", "http://llm-proxy.internal:4100")
    monkeypatch.setattr(llm_config_service.settings, "LLM_PROXY_URL", "https://llm-proxy.example.com")

    providers, env_updates, primary = await llm_config_service._build_hermes_provider_payload(
        configs,
        wp_api_key="wp-token",
        user_keys=user_keys,
        org_keys={},
        use_external_proxy=False,
    )

    assert providers == [{
        "name": "nodeskclaw-gemini",
        "base_url": "http://llm-proxy.internal:4100/gemini",
        "key_env": "NODESKCLAW_WP_API_KEY",
        "api_mode": "chat_completions",
        "model": "gemini-2.5-pro",
    }]
    assert env_updates == {"NODESKCLAW_WP_API_KEY": "wp-token"}
    assert "personal-real-key" not in env_updates.values()
    assert primary == {
        "provider": "custom:nodeskclaw-gemini",
        "base_url": "http://llm-proxy.internal:4100/gemini",
        "model": "gemini-2.5-pro",
    }


def test_dotenv_roundtrip_preserves_values() -> None:
    raw = 'OPENAI_API_KEY="abc123"\nOTHER=value\n'

    parsed = llm_config_service._parse_dotenv(raw)

    assert parsed == {"OPENAI_API_KEY": "abc123", "OTHER": "value"}
    assert llm_config_service._dump_dotenv(parsed) == 'OPENAI_API_KEY="abc123"\nOTHER="value"\n'


async def test_restart_runtime_recovers_hermes_pending_without_openclaw_force(monkeypatch) -> None:
    instance = SimpleNamespace(
        runtime="hermes",
        compute_provider="k8s",
        namespace="ns-hermes",
        slug="hermes-1",
        name="Hermes",
        llm_config_pending=True,
    )
    db = AsyncMock()
    k8s = SimpleNamespace(
        restart_deployment=AsyncMock(),
        set_deployment_env=AsyncMock(),
        remove_deployment_env=AsyncMock(),
    )
    sync_hermes = AsyncMock()
    sync_openclaw = AsyncMock()

    monkeypatch.setattr(llm_config_service, "_get_k8s_client", AsyncMock(return_value=k8s))
    monkeypatch.setattr(llm_config_service, "_poll_pod_ready", AsyncMock(return_value=True))
    monkeypatch.setattr(llm_config_service, "sync_hermes_llm_config", sync_hermes)
    monkeypatch.setattr(llm_config_service, "sync_openclaw_llm_config", sync_openclaw)

    result = await llm_config_service.restart_runtime(instance, db)

    assert result == {"status": "ok", "message": "配置已恢复并重启完成"}
    sync_hermes.assert_awaited_once_with(
        instance,
        db,
        restart_runtime_after_write=False,
    )
    sync_openclaw.assert_not_awaited()
    assert k8s.restart_deployment.await_count == 2
    k8s.restart_deployment.assert_any_await("ns-hermes", "hermes-1")
    k8s.set_deployment_env.assert_not_awaited()
    k8s.remove_deployment_env.assert_not_awaited()
    assert instance.llm_config_pending is False
    db.commit.assert_awaited_once()


def _ipc_write_mocks(monkeypatch, *, write_side_effect):
    """Stub out the heavy dependencies of write_instance_llm_configs.

    Returns the configs list; caller sets up db + instance.
    """
    monkeypatch.setattr(llm_config_service, "normalize_selected_models", lambda provider, models: models)
    monkeypatch.setattr(llm_config_service, "_docker_rewrite_urls", lambda providers: providers)
    monkeypatch.setattr(llm_config_service, "_ensure_gateway_config", lambda config, instance: None)
    monkeypatch.setattr(llm_config_service, "_read_config_file", AsyncMock(return_value={}))
    monkeypatch.setattr(llm_config_service, "_write_config_file", AsyncMock(side_effect=write_side_effect))

    @asynccontextmanager
    async def fake_remote_fs(_instance, _db):
        yield object()

    monkeypatch.setattr(llm_config_service, "remote_fs", fake_remote_fs)


def _build_db(monkeypatch):
    """db.execute 顺序：existing InstanceProviderConfig 查询、cluster 查询。"""
    existing_res = MagicMock()
    existing_res.scalars.return_value.all.return_value = []
    cluster_res = MagicMock()
    cluster_res.scalar_one_or_none.return_value = None  # use_external=False
    db = AsyncMock()
    db.add = MagicMock()  # add 是同步方法，避免 AsyncMock 产生未 await 的协程警告
    db.execute = AsyncMock(side_effect=[existing_res, cluster_res])
    return db


async def test_write_instance_llm_configs_marks_pending_on_write_oserror(monkeypatch) -> None:
    """运行时写入抛 OSError/PermissionError 时，配置存 DB 并标记 pending（不应 500）。

    复现真实事故：原生 Linux 下写容器 root:700 的 openclaw.json 抛 PermissionError，
    旧代码 except 只认 NFSMountError → 直接 500，DB 与容器静默不一致。
    """
    instance = SimpleNamespace(
        id="inst-1", org_id="org-1", cluster_id="cl-1",
        runtime="openclaw", compute_provider="docker",
        name="t1", wp_api_key="wp-key", llm_config_pending=False,
    )
    db = _build_db(monkeypatch)
    monkeypatch.setattr(
        llm_config_service, "_build_providers_config",
        lambda *a, **k: {"minimax-openai": {"baseUrl": "x", "apiKey": "y", "models": [{"id": "MiniMax-M2.5"}]}},
    )
    _ipc_write_mocks(monkeypatch, write_side_effect=PermissionError("Permission denied"))

    configs = [SimpleNamespace(
        provider="minimax-openai", key_source="team",
        selected_models=[{"id": "MiniMax-M2.5"}], base_url=None, api_type=None,
    )]

    applied = await llm_config_service.write_instance_llm_configs(instance, db, configs, "user-1")

    assert applied is False
    assert instance.llm_config_pending is True


async def test_write_instance_llm_configs_propagates_validation_error(monkeypatch) -> None:
    """校验类错误（未生成任何 Provider）必须抛 AppException 给用户，不能被吞成 pending。"""
    instance = SimpleNamespace(
        id="inst-1", org_id="org-1", cluster_id="cl-1",
        runtime="openclaw", compute_provider="docker",
        name="t1", wp_api_key="wp-key", llm_config_pending=False,
    )
    db = _build_db(monkeypatch)
    # 模拟"配了 provider 但没生成任何 entry（key 缺失）" -> 触发 AppException
    monkeypatch.setattr(llm_config_service, "_build_providers_config", lambda *a, **k: {})
    _ipc_write_mocks(monkeypatch, write_side_effect=PermissionError("should not reach"))

    configs = [SimpleNamespace(
        provider="minimax-openai", key_source="team",
        selected_models=[{"id": "MiniMax-M2.5"}], base_url=None, api_type=None,
    )]

    with pytest.raises(llm_config_service.AppException):
        await llm_config_service.write_instance_llm_configs(instance, db, configs, "user-1")

    assert instance.llm_config_pending is False  # 未被误标 pending
