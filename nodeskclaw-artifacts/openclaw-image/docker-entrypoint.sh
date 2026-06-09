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

# ---- 3.6 Windows bind-mount 插件权限修复 ----
#
# Windows NTFS bind-mount 进容器后所有目录均显示为 world-writable，
# OpenClaw 的安全检查会拒绝加载这类插件候选目录。
# 旧方案依赖 stat -c '%a' == "777" 的字符串比较，
# 但实际返回值可能是 "0777" / "1777" / "777" 等多种格式，导致漏检。
# 新方案：先尝试 chmod，若 chmod 无效（NTFS bind-mount 会静默忽略），
# 用 find -perm /o+w 检测 other-write bit，确认仍为 world-writable 后
# 复制到 npm global extensions 路径（overlayfs，权限可控）。
if [ -d "${OPENCLAW_DIR}/extensions" ]; then
  GLOBAL_EXT="$(npm root -g 2>/dev/null)/openclaw/extensions"
  mkdir -p "${GLOBAL_EXT}"
  copied=0
  for ext_dir in "${OPENCLAW_DIR}/extensions"/*/; do
    [ -d "${ext_dir}" ] || continue
    dir_name=$(basename "${ext_dir}")
    dest="${GLOBAL_EXT}/${dir_name}"
    # 先尝试直接收紧权限（对 Linux 原生挂载有效）
    find "${ext_dir}" -type d -exec chmod go-w {} \; 2>/dev/null || true
    # 若 other-write bit 仍然存在（Windows bind-mount chmod 无效）→ 复制到 bundled 路径
    if find "${ext_dir}" -maxdepth 0 -perm /o+w 2>/dev/null | grep -q .; then
      rm -rf "${dest}"
      cp -r "${ext_dir}" "${dest}"
      chmod -R 755 "${dest}"
      echo "[entrypoint] 插件 ${dir_name} 已复制到 bundled 路径（Windows bind-mount 权限修复）"
      copied=$((copied + 1))
    fi
  done
  [ "${copied}" -gt 0 ] && echo "[entrypoint] 共修复 ${copied} 个 world-writable 插件"
fi

# ---- 4. 前台启动 ----

echo "[entrypoint] 启动 OpenClaw Gateway..."
echo "[entrypoint]   端口: ${OPENCLAW_GATEWAY_PORT}"
echo "[entrypoint]   绑定: ${OPENCLAW_GATEWAY_BIND}"
echo "[entrypoint]   日志级别: ${OPENCLAW_LOG_LEVEL}"

# exec 替换当前 shell 进程，让 Node.js 成为 PID 1
exec openclaw gateway --allow-unconfigured --bind lan
