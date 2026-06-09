#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# OpenClaw 容器启动脚本
#
# 职责:
#   1. 配置初始化 - 从模板生成 openclaw.json（首次 / 强制重建）
#   2. 凭证注入   - 将环境变量中的凭证写入文件
#   3. 缓存清理   - 清理 jiti 编译缓存
#   4. 前台启动   - exec 让 Node.js 成为 PID 1，接收 K8s SIGTERM
#
# 注意: 不依赖 apt 包，用 node 替代 envsubst
# =============================================================================

OPENCLAW_DIR="/root/.openclaw"
CONFIG_FILE="${OPENCLAW_DIR}/openclaw.json"
TEMPLATE_FILE="${OPENCLAW_DIR}/openclaw.json.template"
CREDENTIALS_DIR="${OPENCLAW_DIR}/credentials"

# ---- 1. 配置初始化 ----

# 用 node 实现 envsubst（替换模板中的 ${VAR} 占位符）
envsubst_node() {
  node -e "
    const fs = require('fs');
    let t = fs.readFileSync('$1', 'utf8');
    t = t.replace(/\\\$\{([^}]+)\}/g, (_, k) => process.env[k] ?? '');
    fs.writeFileSync('$2', t);
  "
}

# 设置默认值
export OPENCLAW_GATEWAY_PORT="${OPENCLAW_GATEWAY_PORT:-18789}"
export OPENCLAW_GATEWAY_BIND="${OPENCLAW_GATEWAY_BIND:-lan}"
export OPENCLAW_LOG_LEVEL="${OPENCLAW_LOG_LEVEL:-info}"

# 未指定 Token 时自动生成一个随机 Token
if [ -z "${OPENCLAW_GATEWAY_TOKEN:-}" ]; then
  OPENCLAW_GATEWAY_TOKEN=$(node -e "console.log(require('crypto').randomBytes(24).toString('hex'))")
  export OPENCLAW_GATEWAY_TOKEN
  echo "[entrypoint] =================================================="
  echo "[entrypoint] 未指定 OPENCLAW_GATEWAY_TOKEN，已自动生成"
  echo "[entrypoint] Token: ${OPENCLAW_GATEWAY_TOKEN}"
  echo "[entrypoint]"
  echo "[entrypoint] 打开控制台: http://localhost:${OPENCLAW_GATEWAY_PORT}/?token=${OPENCLAW_GATEWAY_TOKEN}"
  echo "[entrypoint]"
  echo "[entrypoint] 如需固定 Token，启动时加 -e OPENCLAW_GATEWAY_TOKEN=<你的Token>"
  echo "[entrypoint] =================================================="
fi

if [ "${OPENCLAW_FORCE_RECONFIG:-false}" = "true" ]; then
  echo "[entrypoint] OPENCLAW_FORCE_RECONFIG=true，从模板重新生成配置..."
  if [ -f "${TEMPLATE_FILE}" ]; then
    envsubst_node "${TEMPLATE_FILE}" "${CONFIG_FILE}"
    echo "[entrypoint] 配置已重新生成: ${CONFIG_FILE}"
  else
    echo "[entrypoint] 警告: 模板文件不存在 ${TEMPLATE_FILE}，跳过配置生成"
  fi
elif [ ! -f "${CONFIG_FILE}" ]; then
  echo "[entrypoint] 首次启动，从模板生成配置..."
  if [ -f "${TEMPLATE_FILE}" ]; then
    envsubst_node "${TEMPLATE_FILE}" "${CONFIG_FILE}"
    echo "[entrypoint] 配置已生成: ${CONFIG_FILE}"
  else
    echo "[entrypoint] 警告: 模板文件不存在 ${TEMPLATE_FILE}，将以无配置模式启动"
  fi
else
  echo "[entrypoint] 配置文件已存在，跳过生成"
fi

# ---- 1.1. 配置补全（兼容旧版 PVC 上的配置） ----

if [ -f "${CONFIG_FILE}" ]; then
  node -e "
    const fs = require('fs');
    const f = '${CONFIG_FILE}';
    let text = fs.readFileSync(f, 'utf8');
    text = text.replace(/^\s*\/\/.*$/gm, '');
    const c = JSON.parse(text);
    let changed = false;
    if (c.gateway?.controlUi && !c.gateway.controlUi.dangerouslyAllowHostHeaderOriginFallback) {
      c.gateway.controlUi.dangerouslyAllowHostHeaderOriginFallback = true;
      changed = true;
    }
    if (c.gateway?.controlUi && !c.gateway.controlUi.dangerouslyDisableDeviceAuth) {
      c.gateway.controlUi.dangerouslyDisableDeviceAuth = true;
      changed = true;
    }
    const skills = c.skills ?? (c.skills = {});
    const load = skills.load ?? (skills.load = {});
    const extraDirs = Array.isArray(load.extraDirs) ? load.extraDirs : [];
    if (!extraDirs.includes('/root/.openclaw/skills')) {
      extraDirs.push('/root/.openclaw/skills');
      load.extraDirs = extraDirs;
      changed = true;
    }
    const tools = c.tools ?? (c.tools = {});
    const exec = tools.exec ?? (tools.exec = {});
    if (!exec.security) { exec.security = 'full'; changed = true; }
    if (!exec.ask) { exec.ask = 'off'; changed = true; }
    // 补全 nodeskclaw channel 配置（旧版 PVC 上的 openclaw.json 缺少此节）
    // 三个环境变量由 deploy_service 在容器启动时注入
    const ndApiUrl = process.env.NODESKCLAW_API_URL || '';
    const ndInstanceId = process.env.NODESKCLAW_INSTANCE_ID || '';
    const ndToken = process.env.OPENCLAW_GATEWAY_TOKEN || '';
    if (ndApiUrl || ndInstanceId || ndToken) {
      const channels = c.channels ?? (c.channels = {});
      const ndChannel = channels.nodeskclaw ?? (channels.nodeskclaw = {});
      const accounts = ndChannel.accounts ?? (ndChannel.accounts = {});
      const defAcc = accounts.default ?? (accounts.default = {});
      if (ndApiUrl && defAcc.apiUrl !== ndApiUrl) { defAcc.apiUrl = ndApiUrl; changed = true; }
      if (ndInstanceId && defAcc.instanceId !== ndInstanceId) { defAcc.instanceId = ndInstanceId; changed = true; }
      if (ndToken && defAcc.apiToken !== ndToken) { defAcc.apiToken = ndToken; changed = true; }
    }
    if (changed) {
      fs.writeFileSync(f, JSON.stringify(c, null, 2));
      console.log('[entrypoint] 已补全 controlUi / skills / exec / nodeskclaw channel 配置');
    }
  "
fi

# ---- 1.2. 升级数据修复（兼容旧版目录/文件命名） ----

node /repair-user-data.js

# ---- 1.3. 会话索引修复（兼容旧版会话文件命名） ----

if [ -d "${OPENCLAW_DIR}/agents/main/sessions" ]; then
  node /repair-sessions-index.js
fi

# ---- 2. 凭证注入 ----

if [ -n "${OPENCLAW_CREDENTIALS_JSON:-}" ]; then
  mkdir -p -m 700 "${CREDENTIALS_DIR}"
  echo "${OPENCLAW_CREDENTIALS_JSON}" > "${CREDENTIALS_DIR}/default.json"
  echo "[entrypoint] 凭证已写入: ${CREDENTIALS_DIR}/default.json"
fi

# ---- 3. 清理编译缓存 ----

rm -rf /tmp/jiti/* 2>/dev/null || true

# ---- 3.5 文件权限收紧 ----

chmod 700 "${OPENCLAW_DIR}" 2>/dev/null || true
[ -d "${CREDENTIALS_DIR}" ] && chmod 700 "${CREDENTIALS_DIR}"

# ---- 4. 前台启动 ----

echo "[entrypoint] 启动 OpenClaw Gateway..."
echo "[entrypoint]   端口: ${OPENCLAW_GATEWAY_PORT}"
echo "[entrypoint]   绑定: ${OPENCLAW_GATEWAY_BIND}"
echo "[entrypoint]   日志级别: ${OPENCLAW_LOG_LEVEL}"

# exec 替换当前 shell 进程，让 Node.js 成为 PID 1
exec openclaw gateway --allow-unconfigured --bind lan
