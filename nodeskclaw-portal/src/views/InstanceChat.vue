<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ArrowLeft, Bot, Send, Loader2, AlertCircle, Plus, MessageSquare } from 'lucide-vue-next'
import api from '@/services/api'
import { useWorkspaceStore } from '@/stores/workspace'
import { useAuthStore } from '@/stores/auth'
import { getStatusDisplay } from '@/utils/instanceStatus'
import type { WorkspaceListItem, Conversation } from '@/stores/workspace'

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
const workspace = ref<WorkspaceListItem | null>(null)
const workspaceLoading = ref(false)

// ── 会话列表 ─────────────────────────────────
const sessions = ref<Conversation[]>([])
const activeSessionId = ref<string | null>(null)
const sessionsLoading = ref(false)
const creatingSession = ref(false)

// ── 消息列表 ─────────────────────────────────
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

// ── 思考指示器 ───────────────────────────────
// 当 agent:typing 到达但尚未收到第一个 chunk 时显示
const isTyping = ref(false)

// ── 技能列表 ─────────────────────────────────
interface SkillItem {
  skill_name: string
  name: string
  description?: string
  type: string
}

const skills = ref<SkillItem[]>([])
const selectedSkill = ref<string | null>(null)

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

// 加载该 AI 员工的历史会话列表
async function loadSessions() {
  if (!workspace.value) return
  sessionsLoading.value = true
  try {
    const list = await store.fetchInstanceConversations(workspace.value.id, instanceId.value)
    // 按最近消息时间降序，置顶有消息的会话
    sessions.value = list.sort((a, b) => {
      if (!a.last_message_at && !b.last_message_at) return 0
      if (!a.last_message_at) return 1
      if (!b.last_message_at) return -1
      return new Date(b.last_message_at).getTime() - new Date(a.last_message_at).getTime()
    })
  } finally {
    sessionsLoading.value = false
  }
}

// 创建新会话
async function createNewSession() {
  if (!workspace.value || creatingSession.value) return
  creatingSession.value = true
  try {
    const userId = authStore.user?.id || ''
    const index = sessions.value.length + 1
    const name = t('instanceChat.sessionTitle', { index })
    const conv = await store.createConversation(workspace.value.id, name, [
      instanceId.value,
      userId,
    ])
    sessions.value.unshift(conv)
    await switchSession(conv.id)
  } finally {
    creatingSession.value = false
  }
}

// 切换会话
async function switchSession(sessionId: string) {
  if (activeSessionId.value === sessionId) return
  activeSessionId.value = sessionId
  messages.value = []
  isTyping.value = false
  await loadSessionMessages()
}

// 加载当前会话的消息
async function loadSessionMessages() {
  if (!workspace.value || !activeSessionId.value) return
  messagesLoading.value = true
  try {
    const msgs = await store.fetchConversationMessages(workspace.value.id, activeSessionId.value)
    messages.value = msgs as ChatMsg[]
    await scrollToBottom()
  } finally {
    messagesLoading.value = false
  }
}

// 加载已安装的技能列表
async function loadSkills() {
  try {
    const res = await api.get(`/instances/${instanceId.value}/skills`)
    skills.value = (res.data.data || []) as SkillItem[]
  } catch {
    // 技能加载失败不影响主流程
  }
}

// 相对时间格式化
function relativeTime(iso: string | null): string {
  if (!iso) return ''
  const diff = Date.now() - new Date(iso).getTime()
  const min = Math.floor(diff / 60000)
  if (min < 1) return '刚刚'
  if (min < 60) return `${min} 分钟前`
  const h = Math.floor(min / 60)
  if (h < 24) return `${h} 小时前`
  const d = Math.floor(h / 24)
  if (d < 30) return `${d} 天前`
  return new Date(iso).toLocaleDateString()
}

// SSE 实时消息回调
function onSSEEvent(event: string, data: Record<string, unknown>) {
  const senderId = data.instance_id as string

  if (event === 'agent:typing') {
    // 当前 AI 员工开始处理，尚未输出时显示思考指示器
    if (senderId === instanceId.value) {
      isTyping.value = true
    }
    return
  }

  if (event === 'agent:chunk') {
    // 收到第一个 chunk，隐藏思考指示器
    if (senderId === instanceId.value) isTyping.value = false

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
    return
  }

  if (event === 'agent:done') {
    if (senderId === instanceId.value) isTyping.value = false
    const target = messages.value.find(
      (m) => m.streaming && m.sender_id === senderId,
    )
    if (target) {
      target.streaming = false
      // 更新当前会话的最后消息预览
      const session = sessions.value.find((s) => s.id === activeSessionId.value)
      if (session) {
        session.last_message_at = new Date().toISOString()
        session.last_message_preview = target.content.slice(0, 60)
      }
    }
  }
}

// 发送消息
async function sendMessage() {
  if (!inputText.value.trim() || sending.value || !workspace.value || !activeSessionId.value) return

  const rawText = inputText.value.trim()
  // 若选择了技能，在消息前追加 slash command 前缀
  const text = selectedSkill.value ? `/${selectedSkill.value}\n${rawText}` : rawText
  inputText.value = ''
  sending.value = true

  // 乐观更新：立即将用户消息加入列表
  messages.value.push({
    id: `local-${Date.now()}`,
    sender_type: 'user',
    sender_id: authStore.user?.id || 'me',
    sender_name: authStore.user?.name || t('instanceChat.you'),
    content: rawText, // 展示原始文本，不含前缀
    created_at: new Date().toISOString(),
  })
  await scrollToBottom()

  // 更新会话列表预览
  const session = sessions.value.find((s) => s.id === activeSessionId.value)
  if (session) {
    session.last_message_at = new Date().toISOString()
    session.last_message_preview = rawText.slice(0, 60)
  }

  try {
    await store.sendWorkspaceMessage(
      workspace.value.id,
      text,
      [instanceId.value],
      undefined,
      undefined,
      activeSessionId.value,
    )
  } catch {
    // 发送失败保持乐观更新显示
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
    // 并行加载会话列表和技能列表
    await Promise.all([loadSessions(), loadSkills()])

    // 若有历史会话选中最新的，否则自动创建第一个
    if (sessions.value.length > 0) {
      activeSessionId.value = sessions.value[0].id
      await loadSessionMessages()
    } else {
      await createNewSession()
    }

    store.connectSSE(workspace.value.id, onSSEEvent)
  }
})

onUnmounted(() => {
  store.disconnectSSE()
})
</script>

<template>
  <div class="h-screen flex flex-col bg-background">
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

    <!-- 主对话区域：左侧会话面板 + 右侧消息区 -->
    <template v-else>
      <div class="flex-1 flex overflow-hidden">

        <!-- ── 左侧会话侧边栏 200px ── -->
        <aside class="w-[200px] shrink-0 border-r border-border flex flex-col bg-card">
          <!-- 新建对话按钮 -->
          <div class="p-3 border-b border-border">
            <button
              class="w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg bg-primary/10 text-primary text-xs font-medium hover:bg-primary/20 transition-colors disabled:opacity-50"
              :disabled="creatingSession"
              @click="createNewSession"
            >
              <Loader2 v-if="creatingSession" class="w-3.5 h-3.5 animate-spin" />
              <Plus v-else class="w-3.5 h-3.5" />
              {{ t('instanceChat.newSession') }}
            </button>
          </div>

          <!-- 会话列表 -->
          <div class="flex-1 overflow-y-auto py-1">
            <div v-if="sessionsLoading" class="flex justify-center py-4">
              <Loader2 class="w-4 h-4 animate-spin text-muted-foreground" />
            </div>
            <template v-else>
              <button
                v-for="session in sessions"
                :key="session.id"
                class="w-full text-left px-3 py-2.5 flex flex-col gap-0.5 hover:bg-accent transition-colors relative"
                :class="session.id === activeSessionId ? 'bg-accent/60' : ''"
                @click="switchSession(session.id)"
              >
                <!-- 激活指示条 -->
                <span
                  v-if="session.id === activeSessionId"
                  class="absolute left-0 top-2 bottom-2 w-0.5 rounded-full bg-primary"
                />
                <div class="flex items-center justify-between gap-1 pl-1">
                  <span class="text-xs font-medium truncate flex-1">{{ session.name }}</span>
                  <span class="text-[10px] text-muted-foreground shrink-0">
                    {{ relativeTime(session.last_message_at) }}
                  </span>
                </div>
                <p v-if="session.last_message_preview" class="text-[11px] text-muted-foreground truncate pl-1">
                  {{ session.last_message_preview }}
                </p>
                <div v-else class="flex items-center gap-1 pl-1">
                  <MessageSquare class="w-2.5 h-2.5 text-muted-foreground/50" />
                  <span class="text-[11px] text-muted-foreground/50">{{ t('instanceChat.startHint', { name: '' }).trim().replace('和', '').replace('打个招呼吧', '') }}</span>
                </div>
              </button>
            </template>
          </div>
        </aside>

        <!-- ── 右侧：顶部栏 + 消息区 + 输入区 ── -->
        <div class="flex-1 flex flex-col min-w-0">

          <!-- 顶部导航栏 -->
          <header class="flex items-center gap-3 px-4 py-3 border-b border-border bg-card shrink-0">
            <button
              class="p-1.5 rounded-lg hover:bg-accent transition-colors"
              @click="router.back()"
            >
              <ArrowLeft class="w-4 h-4" />
            </button>

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
          </header>

          <!-- 消息列表 -->
          <div class="flex-1 overflow-y-auto px-4 py-4 space-y-4">
            <div v-if="messagesLoading" class="flex justify-center py-4">
              <Loader2 class="w-5 h-5 animate-spin text-muted-foreground" />
            </div>

            <div
              v-else-if="messages.length === 0 && !isTyping"
              class="flex flex-col items-center justify-center py-16 gap-3 text-center"
            >
              <div class="w-12 h-12 rounded-2xl bg-primary/10 flex items-center justify-center">
                <Bot class="w-6 h-6 text-primary" />
              </div>
              <p class="text-sm text-muted-foreground">
                {{ t('instanceChat.startHint', { name: instance?.name }) }}
              </p>
            </div>

            <template v-else>
              <!-- 消息气泡 -->
              <div
                v-for="msg in messages"
                :key="msg.id"
                class="flex gap-3"
                :class="msg.sender_type === 'user' ? 'flex-row-reverse' : 'flex-row'"
              >
                <div
                  class="w-7 h-7 rounded-full flex items-center justify-center shrink-0 text-xs font-semibold mt-0.5"
                  :class="msg.sender_type === 'user' ? 'bg-primary text-primary-foreground' : 'bg-primary/15 text-primary'"
                >
                  <template v-if="msg.sender_type === 'user'">
                    {{ (msg.sender_name || '?').charAt(0).toUpperCase() }}
                  </template>
                  <Bot v-else class="w-3.5 h-3.5" />
                </div>

                <div
                  class="max-w-[72%] rounded-2xl px-3.5 py-2.5 text-sm whitespace-pre-wrap break-words leading-relaxed"
                  :class="
                    msg.sender_type === 'user'
                      ? 'bg-primary text-primary-foreground rounded-tr-sm'
                      : 'bg-card border border-border rounded-tl-sm'
                  "
                >
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

              <!-- 思考指示器：等待第一个 chunk 时显示 -->
              <div v-if="isTyping" class="flex gap-3 flex-row">
                <div class="w-7 h-7 rounded-full bg-primary/15 text-primary flex items-center justify-center shrink-0 mt-0.5">
                  <Bot class="w-3.5 h-3.5" />
                </div>
                <div class="bg-card border border-border rounded-2xl rounded-tl-sm px-3.5 py-2.5 text-sm text-muted-foreground">
                  <span class="flex items-center gap-1">
                    <span class="w-1.5 h-1.5 rounded-full bg-muted-foreground/60 animate-bounce" style="animation-delay: 0ms" />
                    <span class="w-1.5 h-1.5 rounded-full bg-muted-foreground/60 animate-bounce" style="animation-delay: 150ms" />
                    <span class="w-1.5 h-1.5 rounded-full bg-muted-foreground/60 animate-bounce" style="animation-delay: 300ms" />
                  </span>
                </div>
              </div>
            </template>

            <!-- 滚动锚点 -->
            <div ref="chatEndRef" />
          </div>

          <!-- 输入区域 -->
          <div class="shrink-0 border-t border-border bg-card px-4 pt-2 pb-3">
            <!-- 技能选择条（有技能时才显示） -->
            <div v-if="skills.length > 0" class="flex items-center gap-1.5 mb-2 flex-wrap">
              <span class="text-[11px] text-muted-foreground shrink-0">{{ t('instanceChat.skillSelect') }}:</span>
              <!-- 无技能选项 -->
              <button
                class="px-2 py-0.5 rounded-full text-[11px] border transition-colors"
                :class="selectedSkill === null
                  ? 'bg-primary text-primary-foreground border-primary'
                  : 'border-border text-muted-foreground hover:bg-accent'"
                @click="selectedSkill = null"
              >
                {{ t('instanceChat.noSkill') }}
              </button>
              <!-- 技能 chip -->
              <button
                v-for="skill in skills"
                :key="skill.skill_name"
                class="px-2 py-0.5 rounded-full text-[11px] border transition-colors"
                :class="selectedSkill === skill.skill_name
                  ? 'bg-primary text-primary-foreground border-primary'
                  : 'border-border text-muted-foreground hover:bg-accent'"
                :title="skill.description || skill.name"
                @click="selectedSkill = skill.skill_name"
              >
                {{ skill.name || skill.skill_name }}
              </button>
            </div>

            <!-- 文本输入和发送按钮 -->
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
                :disabled="!inputText.trim() || sending || !activeSessionId"
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
        </div>
      </div>
    </template>
  </div>
</template>
