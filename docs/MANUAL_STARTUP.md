# NoDeskClaw 手动启动指南（EE 模式 / Windows + Git Bash）

> 适用场景：Windows 本机开发，企业内部使用（EE 模式），通过三个 Git Bash 窗口
> 手动起 backend / llm-proxy / portal 三个服务。
>
> 为什么不用 `./dev.sh ee`：MSYS/Git Bash 下 bash 后台管道（`cmd | sed &`）的 PID
> 跟踪和真实 Linux 不一致，`dev.sh` 的 `wait_for_children` 会误判进程已死、立即退出，
> banner 不出来、Ctrl+C 也控制不到子进程。手动起三个窗口最稳，且每个服务的报错都
> 直接显示在自己窗口，调试最快。

---

## 0. 前置条件

| 工具 | 版本要求 | 备注 |
|------|---------|------|
| Git for Windows | 含 Git Bash | 终端环境（不要用 PowerShell 调 bash） |
| [uv](https://docs.astral.sh/uv/) | ≥ 0.5 | Python 包管理器 |
| [Node.js](https://nodejs.org/) | ≥ 18 | 推荐 LTS（24.x 验证通过） |
| Docker Desktop | 任意 | 跑 PostgreSQL |

### 把 uv / node 加进 Git Bash 的 PATH（一次性）

独立打开的 Git Bash **不会**继承 PowerShell/Anaconda 的 PATH，导致找不到 `uv`。
在 Git Bash 里执行一次：

```bash
echo 'export PATH="/c/Users/gg102/miniconda3/Scripts:/c/Program Files/nodejs:$PATH"' >> ~/.bashrc
source ~/.bashrc
which uv && which node   # 应输出两条路径，证明 PATH 已生效
```

> 若 uv 装在别的位置（如 `/c/Users/<你>/.cargo/bin`），把路径替换成实际安装路径。

---

## 1. 启动 PostgreSQL（Docker）

```bash
# 首次：创建并启动容器
docker run -d \
  --name nodeskclaw-postgres \
  -e POSTGRES_DB=nodeskclaw \
  -e POSTGRES_USER=nodeskclaw \
  -e POSTGRES_PASSWORD=nodeskclaw123 \
  -p 5432:5432 \
  postgres:16-alpine

# 后续：直接启动已有容器
docker start nodeskclaw-postgres

# 验证就绪
docker exec nodeskclaw-postgres pg_isready -U nodeskclaw
```

---

## 2. 配置 `nodeskclaw-backend/.env`（一次性）

```env
# 数据库
DATABASE_URL=postgresql+asyncpg://nodeskclaw:nodeskclaw123@localhost:5432/nodeskclaw

# EE 模式（企业内部使用，启用 multi_org / platform_admin / advanced_rbac 等全部 EE feature）
NODESKCLAW_EDITION=ee

# LLM Proxy 地址（手动启动必须显式设置，dev.sh 是自动注入的）
LLM_PROXY_URL=http://localhost:4511
LLM_PROXY_INTERNAL_URL=http://localhost:4511

# 超管初始账号
INIT_ADMIN_ACCOUNT=admin
INIT_EE_ADMIN_ACCOUNT=deskclaw-admin
# 想强制重置密码时改为 true 重启一次即可，之后改回 false
RESET_ADMIN_PASSWORD=false
RESET_EE_ADMIN_PASSWORD=false

# JWT / 加密密钥（生产务必替换）
JWT_SECRET=change-me-in-production
ENCRYPTION_KEY=change-me-32-bytes-base64-key__=
```

---

## 3. 执行数据库迁移（一次性 / 模型变更后）

在 Git Bash 里：

```bash
cd /c/Users/gg102/my_project/nodeskclaw/nodeskclaw-backend
uv run alembic upgrade head
```

输出 `INFO  [alembic.runtime.migration] Will assume transactional DDL.` 即成功。

---

## 4. 启动三个服务（三个 Git Bash 窗口）

> **启动顺序**：llm-proxy → backend → portal。Backend 启动时虽不强依赖 llm-proxy 已 ready，
> 但 4511 端口先占住更稳。

### 窗口 ① — LLM Proxy（端口 4511）

```bash
cd /c/Users/gg102/my_project/nodeskclaw/nodeskclaw-llm-proxy
export DATABASE_URL="postgresql+asyncpg://nodeskclaw:nodeskclaw123@localhost:5432/nodeskclaw"
uv run uvicorn app.main:app --host 0.0.0.0 --port 4511
```

看到 `Uvicorn running on http://0.0.0.0:4511` 即就绪。

### 窗口 ② — Backend（端口 4510，EE 模式）

```bash
cd /c/Users/gg102/my_project/nodeskclaw/nodeskclaw-backend
uv run uvicorn app.main:app --host 0.0.0.0 --port 4510 --reload
```

启动成功标志：

```
INFO  FeatureGate: edition=ee (env override), ee_features=13
INFO  Application startup complete.
INFO  Uvicorn running on http://0.0.0.0:4510
```

**留意日志里打印的超管账号/初始密码**，登录要用。

### 窗口 ③ — Portal（端口 4517）

```bash
cd /c/Users/gg102/my_project/nodeskclaw/nodeskclaw-portal
npm run dev
```

看到 `Local:   http://localhost:4517/` 即就绪。

---

## 5. 验证 EE 模式生效

| 检查项 | 方法 | 预期 |
|--------|------|------|
| Backend 边界 | 浏览器访问 http://localhost:4510/docs | 看到 FastAPI 文档页 |
| Edition | 浏览器访问 http://localhost:4510/api/v1/system/info | JSON 含 `"edition": "ee"` |
| 全部 EE feature | 同上 | `features` 数组里 `enabled: true` |
| Portal 入口 | 浏览器访问 http://localhost:4517 | 看到登录页 |
| Admin 路由 | 登录后访问 http://localhost:4517/admin/orgs | 看到组织管理列表 |

---

## 6. 服务地址速查

| 服务 | 地址 | 备注 |
|------|------|------|
| Backend API | http://localhost:4510 | `/docs` 看 OpenAPI |
| LLM Proxy | http://localhost:4511 | 内部服务，无 UI |
| Portal | http://localhost:4517 | 用户门户 + Admin 后台合并入口 |
| PostgreSQL | localhost:5432 | Docker 容器 `nodeskclaw-postgres` |

> Admin 独立前端（4518）已合并到 portal，不再单独启动。
> `ee/nodeskclaw-frontend/` 目录已无需存在。

---

## 7. 停止服务

每个窗口 `Ctrl+C` 即可。如残留进程：

```bash
# 查端口占用
netstat -ano | grep -E ":(4510|4511|4517) "

# 用上一步输出的 PID 杀掉
taskkill //F //PID <PID>
```

PostgreSQL：

```bash
docker stop nodeskclaw-postgres   # 停止
docker start nodeskclaw-postgres  # 恢复
```

---

## 8. 常见问题

### Q1: `[dev] ERROR: 未找到 uv`

Git Bash 没继承 PATH。按本文「前置条件」节把 PATH 写入 `~/.bashrc` 即可。

### Q2: `LLM_PROXY_URL 未配置，服务无法启动`

`.env` 里缺 `LLM_PROXY_URL=http://localhost:4511`。按本文「2. 配置 .env」补上。

### Q3: 数据库连接失败 `getaddrinfo failed`，URL 里出现 `<host>`

`.env` 里 `DATABASE_URL` 还是占位符模板，按本文「2. 配置 .env」改成实际地址。

### Q4: PowerShell 调 `& bash dev.sh ee` 后服务很快全部退出

PowerShell 通过 `&` 启动 bash 时，后台进程没有控制终端，会被立即回收。
**必须用真正的 Git Bash 终端**，从开始菜单或文件资源管理器右键「Open Git Bash here」打开。

### Q5: `./dev.sh ee` 跑到「启动服务...」就退出，看不到 banner

MSYS bash 的后台管道 PID 跟踪 bug。**按本文三窗口手动启**，不要用 `dev.sh`。

### Q6: 端口已被占用

```bash
netstat -ano | grep ":4510"      # 查 PID
taskkill //F //PID <PID>          # 杀掉
```

### Q7: 依赖未安装

```bash
cd nodeskclaw-backend     && uv sync
cd nodeskclaw-llm-proxy   && uv sync
cd nodeskclaw-portal      && npm install
```

### Q8: 复制粘贴命令报 `bash: $'\302\226': command not found`

复制时带了不可见 Unicode 控制字符。在 Git Bash 里**手动键入**命令，或先 `clear` 再粘贴。

---

## 9. 切换回 CE 模式（如需要）

1. 改 `.env`：`NODESKCLAW_EDITION=ce`
2. 重启 backend 窗口
3. Portal 不需重启，`/api/v1/system/info` 返回 `ce` 后前端会自动隐藏 EE feature 入口

---

## 附录：每日开发启动顺序（快速回顾）

1. 确认 Docker Desktop 已开 → `docker start nodeskclaw-postgres`
2. Git Bash 窗口 ① → `cd .../nodeskclaw-llm-proxy && uv run uvicorn app.main:app --host 0.0.0.0 --port 4511`
3. Git Bash 窗口 ② → `cd .../nodeskclaw-backend && uv run uvicorn app.main:app --host 0.0.0.0 --port 4510 --reload`
4. Git Bash 窗口 ③ → `cd .../nodeskclaw-portal && npm run dev`
5. 浏览器开 http://localhost:4517 开始干活
