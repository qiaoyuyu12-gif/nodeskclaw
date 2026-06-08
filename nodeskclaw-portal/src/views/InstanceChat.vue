<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ArrowLeft, Bot, Send, Loader2, AlertCircle } from 'lucide-vue-next'
import api from '@/services/api'
import { useWorkspaceStore } from '@/stores/workspace'
import { useAuthStore } from '@/stores/auth'
import { getStatusDisplay } from '@/utils/instanceStatus'
import type { WorkspaceListItem } from '@/stores/workspace'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const store = useWorkspaceStore()
const authStore = useAuthStore()

const instanceId = computed(() => route.params.id as string)

// ── 实例信息 ─────────────────────────────────
interface InstanceDetail {
  id: string
  name: string
  display_status?: string
  compute_provider?: string
}

const instance = ref<InstanceDetail | null>(null)
const instanceLoading = ref(true)
const instanceError = ref('')

// ── 工作空间 ─────────────────────────────────
// 找到包含该实例的第一个工作空间
const workspace = ref<WorkspaceListItem | null>(null)
const workspaceLoading = ref(false)

// ── 消息列表（本地管理，不影响全局 store 状态） ──
interface ChatMsg {
  id: string
  sender_type: 'user' | 'agent' | 'system'
  sender_id: string
  sender_name: string
  content: string
  created_at: string
  streaming?: boolean
}

const messages = ref<ChatMsg[]>([])
const messagesLoading = ref(false)
const chatEndRef = ref<HTMLElement | null>(null)

// ── 输入框 ───────────────────────────────────
const inputText = ref('')
const sending = ref(false)

// ── 状态展示 ─────────────────────────────────
const statusDisplay = computed(() =>
  getStatusDisplay(instance.value?.display_status ?? ''),
)

// 滚动到底部
async function scrollToBottom() {
  await nextTick()
  chatEndRef.value?.scrollIntoView({ behavior: 'smooth' })
}

// 加载实例信息
async function loadInstance() {
  instanceLoading.value = true
  instanceError.value = ''
  try {
    const res = await api.get(`/instances/${instanceId.value}`)
    instance.value = res.data.data
  } catch {
    instanceError.value = t('instanceChat.loadFailed')
  } finally {
    instanceLoading.value = false
  }
}

// 查找该实例所属的工作空间
async function findWorkspace() {
  workspaceLoading.value = true
  try {
    await store.fetchWorkspaces()
    const found = store.workspaces.find((ws: WorkspaceListItem) =>
      ws.agents?.some((a) => a.instance_id === instanceId.value),
    )
    workspace.value = found ?? null
  } finally {
    workspaceLoading.value = false
  }
}

// 加载该工作空间的最近消息
async function loadMessages() {
  if (!workspace.value) return
  messagesLoading.value = true
  try {
    const msgs = await store.fetchChatHistory(workspace.value.id, { limit: 50 })
    messages.value = msgs as ChatMsg[]
    await scrollToBottom()
  } finally {
    messagesLoading.value = false
  }
}

// SSE 实时消息回调
function onSSEEvent(event: string, data: Record<string, unknown>) {
  if (event === 'agent:chunk') {
    // AI 员工流式输出：累加到已有 streaming 消息或新建
    const senderId = data.instance_id as string
    const existing = messages.value.find(
      (m) => m.sender_id === senderId && m.streaming,
    )
    if (existing) {
      existing.content += (data.content as string) || ''
    } else {
      messages.value.push({
        id: (data.envelope_id as string) || `stream-${senderId}-${Date.now()}`,
        sender_type: 'agent',
        sender_id: senderId,
        sender_name: (data.agent_name as string) || '',
        content: (data.content as string) || '',
        created_at: new Date().toISOString(),
        streaming: true,
      })
    }
    scrollToBottom()
  } else if (event === 'agent:done') {
    // 流式结束：取消 streaming 标记
    const senderId = data.instance_id as string
    const target = messages.value.find(
      (m) => m.streaming && m.sender_id === senderId,
    )
    if (target) target.streaming = false
  } else if (event === 'agent:typing') {
    // 可选：后续可在此处添加"正在输入"指示
  }
}

// 发送消息
async function sendMessage() {
  if (!inputText.value.trim() || sending.value || !workspace.value) return

  const text = inputText.value.trim()
  inputText.value = ''
  sending.value = true

  // 乐观更新：立即将用户消息加入列表
  messages.value.push({
    id: `local-${Date.now()}`,
    sender_type: 'user',
    sender_id: authStore.user?.id || 'me',
    sender_name: authStore.user?.name || t('instanceChat.you'),
    content: text,
    created_at: new Date().toISOString(),
  })
  await scrollToBottom()

  try {
    // @mention 该 AI 员工，使其优先响应
    await store.sendWorkspaceMessage(
      workspace.value.id,
      text,
      [instanceId.value],
    )
  } catch {
    // 发送失败时给出提示但不回滚（保持乐观更新显示）
  } finally {
    sending.value = false
  }
}

// 按 Enter 发送（Shift+Enter 换行）
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendMessage()
  }
}

onMounted(async () => {
  await loadInstance()
  await findWorkspace()

  if (workspace.value) {
    await loadMessages()
    store.connectSSE(workspace.value.id, onSSEEvent)
  }
})

onUnmounted(() => {
  store.disconnectSSE()
})
</script>

<template>
  <div class="h-screen flex flex-col bg-background">
    <!-- 顶部导航栏 -->
    <header class="flex items-center gap-3 px-4 py-3 border-b border-border bg-card shrink-0">
      <button
        class="p-1.5 rounded-lg hover:bg-accent transition-colors"
        @click="router.back()"
      >
        <ArrowLeft class="w-4 h-4" />
      </button>

      <!-- AI 员工名称 + 状态 -->
      <template v-if="instance">
        <div class="w-8 h-8 rounded-xl bg-primary/10 flex items-center justify-center shrink-0">
          <Bot class="w-4 h-4 text-primary" />
        </div>
        <div class="flex-1 min-w-0">
          <div class="font-semibold text-sm truncate">{{ instance.name }}</div>
          <div class="flex items-center gap-1.5 text-xs">
            <span
              class="w-1.5 h-1.5 rounded-full"
              :class="[statusDisplay.bgColor, statusDisplay.pulse ? 'animate-pulse' : '']"
            />
            <span :class="statusDisplay.color">
              {{ t(`displayStatus.${statusDisplay.key}`) }}
            </span>
          </div>
        </div>
      </template>
      <div v-else-if="instanceLoading" class="flex items-center gap-2">
        <Loader2 class="w-4 h-4 animate-spin text-muted-foreground" />
      </div>
    </header>

    <!-- 加载中 -->
    <div v-if="instanceLoading || workspaceLoading" class="flex-1 flex items-center justify-center">
      <Loader2 class="w-6 h-6 animate-spin text-muted-foreground" />
    </div>

    <!-- 加载失败 -->
    <div v-else-if="instanceError" class="flex-1 flex flex-col items-center justify-center gap-3">
      <AlertCircle class="w-8 h-8 text-red-400" />
      <p class="text-sm text-muted-foreground">{{ instanceError }}</p>
      <button
        class="px-3 py-1.5 rounded-lg border border-border text-sm hover:bg-accent transition-colors"
        @click="loadInstance"
      >
        {{ t('instanceList.retry') }}
      </button>
    </div>

    <!-- 未加入工作空间提示 -->
    <div v-else-if="!workspace" class="flex-1 flex flex-col items-center justify-center gap-3 px-6 text-center">
      <div class="w-14 h-14 rounded-2xl bg-primary/10 flex items-center justify-center">
        <Bot class="w-7 h-7 text-primary" />
      </div>
      <h3 class="font-semibold">{{ t('instanceChat.noWorkspaceTitle') }}</h3>
      <p class="text-sm text-muted-foreground max-w-sm">
        {{ t('instanceChat.noWorkspaceDesc') }}
      </p>
      <button
        class="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors"
        @click="router.push('/')"
      >
        {{ t('instanceChat.goToWorkspaces') }}
      </button>
    </div>

    <!-- 对话区域 -->
    <template v-else>
      <!-- 消息列表 -->
      <div class="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        <!-- 历史加载中 -->
        <div v-if="messagesLoading" class="flex justify-center py-4">
          <Loader2 class="w-5 h-5 animate-spin text-muted-foreground" />
        </div>

        <!-- 无消息 -->
        <div v-else-if="messages.length === 0" class="flex flex-col items-center justify-center py-16 gap-3 text-center">
          <div class="w-12 h-12 rounded-2xl bg-primary/10 flex items-center justify-center">
            <Bot class="w-6 h-6 text-primary" />
          </div>
          <p class="text-sm text-muted-foreground">{{ t('instanceChat.startHint', { name: instance?.name }) }}</p>
        </div>

        <!-- 消息气泡 -->
        <template v-else>
          <div
            v-for="msg in messages"
            :key="msg.id"
            class="flex gap-3"
            :class="msg.sender_type === 'user' ? 'flex-row-reverse' : 'flex-row'"
          >
            <!-- 头像 -->
            <div
              class="w-7 h-7 rounded-full flex items-center justify-center shrink-0 text-xs font-semibold mt-0.5"
              :class="msg.sender_type === 'user' ? 'bg-primary text-primary-foreground' : 'bg-primary/15 text-primary'"
            >
              <template v-if="msg.sender_type === 'user'">
                {{ (msg.sender_name || '?').charAt(0).toUpperCase() }}
              </template>
              <Bot v-else class="w-3.5 h-3.5" />
            </div>

            <!-- 消息内容 -->
            <div
              class="max-w-[72%] rounded-2xl px-3.5 py-2.5 text-sm whitespace-pre-wrap break-words leading-relaxed"
              :class="
                msg.sender_type === 'user'
                  ? 'bg-primary text-primary-foreground rounded-tr-sm'
                  : 'bg-card border border-border rounded-tl-sm'
              "
            >
              <!-- 非目标 agent 的消息加上发送者名字 -->
              <div
                v-if="msg.sender_type === 'agent' && msg.sender_id !== instanceId"
                class="text-xs text-muted-foreground mb-1 font-medium"
              >
                {{ msg.sender_name }}
              </div>
              {{ msg.content }}
              <!-- 流式输出光标 -->
              <span v-if="msg.streaming" class="inline-block w-1 h-3.5 ml-0.5 bg-current animate-pulse align-middle" />
            </div>
          </div>
        </template>

        <!-- 滚动锚点 -->
        <div ref="chatEndRef" />
      </div>

      <!-- 输入区域 -->
      <div class="shrink-0 border-t border-border bg-card px-4 py-3">
        <div class="flex items-end gap-2">
          <textarea
            v-model="inputText"
            rows="2"
            class="flex-1 resize-none rounded-xl border border-border bg-background px-3.5 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40 transition-colors placeholder:text-muted-foreground"
            :placeholder="t('instanceChat.placeholder', { name: instance?.name || 'AI 员工' })"
            @keydown="onKeydown"
          />
          <button
            class="shrink-0 w-9 h-9 rounded-xl bg-primary text-primary-foreground flex items-center justify-center hover:bg-primary/90 transition-colors disabled:opacity-50"
            :disabled="!inputText.trim() || sending"
            @click="sendMessage"
          >
            <Send v-if="!sending" class="w-4 h-4" />
            <Loader2 v-else class="w-4 h-4 animate-spin" />
          </button>
        </div>
        <p class="text-[11px] text-muted-foreground mt-1.5 ml-1">
          {{ t('instanceChat.workspaceHint', { name: workspace?.name }) }}
        </p>
      </div>
    </template>
  </div>
</template>
