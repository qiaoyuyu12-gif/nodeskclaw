"""DockerComputeProvider — manages agent instances as Docker Compose services."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath

from app.services.docker_constants import DOCKER_DATA_DIR, DOCKER_HOST_DATA_DIR
from app.services.runtime.compute.base import (
    ComputeHandle,
    InstanceComputeConfig,
)

logger = logging.getLogger(__name__)

_LOCALHOST_RE = re.compile(r"(https?://)(localhost|127\.0\.0\.1)(:\d+)?")
_WINDOWS_HOST_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")


def _docker_endpoint_host() -> str:
    """Return the hostname for reaching host-mapped ports from the backend process.

    Inside a container: host.docker.internal (host ports are not on localhost).
    On the host directly: localhost.
    """
    if os.path.exists("/.dockerenv") or os.environ.get("DOCKER_DATA_DIR"):
        return "host.docker.internal"
    return "localhost"


def _parse_cpu(cpu_str: str) -> float:
    """Convert K8s-style cpu (e.g. '2000m', '2') to Docker cpus float."""
    s = cpu_str.strip().lower()
    if s.endswith("m"):
        return int(s[:-1]) / 1000
    return float(s)


_K8S_MEM_SUFFIXES: dict[str, str] = {
    "ki": "k", "mi": "m", "gi": "g", "ti": "t", "pi": "p",
}


def _parse_mem(mem_str: str) -> str:
    """Convert K8s-style memory (e.g. '2Gi', '512Mi') to Docker format ('2g', '512m')."""
    s = mem_str.strip()
    lower = s.lower()
    for k8s_suffix, docker_suffix in _K8S_MEM_SUFFIXES.items():
        if lower.endswith(k8s_suffix):
            return s[:-len(k8s_suffix)] + docker_suffix
    if lower[-1:].isdigit() or lower.endswith(("k", "m", "g", "t", "b")):
        return s
    raise ValueError(f"Unsupported memory unit: {mem_str!r}")


def _extract_docker_error(stderr_text: str) -> str:
    """Extract the meaningful error from docker compose stderr, stripping progress noise."""
    marker = "Error response from daemon:"
    idx = stderr_text.find(marker)
    if idx != -1:
        return stderr_text[idx:].strip()[:500]
    idx2 = stderr_text.rfind("Error")
    if idx2 != -1:
        return stderr_text[idx2:].strip()[:500]
    return stderr_text.strip()[:500]


def _classify_docker_error(stderr_text: str) -> str | None:
    """对 docker compose 失败的 stderr 做模式匹配，返回中文引导文案。

    单纯的 _extract_docker_error 输出对用户不够友好——「TLS handshake timeout」
    本身用户不知道下一步该做什么。这里识别几类高频部署失败场景，给出可操作建议。
    无匹配时返回 None（调用方不附加提示）。
    """
    text = stderr_text.lower()

    # 1) 网络/镜像仓库连不通
    if any(kw in text for kw in (
        "tls handshake timeout",
        "no such host",
        "i/o timeout",
        "connection refused",
        "dial tcp",
    )):
        return (
            "无法连接镜像仓库。请手动 `docker pull <image>` 后重试，"
            "或在创建实例时通过 DOCKER_IMAGE 环境变量指向已在本地的镜像。"
        )

    # 2) 镜像仓库需要登录
    if "unauthorized" in text or "pull access denied" in text:
        return "镜像仓库需要登录。请先 `docker login <registry>` 后重试。"

    # 3) 镜像/标签不存在
    if "manifest unknown" in text or "manifest for" in text and "not found" in text:
        return "镜像或版本不存在。请检查 image_version 拼写，或确认该 tag 已发布到仓库。"

    # 4) 端口绑定失败 / 容器网络建立失败
    if any(kw in text for kw in (
        "failed to set up container networking",
        "driver failed programming external connectivity",
        "address already in use",
        "bind: address already in use",
        "port is already allocated",
    )):
        return (
            "宿主机端口被占用，Docker 无法完成端口绑定。"
            "请删除本实例后重新创建（系统会自动分配空闲端口），"
            "或手动执行 `docker ps` 找到占用该端口的容器并停止后重试。"
        )

    # 5) compose 未安装（兜底，create_instance 已有 FileNotFoundError 分支处理）
    if "docker compose" in text and "not found" in text:
        return "未安装 docker compose v2，请升级 Docker 或安装 docker-compose-v2。"

    return None


def _format_docker_failure(prefix: str, stderr_text: str) -> str:
    """组合「核心错误 + 引导提示」的完整 RuntimeError 文案。

    所有 docker compose ... 失败的 raise 路径统一走这里，前端 toast 既能
    看到原始 daemon 错误，也能看到下一步该怎么做。
    """
    err = _extract_docker_error(stderr_text)
    hint = _classify_docker_error(stderr_text)
    return f"{prefix}: {err}" + (f"\n提示：{hint}" if hint else "")


async def _run_docker(
    *args: str,
    stdout: int | None = None,
    stderr: int | None = None,
    timeout: float | None = None,
) -> tuple[int, bytes, bytes]:
    """跨平台 docker 子进程调用。

    Windows SelectorEventLoop 上 asyncio.create_subprocess_exec 会抛
    NotImplementedError（参见 CLAUDE.md 易踩点 #2），导致整个 docker 部署
    链路炸掉。本 helper 在 NotImplementedError 时自动回退到线程池里的
    同步 subprocess.run，把跨平台问题收敛在一个地方。

    返回 (returncode, stdout_bytes, stderr_bytes)；rc=0 表示成功。
    stdout / stderr 默认为 PIPE；显式传 subprocess.DEVNULL 可丢弃输出。
    """
    out_pipe = stdout if stdout is not None else asyncio.subprocess.PIPE
    err_pipe = stderr if stderr is not None else asyncio.subprocess.PIPE
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=out_pipe, stderr=err_pipe,
        )
        if timeout is not None:
            so, se = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        else:
            so, se = await proc.communicate()
        return proc.returncode or 0, so or b"", se or b""
    except NotImplementedError:
        # Windows SelectorEventLoop 不支持 asyncio subprocess → 走同步路径
        import subprocess

        def _run() -> tuple[int, bytes, bytes]:
            r = subprocess.run(
                list(args),
                stdout=subprocess.PIPE if out_pipe == asyncio.subprocess.PIPE else out_pipe,
                stderr=subprocess.PIPE if err_pipe == asyncio.subprocess.PIPE else err_pipe,
                timeout=timeout,
            )
            return r.returncode, r.stdout or b"", r.stderr or b""

        return await asyncio.to_thread(_run)


def _is_windows_path(path: str) -> bool:
    return bool(_WINDOWS_HOST_PATH_RE.match(path))


def _join_host_path(base: str, *parts: str) -> str:
    if _is_windows_path(base):
        return str(PureWindowsPath(base, *parts))
    return str(PurePosixPath(base, *parts))


def _pure_host_path(path: str) -> PureWindowsPath | PurePosixPath:
    if _is_windows_path(path):
        return PureWindowsPath(path)
    return PurePosixPath(path)


def _compose_path_for_slug(slug: str) -> str:
    return str(DOCKER_DATA_DIR / slug / "docker-compose.yml")


def _remap_legacy_compose_path(stored_path: str) -> str:
    if not stored_path:
        return ""

    try:
        rel = _pure_host_path(stored_path).relative_to(_pure_host_path(DOCKER_HOST_DATA_DIR))
    except ValueError:
        return ""

    return str(DOCKER_DATA_DIR.joinpath(*rel.parts))


def _resolve_compose_path(slug: str, stored_path: str) -> str:
    current_path = _compose_path_for_slug(slug)
    if os.path.exists(current_path):
        return current_path

    remapped_path = _remap_legacy_compose_path(stored_path)
    if remapped_path and os.path.exists(remapped_path):
        return remapped_path

    if stored_path and os.path.exists(stored_path):
        return stored_path

    return current_path


async def _seed_template_from_image(config: InstanceComputeConfig, data_dir: Path) -> None:
    """从镜像中提取配置模板到宿主机 data 目录（仅首次部署时需要）。

    Docker Compose 部署时，空目录 bind mount 到容器的 data_dir 会遮盖镜像内
    预置的模板文件。此处通过 docker create + cp 从镜像提取模板，确保 entrypoint
    首次启动时能正确生成 openclaw.json。
    """
    from app.services.runtime.registries.runtime_registry import RUNTIME_REGISTRY
    rt_spec = RUNTIME_REGISTRY.get(config.runtime)
    if not rt_spec:
        return

    template_rel = rt_spec.docker_seed_template_rel
    if not template_rel:
        return

    container_data_dir = rt_spec.data_dir_container_path
    host_template = data_dir / template_rel

    # 已存在则跳过（已有实例或已迁移数据）
    if host_template.exists():
        return

    image = config.env_vars.get("DOCKER_IMAGE", f"deskclaw:{config.image_version}")
    tmp_container = f"tmpl-seed-{config.slug}-{uuid.uuid4().hex[:8]}"

    try:
        rc, stdout, stderr = await _run_docker(
            "docker", "create", "--platform", "linux/amd64", "--name", tmp_container, image,
        )
        if rc != 0:
            logger.warning("seed_template: docker create failed: %s", stderr.decode().strip()[:300])
            return
        container_id = stdout.decode().strip()
        if not container_id:
            logger.warning("seed_template: docker create returned empty id for %s", config.slug)
            return

        try:
            rc, _, cp_stderr = await _run_docker(
                "docker", "cp",
                f"{container_id}:{container_data_dir}/{template_rel}",
                str(host_template),
            )
            if rc != 0:
                logger.warning("seed_template: docker cp failed: %s", cp_stderr.decode().strip()[:300])
                return
            logger.info("seed_template: copied %s from %s to %s", template_rel, image, host_template)
        finally:
            import subprocess as _subprocess
            await _run_docker(
                "docker", "rm", container_id,
                stdout=_subprocess.DEVNULL, stderr=_subprocess.DEVNULL,
            )
    except Exception:
        logger.warning("seed_template: unexpected error for %s", config.slug, exc_info=True)


def _build_compose_yaml(config: InstanceComputeConfig) -> dict:
    """Generate a docker-compose service definition with full resource config."""
    env = {
        k: _LOCALHOST_RE.sub(r"\1host.docker.internal\3", str(v))
        for k, v in config.env_vars.items()
    }
    host_port = env.get("DOCKER_HOST_PORT", "3000")

    from app.services.runtime.registries.runtime_registry import RUNTIME_REGISTRY
    rt_spec = RUNTIME_REGISTRY.get(config.runtime)
    container_data_dir = rt_spec.data_dir_container_path if rt_spec else "/root/.openclaw"
    host_data_dir = _join_host_path(DOCKER_HOST_DATA_DIR, config.slug, "data")

    main_service: dict = {
        "image": env.get("DOCKER_IMAGE", f"deskclaw:{config.image_version}"),
        # 本地有镜像就直接用，不再 HEAD registry。这样用户可手动 docker pull
        # 后离线部署，避开 TLS 握手超时 / 镜像源不通的环境问题。
        # Compose v2.20+ 支持；老版本会忽略此字段，行为退化为默认（仍可工作）。
        "pull_policy": "missing",
        "container_name": config.slug,
        "environment": env,
        "ports": [f"{host_port}:{config.gateway_port}"],
        "volumes": [{
            "type": "bind",
            "source": host_data_dir,
            "target": container_data_dir,
        }],
        "restart": "unless-stopped",
        "platform": "linux/amd64",
        "networks": [f"{config.slug}-net"],
        "extra_hosts": ["host.docker.internal:host-gateway"],
    }

    if rt_spec and rt_spec.docker_command:
        main_service["command"] = list(rt_spec.docker_command)

    if config.mem_limit:
        main_service["mem_limit"] = _parse_mem(config.mem_limit)
    if config.cpu_limit:
        try:
            parsed = _parse_cpu(config.cpu_limit)
            available = os.cpu_count() or 1
            if parsed <= available:
                main_service["cpus"] = parsed
            else:
                logger.warning(
                    "requested cpus %.2f exceeds available %d, skipping cpu limit",
                    parsed, available,
                )
        except (ValueError, TypeError):
            pass

    if config.companion and config.companion.enabled:
        companion = {
            "image": config.companion.image or "deskclaw-companion:latest",
            "pull_policy": "missing",  # 同 main_service：本地镜像优先，避开 registry 网络问题
            "container_name": f"{config.slug}-companion",
            "environment": config.companion.env_vars,
            "ports": [str(config.companion.port)],
            "restart": "unless-stopped",
            "platform": "linux/amd64",
            "depends_on": ["agent"],
            "networks": [f"{config.slug}-net"],
            "extra_hosts": ["host.docker.internal:host-gateway"],
        }
        return {
            "services": {"agent": main_service, "companion": companion},
            "networks": {f"{config.slug}-net": {"driver": "bridge"}},
        }

    return {
        "services": {"agent": main_service},
        "networks": {f"{config.slug}-net": {"driver": "bridge"}},
    }


class DockerComputeProvider:
    """Docker compose-based compute provider for local/dev agent instances."""

    provider_id = "docker"

    async def create_instance(
        self, config: InstanceComputeConfig, **kwargs,
    ) -> ComputeHandle:
        logger.info("DockerComputeProvider.create_instance: %s (slug=%s)", config.instance_id, config.slug)

        project_dir = str(DOCKER_DATA_DIR / config.slug)
        os.makedirs(project_dir, exist_ok=True)
        data_dir = DOCKER_DATA_DIR / config.slug / "data"
        os.makedirs(str(data_dir), exist_ok=True)

        # 从镜像中提取模板文件到宿主机 data 目录，确保 entrypoint 首次启动能生成配置
        await _seed_template_from_image(config, data_dir)

        compose = _build_compose_yaml(config)
        compose_path = _compose_path_for_slug(config.slug)

        try:
            import yaml
            with open(compose_path, "w") as f:
                yaml.dump(compose, f, default_flow_style=False)
        except ImportError:
            with open(compose_path, "w") as f:
                json.dump(compose, f, indent=2)

        try:
            rc, _, stderr = await _run_docker(
                "docker", "compose", "-f", compose_path, "up", "-d",
            )
            if rc != 0:
                raw = stderr.decode()
                logger.error("docker compose up failed: %s", raw)
                # 清理残留容器/网络，避免下次重建因"name already in use"再次失败
                await self._cleanup_on_failure(config.slug, compose_path)
                raise RuntimeError(_format_docker_failure("docker compose up 失败", raw))
        except FileNotFoundError:
            raise RuntimeError("docker compose 未安装")

        host_port = config.env_vars.get("DOCKER_HOST_PORT", "3000")
        host = _docker_endpoint_host()
        return ComputeHandle(
            provider=self.provider_id,
            instance_id=config.instance_id,
            namespace=config.namespace,
            endpoint=f"http://{host}:{host_port}",
            status="running",
            extra={"compose_path": compose_path, "slug": config.slug, "runtime": config.runtime},
        )

    async def _cleanup_on_failure(self, slug: str, compose_path: str) -> None:
        """创建失败时清理残留容器和网络，防止下次重建被「name already in use」卡住。"""
        import subprocess as _subprocess
        if compose_path and os.path.exists(compose_path):
            try:
                await _run_docker(
                    "docker", "compose", "-f", compose_path, "down", "--remove-orphans",
                    stderr=_subprocess.DEVNULL,
                )
            except Exception:
                pass
        # 兜底：直接 rm 容器和网络（compose down 失败时的保底清理）
        for name in (f"{slug}-companion", slug):
            try:
                await _run_docker(
                    "docker", "rm", "-f", name,
                    stdout=_subprocess.DEVNULL, stderr=_subprocess.DEVNULL,
                )
            except Exception:
                pass
        try:
            await _run_docker(
                "docker", "network", "rm", f"{slug}-net",
                stdout=_subprocess.DEVNULL, stderr=_subprocess.DEVNULL,
            )
        except Exception:
            pass
        logger.info("create_instance cleanup done for slug=%s", slug)

    async def destroy_instance(self, handle: ComputeHandle, **kwargs) -> None:
        logger.info("DockerComputeProvider.destroy_instance: %s", handle.instance_id)
        slug = handle.extra.get("slug", handle.instance_id)
        compose_path = _resolve_compose_path(slug, handle.extra.get("compose_path", ""))
        if compose_path and os.path.exists(compose_path):
            try:
                rc, _, stderr = await _run_docker(
                    "docker", "compose", "-f", compose_path, "down", "-v",
                )
                if rc == 0:
                    return
                logger.warning("docker compose down failed: %s", stderr.decode().strip()[:300])
            except Exception as e:
                logger.warning("docker compose down failed: %s", e)

        for container_name in (f"{slug}-companion", slug):
            try:
                rc, _, stderr = await _run_docker(
                    "docker", "rm", "-f", container_name,
                )
                if rc != 0 and "No such container" not in stderr.decode():
                    logger.warning("docker rm failed for %s: %s", container_name, stderr.decode().strip()[:300])
            except Exception as e:
                logger.warning("docker rm failed for %s: %s", container_name, e)

        try:
            rc, _, stderr = await _run_docker(
                "docker", "network", "rm", f"{slug}-net",
            )
            if rc != 0 and "No such network" not in stderr.decode():
                logger.warning("docker network rm failed for %s-net: %s", slug, stderr.decode().strip()[:300])
        except Exception as e:
            logger.warning("docker network rm failed for %s-net: %s", slug, e)

    async def get_status(self, handle: ComputeHandle) -> str:
        slug = handle.extra.get("slug", handle.instance_id)
        try:
            rc, stdout, _ = await _run_docker(
                "docker", "inspect", "--format", "{{.State.Status}}", slug,
            )
            if rc == 0:
                status = stdout.decode().strip()
                status_map = {"running": "running", "exited": "stopped", "paused": "stopped"}
                return status_map.get(status, status)
        except Exception:
            logger.warning("docker inspect failed for slug=%s", slug, exc_info=True)
        return "unknown"

    async def get_endpoint(self, handle: ComputeHandle) -> str:
        return handle.endpoint

    async def get_logs(self, handle: ComputeHandle, *, tail: int = 50) -> str:
        slug = handle.extra.get("slug", handle.instance_id)
        try:
            # docker logs 把 stderr 合并到 stdout（保留原行为）
            _, stdout, _ = await _run_docker(
                "docker", "logs", "--tail", str(tail), slug,
                stderr=asyncio.subprocess.STDOUT,
            )
            return stdout.decode() if stdout else ""
        except Exception:
            return ""

    async def update_instance(
        self, handle: ComputeHandle, config: InstanceComputeConfig,
    ) -> ComputeHandle:
        logger.info("DockerComputeProvider.update_instance: %s", handle.instance_id)
        await self.destroy_instance(handle)
        return await self.create_instance(config)

    async def restart_instance(self, handle: ComputeHandle) -> None:
        slug = handle.extra.get("slug", handle.instance_id)
        compose_path = _resolve_compose_path(slug, handle.extra.get("compose_path", ""))
        if compose_path and os.path.exists(compose_path):
            rc, _, stderr = await _run_docker(
                "docker", "compose", "-f", compose_path, "restart",
            )
            if rc != 0:
                raise RuntimeError(_format_docker_failure("docker compose restart 失败", stderr.decode()))
        else:
            rc, _, stderr = await _run_docker(
                "docker", "restart", slug,
            )
            if rc != 0:
                raise RuntimeError(_format_docker_failure("docker restart 失败", stderr.decode()))

    async def scale_instance(self, handle: ComputeHandle, replicas: int) -> ComputeHandle:
        slug = handle.extra.get("slug", handle.instance_id)
        compose_path = _resolve_compose_path(slug, handle.extra.get("compose_path", ""))
        if compose_path and os.path.exists(compose_path):
            rc, _, stderr = await _run_docker(
                "docker", "compose", "-f", compose_path, "up", "-d",
                "--scale", f"agent={replicas}",
            )
            if rc != 0:
                raise RuntimeError(_format_docker_failure("docker compose scale 失败", stderr.decode()))
        handle.extra["replicas"] = replicas
        return handle

    async def update_env_vars_and_restart(
        self, handle: ComputeHandle, env_updates: dict,
    ) -> None:
        """Patch env vars in the compose file and recreate the container.

        Reads the existing docker-compose.yml, merges *env_updates* into
        every service's environment block, writes the file back, then runs
        ``docker compose up -d``.  Docker Compose automatically recreates
        containers whose configuration has changed, so the updated env vars
        take effect without a separate restart step.
        """
        slug = handle.extra.get("slug", handle.instance_id)
        compose_path = _resolve_compose_path(slug, handle.extra.get("compose_path", ""))

        if not compose_path or not os.path.exists(compose_path):
            logger.warning("compose 文件不存在，降级为 docker restart: %s", slug)
            await self.restart_instance(handle)
            return

        try:
            import yaml as _yaml
            with open(compose_path, encoding="utf-8") as f:
                compose = _yaml.safe_load(f)
        except Exception as exc:
            raise RuntimeError(f"无法读取 docker-compose.yml: {compose_path}: {exc}") from exc

        for svc in (compose.get("services") or {}).values():
            env = svc.get("environment")
            if isinstance(env, dict):
                env.update({k: str(v) for k, v in env_updates.items()})

        try:
            import yaml as _yaml
            with open(compose_path, "w", encoding="utf-8") as f:
                _yaml.dump(compose, f, default_flow_style=False, allow_unicode=True)
        except Exception as exc:
            raise RuntimeError(f"无法写入 docker-compose.yml: {compose_path}: {exc}") from exc

        rc, _, stderr = await _run_docker(
            "docker", "compose", "-f", compose_path, "up", "-d",
        )
        if rc != 0:
            raise RuntimeError(
                _format_docker_failure("docker compose up 失败", stderr.decode())
            )

    async def health_check(self, handle: ComputeHandle) -> dict:
        try:
            status = await self.get_status(handle)
        except Exception as e:
            return {"healthy": False, "detail": f"docker inspect failed: {e}"}
        if status != "running":
            return {"healthy": False, "detail": f"container {status}"}

        runtime = (handle.extra or {}).get("runtime", "openclaw")
        from app.services.runtime.registries.runtime_registry import RUNTIME_REGISTRY
        rt_spec = RUNTIME_REGISTRY.get(runtime)
        probe_path = rt_spec.health_probe_path if rt_spec else "/"

        if probe_path is None:
            return {"healthy": True, "detail": "container running (no http probe)"}

        from app.services.runtime.compute.base import http_probe
        endpoint = handle.endpoint
        if endpoint:
            host = _docker_endpoint_host()
            if host != "localhost":
                endpoint = endpoint.replace("localhost", host).replace("127.0.0.1", host)
        return await http_probe(endpoint, path=probe_path)
