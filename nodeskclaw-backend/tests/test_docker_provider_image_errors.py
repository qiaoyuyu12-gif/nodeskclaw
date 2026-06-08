"""验证 docker_provider 的 pull_policy 默认行为 + 错误分类引导。

为修复「AI 员工实例创建失败 — 镜像 TLS handshake timeout」做的两条防回归：
1. compose YAML 主服务 / companion 都带 pull_policy=missing，避开 registry HEAD
2. _classify_docker_error 能识别典型 docker 失败 stderr 并给出引导文案
"""

from __future__ import annotations

import pytest

from app.services.runtime.compute import docker_provider as dp
from app.services.runtime.compute.base import CompanionSpec, InstanceComputeConfig


# ─── compose YAML 含 pull_policy ─────────────────────────────────────


def _minimal_config(with_companion: bool = False) -> InstanceComputeConfig:
    """构造一个最小可用的 InstanceComputeConfig 给 _build_compose_yaml 用。"""
    return InstanceComputeConfig(
        instance_id="i-1",
        name="test",
        slug="test-deploy",
        namespace="default",
        image_version="v2026.3.13",
        env_vars={"DOCKER_HOST_PORT": "3000"},
        companion=CompanionSpec(enabled=True, image="companion:1", port=8080)
        if with_companion else None,
    )


def test_compose_main_service_has_pull_policy_missing():
    """主服务必须带 pull_policy=missing：本地有镜像就不再 HEAD registry，
    避开火山引擎等私有镜像仓的 TLS 握手超时。"""
    compose = dp._build_compose_yaml(_minimal_config())
    agent = compose["services"]["agent"]
    assert agent.get("pull_policy") == "missing", (
        "main_service 缺少 pull_policy=missing，部署会强制走 registry HEAD，"
        "Windows/国内网络不通时会 TLS handshake timeout。"
    )


def test_compose_companion_service_has_pull_policy_missing():
    """有 companion 时同样必须带 pull_policy=missing。"""
    compose = dp._build_compose_yaml(_minimal_config(with_companion=True))
    companion = compose["services"]["companion"]
    assert companion.get("pull_policy") == "missing"


# ─── _classify_docker_error 模式识别 ──────────────────────────────────


@pytest.mark.parametrize("stderr_keyword", [
    "net/http: TLS handshake timeout",
    "dial tcp 1.2.3.4:443: i/o timeout",
    "lookup registry.example.com: no such host",
    "connection refused",
])
def test_classify_network_unreachable(stderr_keyword: str):
    """网络/镜像仓库不通：提示手动 docker pull 或 DOCKER_IMAGE 覆盖。"""
    hint = dp._classify_docker_error(f"some prefix {stderr_keyword} some suffix")
    assert hint is not None
    assert "docker pull" in hint
    assert "DOCKER_IMAGE" in hint


def test_classify_unauthorized():
    """镜像仓库认证失败：提示 docker login。"""
    hint = dp._classify_docker_error(
        "Error response from daemon: pull access denied for foo, repository "
        "does not exist or may require 'docker login'"
    )
    assert hint is not None
    assert "docker login" in hint


def test_classify_manifest_not_found():
    """镜像/版本不存在：提示检查 image_version。"""
    hint = dp._classify_docker_error(
        "Error response from daemon: manifest unknown: manifest unknown"
    )
    assert hint is not None
    assert "image_version" in hint


def test_classify_unknown_returns_none():
    """无匹配返回 None，调用方据此决定是否附加提示。"""
    assert dp._classify_docker_error("some random docker noise") is None


# ─── _format_docker_failure 组合输出 ──────────────────────────────────


def test_format_docker_failure_includes_hint_when_classifiable():
    """可识别错误：组合输出必须同时含「核心错误」+「提示：...」。"""
    raw = (
        'Error response from daemon: failed to resolve reference '
        '"foo:v1": Head "https://foo": net/http: TLS handshake timeout'
    )
    msg = dp._format_docker_failure("docker compose up 失败", raw)
    assert msg.startswith("docker compose up 失败:")
    assert "TLS handshake timeout" in msg
    assert "提示：" in msg
    assert "docker pull" in msg


def test_format_docker_failure_no_hint_when_unknown():
    """无法识别的错误：仅核心错误，不加多余的「提示：」噪音。"""
    msg = dp._format_docker_failure("docker compose up 失败", "unknown noise")
    assert msg.startswith("docker compose up 失败:")
    assert "提示：" not in msg
