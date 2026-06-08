# 运行时镜像构建指南

> 面向开发者：如何构建、升级和管理 NoDeskClaw 中驱动 AI 员工实例的容器镜像。

---

## 1. 概述

NoDeskClaw 通过**运行时引擎（Runtime Engine）**承载 AI 员工实例。每种引擎都以独立的 Docker 镜像形式发布，镜像由上游包管理器构建，**不**直接从本仓库源码编译。

| 引擎 | 基础镜像 | 安装来源 | 监听端口 | 适用场景 |
|--------|-----------|---------------|------|----------|
| **OpenClaw** | `node:22-bookworm-slim` | npm `openclaw` | 18789 | 全功能 AI Agent，TypeScript 生态 |
| **Nanobot** | `python:3.13-slim-bookworm` | PyPI `nanobot-ai` | 18790 | 轻量 Python 引擎 |

### 与平台组件的关系

```
nodeskclaw-artifacts/build.sh     ← 运行时引擎镜像（本文档）
deploy/cli.sh                     ← 平台组件镜像（backend / portal / admin / llm-proxy）
```

两条构建流水线完全独立。

### 两层镜像结构

每个引擎支持 Base + Security 的双层架构：

```
┌──────────────────────────────┐
│  Security 层（可选）         │  Tag: v2026.3.13-sec
│  FROM base + 安全层插件      │
├──────────────────────────────┤
│  Base 层                     │  Tag: v2026.3.13
│  系统依赖 + 引擎安装 + 脚本   │
└──────────────────────────────┘
```

| 层 | Dockerfile | 构建上下文 | 说明 |
|-------|-----------|---------------|-------------|
| Base | `Dockerfile` | 引擎目录（例如 `openclaw-image/`） | 引擎本体 + 启动脚本 + 配置模板 |
| Security | `Dockerfile.security` | **项目根目录** | FROM base 镜像 + 安全层代码 |

---

## 2. 快速开始

### 前提条件

- Docker Desktop 或 Docker Engine（支持 BuildKit）
- Apple Silicon 用户：脚本会自动指定 `--platform linux/amd64`（目标集群架构）
- npm（OpenClaw 版本校验）、python3（Nanobot 版本检测）

### 统一入口：`build.sh`

所有引擎共用同一个入口脚本 `nodeskclaw-artifacts/build.sh`：

```bash
cd nodeskclaw-artifacts

# 自动检测最新版本，构建 + 推送
./build.sh openclaw
./build.sh nanobot
./build.sh all                          # 所有引擎

# 指定版本
./build.sh openclaw --version 2026.3.13
./build.sh nanobot --version 0.1.4

# 仅构建，跳过推送
./build.sh openclaw --build-only

# 跳过验证（在 Apple Silicon 上由于 QEMU 模拟会很慢）
./build.sh openclaw --skip-verify

# 构建全部引擎，不推送、不验证
./build.sh all --build-only --skip-verify
```

### 自动化构建流水线

```
1. 版本检测（未指定 --version 时）
   ├── OpenClaw → npm view openclaw versions
   └── Nanobot  → PyPI JSON API
        ↓
2. 版本校验（OpenClaw 检查 npm registry）
        ↓
3. docker build --platform linux/amd64
        ↓
4. 打 Tag：v{version}（例如 v2026.3.13）
        ↓
5. 验证（docker run 检查版本号、二进制路径）
        ↓
6. docker push 到容器镜像仓库
```

### 安全层构建

安全层在 base 镜像之上叠加安全插件。**构建上下文为项目根目录**（以便访问 `*-security-layer/` 目录）：

```bash
cd nodeskclaw-artifacts

# OpenClaw：先构建 base，再构建 security
./build.sh openclaw --version 2026.3.13 --build-only
./build.sh openclaw --with-security --base-tag v2026.3.13 --build-only

# Nanobot：同理
./build.sh nanobot --version 0.1.4 --build-only
./build.sh nanobot --with-security --base-tag v0.1.4 --build-only
```

安全层 Tag 格式：`v{VERSION}-sec`（例如 `v2026.3.13-sec`）。

---

## 3. 各引擎构建细节

### 3.1 OpenClaw

**Dockerfile 关键步骤：**

1. `node:22-bookworm-slim` 基础镜像
2. apt 安装系统依赖：git、openssh-client、python3、jq、curl 等
3. pip 安装 Python 依赖：requests、tos
4. `npm install -g openclaw@${VERSION} @nodeskai/genehub`
5. 预创建 `/root/.openclaw/` 目录树（agents、config、credentials、extensions、skills 等）
6. COPY 配置模板 `openclaw.json.template` 和启动脚本
7. 写入版本标记 `/root/.openclaw-version`

**构建参数：**

| 参数 | 说明 | 默认值 |
|----------|-------------|---------|
| `NODE_VERSION` | Node.js 大版本号 | `22` |
| `OPENCLAW_VERSION` | npm 包版本 | `2026.3.13` |
| `IMAGE_VERSION` | 镜像 Tag | `v2026.3.13` |

**安全层：** `Dockerfile.security` 直接 `FROM base`，将 `openclaw-security-layer/` COPY 到 `extensions/` 目录。OpenClaw 原生支持从 extensions 自动加载 TypeScript 插件。

### 3.2 Nanobot

**Dockerfile 关键步骤：**

1. `python:3.13-slim-bookworm` 基础镜像
2. apt 安装 ca-certificates、curl、gettext-base
3. `pip install nanobot-ai==${VERSION}`
4. COPY 并 pip 安装 `nodeskclaw-tunnel-bridge`
5. COPY 配置模板 `nanobot.yaml.template` 和启动脚本

**构建参数：**

| 参数 | 说明 | 默认值 |
|----------|-------------|---------|
| `NANOBOT_VERSION` | PyPI 包版本 | `0.1.4` |
| `IMAGE_VERSION` | 镜像 Tag | `v0.1.4` |

**安全层：** `Dockerfile.security` FROM base + `pip install nanobot-security-layer/` + 将 CMD 替换为 `python -m nanobot_security_layer.startup`（在启动 nanobot 前做 monkey-patch）。

---

## 4. 容器启动流程（以 OpenClaw 为例）

### Init Container（K8s 部署）

Init Container 在主容器启动前运行 `init-container.sh`，处理 PVC 数据初始化：

```
PVC 是否为空？
  ├── 是 → 首次部署：拷贝 /root/.openclaw 模板到 PVC，写入版本标记
  └── 否 → 读取 PVC 版本号
              ├── 版本一致 → 跳过
              └── 版本不同 → 轻量升级：
                    ├── 更新版本标记
                    ├── 合并内置插件（保留用户自定义插件）
                    ├── 补全新版本新增的子目录
                    └── 更新 shell 配置
```

### 主容器启动（docker-entrypoint.sh）

```
1. 配置初始化
   ├── OPENCLAW_FORCE_RECONFIG=true → 从模板重新生成 openclaw.json
   ├── 配置文件不存在 → 首次启动，从模板生成
   └── 配置文件已存在 → 跳过
       ↓
2. 配置补全（兼容旧版 PVC）
   └── 检查并补全缺失的 controlUi 字段
       ↓
3. 凭证注入
   └── OPENCLAW_CREDENTIALS_JSON → 写入 credentials/default.json
       ↓
4. 清理 jiti 编译缓存
       ↓
5. exec openclaw gateway（前台运行，PID 1 接收 SIGTERM）
```

### 关键环境变量

| 变量 | 说明 | 默认值 |
|----------|-------------|---------|
| `OPENCLAW_GATEWAY_PORT` | Gateway 监听端口 | `18789` |
| `OPENCLAW_GATEWAY_BIND` | 绑定策略（`lan` = 0.0.0.0） | `lan` |
| `OPENCLAW_GATEWAY_TOKEN` | 认证 Token（未设置时自动生成） | 必填 |
| `OPENCLAW_LOG_LEVEL` | 日志级别 | `info` |
| `OPENCLAW_FORCE_RECONFIG` | 设为 `true` 时强制重新生成配置 | `false` |
| `OPENCLAW_CREDENTIALS_JSON` | JSON 凭证，写入 credentials/ | 可选 |
| `OPENAI_API_KEY` | OpenAI 模型 Key | 可选 |
| `ANTHROPIC_API_KEY` | Anthropic 模型 Key | 可选 |
| `SECURITY_LAYER_ENABLED` | 安全层开关（安全层镜像预设 `true`） | `false` |

---

## 5. 版本管理

### 手动检查更新

每个引擎目录下都有 `check-update.sh` 脚本：

```bash
# 检查是否有新版本
cd nodeskclaw-artifacts/openclaw-image && ./check-update.sh

# 检查并自动更新 Dockerfile 中的版本号
./check-update.sh --update
```

各引擎的版本检测逻辑：

| 引擎 | 数据源 | 稳定版过滤规则 |
|--------|--------|-----------------------|
| OpenClaw | `npm view openclaw versions` | `YYYY.M.DD` 格式，排除 `-beta`、`-rc` 等后缀 |
| Nanobot | PyPI JSON API | `X.Y.Z` 格式，排除预发布版本 |

### 自动版本检测（GitHub Actions）

`.github/workflows/check-runtime-updates.yml` 定义了定时工作流：

- **触发频率**：每天 UTC 08:00（北京时间 16:00）
- **运行方式**：三个引擎作为独立 Job 并行运行
- **发现新版本**：自动更新 Dockerfile 中的版本 ARG，并创建 PR
- **PR 合并后**：人工执行 `./build.sh` 构建并推送

```
定时触发 → 读取 Dockerfile 当前版本 → 查询上游最新版本 → 版本不同？
    ├── 否 → 结束
    └── 是 → 更新 Dockerfile → 创建 PR（chore/{engine}-{version}）
                                       ↓
                                人工审核合并
                                       ↓
                                手动执行 ./build.sh 构建并推送
```

---

## 6. `build.sh` 完整参数参考

```
./build.sh <engine> [选项]
```

| 参数 | 说明 | 示例 |
|-----------|-------------|---------|
| `<engine>` | 引擎名称 | `openclaw` / `nanobot` / `all` |
| `--version <ver>` | 指定版本（省略则自动检测） | `--version 2026.3.13` |
| `--build-only` | 仅构建，不推送 | |
| `--skip-verify` | 跳过构建后验证 | |
| `--with-security` | 构建安全层镜像（需配合 `--base-tag`） | |
| `--base-tag <tag>` | 安全层使用的基础镜像 Tag | `--base-tag v2026.3.13` |

### 镜像仓库命名

| 引擎 | 镜像全名 |
|--------|----------------|
| OpenClaw | `{REGISTRY_HOST}/{NAMESPACE}/deskclaw-openclaw:{tag}` |
| Nanobot | `{REGISTRY_HOST}/{NAMESPACE}/deskclaw-nanobot:{tag}` |

Tag 格式：Base 层 `v{version}`，Security 层 `v{version}-sec`。

---

## 7. 构建后验证

`build.sh` 默认会运行容器验证（可用 `--skip-verify` 跳过）：

```bash
# OpenClaw
docker run --rm <image> node --version          # Node.js 版本
docker run --rm <image> openclaw --version       # OpenClaw 版本
docker run --rm <image> cat /root/.openclaw-version  # 版本标记
docker run --rm <image> ls /root/.openclaw/      # 目录结构

# Nanobot
docker run --rm <image> python --version
docker run --rm <image> pip show nanobot-ai      # 包版本
```

---

## 8. 目录结构参考

```
nodeskclaw-artifacts/
├── build.sh                         # 统一构建入口
├── common.sh                        # 公共函数（仓库配置、docker_build 封装）
├── openclaw-image/
│   ├── Dockerfile                   # Base 镜像
│   ├── Dockerfile.security          # 安全层镜像
│   ├── docker-entrypoint.sh         # 容器启动脚本
│   ├── init-container.sh            # K8s Init Container
│   ├── openclaw.json.template       # 配置模板（envsubst）
│   └── check-update.sh             # npm 版本检测
└── nanobot-image/
    ├── Dockerfile                   # Base：pip install
    ├── Dockerfile.security          # Security：pip install + CMD wrapper
    ├── nanobot.yaml.template        # 配置模板
    ├── docker-entrypoint.sh
    ├── check-update.sh             # PyPI 版本检测
    └── README.md
```

---

## 9. 常见问题

### Apple Silicon 上构建很慢

脚本强制使用 `--platform linux/amd64` 进行交叉编译。QEMU 模拟 x86_64 会显著拖慢构建速度。建议：
- 使用 `--skip-verify` 跳过验证步骤（验证需要启动 amd64 容器）

### 构建过程中 npm install 失败

检查代理设置。`common.sh` 中的 `docker_build` 会显式清空所有代理环境变量（`http_proxy`、`https_proxy`、`HTTP_PROXY`、`HTTPS_PROXY`），确保容器内直接访问 npm registry。

### 找不到指定版本

OpenClaw 构建前会校验 npm 上是否存在该版本。若校验失败：
- 检查版本号格式（`YYYY.M.DD`，不带 `v` 前缀）
- 手动验证：`npm view openclaw@{version} version`

### 推送到镜像仓库失败

请确保已登录目标 OCI 仓库：

```bash
docker login {REGISTRY_HOST}
```
