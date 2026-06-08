# 计算提供方（Compute Provider）部署指南

> 面向管理员：如何在 NoDeskClaw 中配置计算集群，让 AI 实例有地方运行。

---

## 1. 概述

NoDeskClaw 通过 **Compute Provider**（计算提供方）抽象来管理 AI 实例的运行环境。一个"集群"本质上就是一个计算提供方的实例。当前支持两种类型：

| Compute Provider | 适用场景 | 凭证要求 | 实例运行方式 |
|---|---|---|---|
| `docker` | 本地开发、小规模试用 | 无（需 Docker daemon 可访问） | 每个实例一个 Docker Compose 工程 |
| `k8s` | 生产、多实例 | KubeConfig | Deployment + Service + Ingress |

> `process`（本地子进程）已在注册表中登记，但未接入标准部署流程，仅作未来预留。

### 架构示意

```
用户在 Portal 创建实例
        │
        ▼
  deploy_service 按集群类型路由
        │
        ├── compute_provider == "docker"
        │       └── DockerComputeProvider
        │               └── docker compose up -d
        │
        └── compute_provider == "k8s"
                └── 内置 K8s 部署流水线
                        └── Namespace → ConfigMap → PVC → Deployment → Service → Ingress
```

---

## 2. Docker 集群（本地开发 / 试用）

### 前提条件

- 宿主机已安装 **Docker Engine** 和 **Docker Compose V2**（`docker compose version` 可正常执行）
- 后端进程能够访问 Docker daemon（通过 Docker socket）

### 2.1 Docker Compose 部署（推荐）

项目根目录的 `docker-compose.yml` 已预先为 Docker 计算配置好：

```yaml
nodeskclaw-backend:
  volumes:
    - type: bind
      source: /var/run/docker.sock
      target: /var/run/docker.sock
    - type: bind
      source: ${NODESKCLAW_DATA_DIR:-${HOME:-.}/.nodeskclaw/docker-instances}
      target: /nodeskclaw-data
  environment:
    DOCKER_DATA_DIR: /nodeskclaw-data
    DOCKER_HOST_DATA_DIR: ${NODESKCLAW_DATA_DIR:-${HOME:-.}/.nodeskclaw/docker-instances}
```

**关键挂载说明：**

| 挂载 | 用途 |
|---|---|
| `/var/run/docker.sock` | 让后端容器内的 `docker compose` 命令能够操作宿主机 Docker daemon |
| `NODESKCLAW_DATA_DIR` / `$HOME/.nodeskclaw/docker-instances` | 宿主机实例数据目录，挂载到后端容器内的 `/nodeskclaw-data` |

**Windows（Docker Desktop）注意事项：**

macOS/Linux 上可以直接使用默认值 `$HOME/.nodeskclaw/docker-instances`。Windows 上 `$HOME` 行为不可靠，必须在项目根目录 `.env` 中显式设置 `NODESKCLAW_DATA_DIR` 为宿主机绝对路径，否则 Compose 会立即报错。例如：

```bash
NODESKCLAW_DATA_DIR=C:\Users\yourname\.nodeskclaw\docker-instances
```

启动平台后，在 Portal 的**组织设置 → 集群**页面点击"添加集群"，选择 **Docker** 类型即可。后端会自动执行 `docker compose version` 来验证环境可用性。

### 2.2 本地开发（`./dev.sh`）

本地开发时，后端直接运行在宿主机上，天然可以访问 Docker daemon，无需额外配置。

宿主机直跑后端时，`DOCKER_DATA_DIR` 未设置时默认为 `~/.nodeskclaw/docker-instances`。Docker Compose 部署时，macOS/Linux 默认挂载 `$HOME/.nodeskclaw/docker-instances`；Windows 上若未设置 `NODESKCLAW_DATA_DIR` 会直接拒绝启动，`DOCKER_DATA_DIR` 在容器内固定为 `/nodeskclaw-data`。

### 2.3 Docker 实例的工作原理

创建 Docker 实例时，系统会：

1. **分配宿主机端口** — 从 `13000` 起递增，扫描已有实例避免冲突
2. **生成 Compose 文件** — 写入 `{DOCKER_DATA_DIR}/{slug}/docker-compose.yml`
3. **启动容器** — `docker compose -f <path> up -d`
4. **数据持久化** — 实例数据实际绑定到 `{DOCKER_HOST_DATA_DIR}/{slug}/data`，后端容器内对应路径为 `{DOCKER_DATA_DIR}/{slug}/data`

生成的 Compose 文件结构：

```yaml
services:
  agent:
    image: deskclaw:latest       # 由部署参数决定
    container_name: my-instance
    ports:
      - "13000:18789"            # 宿主机端口 : 容器网关端口
    volumes:
      - type: bind
        source: /host/path/to/docker-instances/my-instance/data
        target: /root/.openclaw
    platform: linux/amd64
    extra_hosts:
      - "host.docker.internal:host-gateway"
    restart: unless-stopped
networks:
  my-instance-net:
    driver: bridge
```

### 2.4 Docker 实例的生命周期

| 操作 | 底层命令 |
|---|---|
| 创建 / 部署 | `docker compose -f <path> up -d` |
| 重启 | `docker compose -f <path> restart` |
| 查看日志 | `docker logs --tail 50 <container>` |
| 扩缩容 | `docker compose -f <path> up -d --scale agent=N` |
| 删除 | `docker compose -f <path> down -v` |
| 健康检查 | `docker inspect` + HTTP 探针 |

### 2.5 资源限制与自适应

- 所有实例共享宿主机资源；通过 `mem_limit` / `cpus` 做基础隔离
- **CPU 自适应**：如果请求的 CPU 数（默认 2 核）超过宿主机可用 CPU 数，系统会自动跳过 CPU 限制（即不设上限，使用全部可用 CPU），避免 Docker daemon 拒绝创建容器
- 实例 URL 为 `localhost:{port}` — 不支持自定义域名或 HTTPS
- 不支持 K8s 特有功能：集群概览（节点 / CPU / 内存统计）、StorageClass 选择、Pod Events、kubectl exec

---

## 3. Kubernetes 集群（生产环境）

### 前提条件

- 一个可用的 Kubernetes 集群（v1.24+）
- 具备足够权限的 **KubeConfig**
- 集群中已部署 **Ingress Controller**（默认 nginx）
- `.env` 中已配置 **`ENCRYPTION_KEY`**（用于加密存储 KubeConfig）

### 3.1 KubeConfig 权限要求

NoDeskClaw 需要以下 K8s API 权限来管理实例：

| 资源 | 操作 | 用途 |
|---|---|---|
| `namespaces` | create, get, delete | 每个实例独占一个 namespace |
| `deployments` | create, get, patch, delete, list | 实例容器编排 |
| `services` | create, get, delete | 网络暴露 |
| `ingresses` | create, get, delete | 域名路由（需 Ingress Controller） |
| `configmaps` | create, get, patch, delete | 实例配置 |
| `persistentvolumeclaims` | create, get, delete | 数据持久化 |
| `networkpolicies` | create, get, delete | 出站流量控制 |
| `pods` | get, list, log | 状态查询和日志 |
| `nodes` | get, list | 集群概览、连接测试 |
| `events` | list | 部署事件追踪 |

> 建议为 NoDeskClaw 创建专用的 ServiceAccount + ClusterRole，避免直接使用 admin kubeconfig。

### 3.2 添加 K8s 集群

在 Portal 的**组织设置 → 集群**页面：

1. 点击"添加集群"
2. 选择 **Kubernetes** 类型
3. 选择云厂商标签（VKE / ACK / TKE / 自建）— 仅作 UI 标识，不影响功能
4. 粘贴 KubeConfig 内容
5. 设置 Ingress Class（默认 `nginx`）
6. （可选）填写 Proxy Endpoint — 用于通过网关集群路由流量
7. 提交后系统自动执行连接测试（`VersionApi.get_code` + `list_node`）

### 3.3 KubeConfig 认证方式

系统自动解析 KubeConfig 并识别认证方式：

| auth_type | 说明 | 注意事项 |
|---|---|---|
| `token` | 静态 Bearer Token | 注意 Token 有效期 |
| `client-certificate` | 客户端证书认证 | 证书过期需更新 KubeConfig |
| `exec-based` | 通过外部命令获取凭证 | 后端环境需安装对应 CLI 工具 |
| `oidc` | OpenID Connect | 需确保 OIDC Provider 可达 |

### 3.4 集群配置项

创建集群时写入 `provider_config`（JSONB）的字段：

| 字段 | 说明 | 默认值 |
|---|---|---|
| `cloud_vendor` | 云厂商标签（vke/ack/tke/custom） | 来自请求 |
| `auth_type` | 认证方式（自动解析） | — |
| `api_server_url` | K8s API Server 地址（自动解析） | — |
| `ingress_class` | Ingress Controller class 名称 | `nginx` |
| `k8s_version` | K8s 版本（连接测试时获取） | — |

### 3.5 K8s 实例部署流水线

当用户在 K8s 集群上创建实例时，后端会执行完整的异步部署流水线：

```
① 创建 Namespace（nodeskclaw-default-{slug}）
    ↓
② 创建 ConfigMap（实例配置）
    ↓
③ 创建 PVC（通过 StorageClass 持久化存储）
    ↓
④ 创建 Deployment（DeskClaw 容器）
    ↓
⑤ 创建 Service（ClusterIP）
    ↓
⑥ 创建 Ingress（域名路由）
    ↓
⑦ 创建 NetworkPolicy（出站流量控制）
    ↓
⑧ 等待 Pod Ready
    ↓
⑨ 后置步骤（LLM 配置同步、Gene 安装等）
```

### 3.6 K8s 基础设施要求

#### Ingress Controller

实例通过 Ingress 对外暴露 HTTP(S) 访问，集群中必须有对应的 Ingress Controller：

- 默认期望：`ingressClassName: nginx`
- 可在创建集群时通过 `ingress_class` 自定义
- 部署说明详见 `nodeskclaw-artifacts/ingress-controller/`

#### 存储（PVC）

每个实例会创建一个 PVC 用于数据持久化：

- 默认 StorageClass：使用集群标记为 default 的 SC（用户创建实例时可手动选择）
- 默认容量：`80Gi`
- 可在创建实例页面调整

#### 网络策略

部署时会自动创建 NetworkPolicy 来控制实例出站流量。相关环境变量：

| 变量 | 说明 | 示例 |
|---|---|---|
| `EGRESS_DENY_CIDRS` | 禁止出站的 CIDR 列表 | `10.0.0.0/8,172.16.0.0/12` |
| `EGRESS_ALLOW_PORTS` | 允许出站的端口列表 | `443,80` |

---

## 4. 环境变量参考

### 通用（所有 Compute Provider）

| 变量 | 必填 | 说明 | 默认值 |
|---|---|---|---|
| `ENCRYPTION_KEY` | 是（K8s 必填） | KubeConfig 加密密钥（32 字节 base64） | — |

### Docker 专用

| 变量 | 必填 | 说明 | 默认值 |
|---|---|---|---|
| `DOCKER_DATA_DIR` | 否 | 后端工作目录；Compose 部署时固定为 `/nodeskclaw-data` | `~/.nodeskclaw/docker-instances` |
| `DOCKER_HOST_DATA_DIR` | 否 | 后端为子容器生成绑定挂载时使用的宿主机路径 | 同 `NODESKCLAW_DATA_DIR` 或 `$HOME/.nodeskclaw/docker-instances` |
| `NODESKCLAW_DATA_DIR` | Windows 必填 | Compose 中宿主机绑定源路径 | macOS/Linux 默认 `$HOME/.nodeskclaw/docker-instances` |

### K8s 专用

| 变量 | 必填 | 说明 | 默认值 |
|---|---|---|---|
| `VKE_SUBNET_ID` | 火山云 VKE 集群需要 | VKE 子网 ID | — |
| `EGRESS_DENY_CIDRS` | 否 | NetworkPolicy 出站拒绝 CIDR | — |
| `EGRESS_ALLOW_PORTS` | 否 | NetworkPolicy 出站允许端口 | — |
| `IMAGE_REGISTRY` | 否 | 容器镜像仓库前缀 | — |

---

## 5. 集群管理 API

| 方法 | 路径 | 说明 | Docker/K8s |
|---|---|---|---|
| `POST` | `/clusters` | 创建集群 | 两者 |
| `GET` | `/clusters` | 列出集群 | 两者 |
| `GET` | `/clusters/{id}` | 集群详情 | 两者 |
| `PUT` | `/clusters/{id}` | 更新集群信息 | 两者 |
| `DELETE` | `/clusters/{id}` | 删除集群（级联软删除实例） | 两者 |
| `POST` | `/clusters/{id}/test` | 测试连接 | 两者（Docker 验证 compose，K8s 验证 API Server） |
| `POST` | `/clusters/{id}/kubeconfig` | 更新 KubeConfig | 仅 K8s |
| `GET` | `/clusters/{id}/overview` | 集群资源概览（节点 / CPU / 内存） | 仅 K8s |
| `GET` | `/clusters/{id}/health` | 集群健康状态 | 仅 K8s |

### 创建集群请求示例

Docker 集群：

```json
{
  "name": "Local Docker",
  "compute_provider": "docker"
}
```

K8s 集群：

```json
{
  "name": "Production Cluster",
  "compute_provider": "k8s",
  "kubeconfig": "apiVersion: v1\nkind: Config\n...",
  "provider": "vke",
  "ingress_class": "nginx"
}
```

---

## 6. Proxy Endpoint（可选，网关代理）

适用于实例集群不直接暴露公网的场景。配置后，系统会在**网关集群**上创建一个 ExternalName Service，把流量代理到实例集群。

```
用户浏览器 → 网关集群 Ingress → ExternalName Service → 实例集群
```

- 在创建或更新集群时设置 `proxy_endpoint`
- 网关集群的 KubeConfig 通过 `GATEWAY_KUBECONFIG` 环境变量配置

---

## 7. 常见问题

### Docker 集群创建失败：无法连接 Docker daemon

**原因**：后端无法访问 Docker socket。

**排查步骤**：
1. Docker Compose 部署：确认 `docker-compose.yml` 中 `/var/run/docker.sock` 挂载正确
2. 宿主机直跑：确认当前用户在 `docker` 用户组中
3. 验证命令：`docker compose version`

### K8s 集群连接测试失败

**排查步骤**：
1. 确认 KubeConfig 中的 API Server 地址从后端网络可达
2. 确认凭证未过期（Token / 证书）
3. 确认 `ENCRYPTION_KEY` 配置正确（密钥不匹配会导致 KubeConfig 解密失败）

### Docker 部署失败：Error response from daemon: range of CPUs

**原因**：请求的 CPU 数超过宿主机可用 CPU 数。旧版本使用固定默认值 `cpus: 2.0`，在单核机器上会触发此错误。

**修复**：升级到包含 CPU 自适应修复的版本。系统会自动检测可用 CPU 数并跳过超限的限制配置。

### Docker 实例无法访问

**原因**：端口冲突或 Docker 网络问题。

**排查步骤**：
1. 检查分配的端口（从 13000 起）是否被宿主机其他进程占用
2. 检查容器状态：`docker ps -a | grep <slug>`
3. 查看容器日志：`docker logs <slug>`

### K8s 实例一直停留在"部署中"

**排查步骤**：
1. 检查 Pod 状态：`kubectl get pods -n nodeskclaw-default-<slug>`
2. 查看 Events：`kubectl describe pod <pod-name> -n <namespace>`
3. 常见原因：镜像拉取失败（ImagePullBackOff）、资源不足（Pending）、PVC 绑定失败
