<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ArrowLeft, Bot, Send, Loader2, AlertCircle, Plus, MessageSquare, Trash2 } from 'lucide-vue-next'
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

// ── 斜杠命令下拉框 ────────────────────────────
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const showSkillDropdown = ref(false)
const skillFilter = ref('')
const slashPosition = ref(-1)
const dropdownIndex = ref(0)

const filteredSkills = computed(() => {
  const q = skillFilter.value.toLowerCase()
  if (!q) return skills.value
  return skills.value.filter(
    (s) =>
      s.skill_name.toLowerCase().startsWith(q) ||
      s.name.toLowerCase().startsWith(q),
  )
})

// ── 输入框 ───────────────────────────────────
const inputText = ref('')
const sending = ref(false)

// ── 状态展示 ─────────────────────────────────
const statusDisplay = computed(() =>
  getStatusDisplay(instance.value?.display_status ?? ''),
)

// 剥离 LLM 内部格式标签（如 <final>…</final>），只展示正文
function cleanContent(text: string): string {
  return text
    .replace(/<final[^>]*>/gi, '')
    .replace(/<\/final[^>]*>/gi, '')
    .trim()
}

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

// 删除会话
async function deleteSession(sessionId: string) {
  if (!workspace.value) return
  try {
    await api.delete(`/workspaces/${workspace.value.id}/conversations/${sessionId}`)
  } catch {
    // 删除失败也从本地列表移除，保持 UI 一致
  }
  const idx = sessions.value.findIndex((s) => s.id === sessionId)
  if (idx !== -1) sessions.value.splice(idx, 1)

  // 若删除的是当前激活会话，切换到最新的或新建一个
  if (activeSessionId.value === sessionId) {
    activeSessionId.value = null
    messages.value = []
    if (sessions.value.length > 0) {
      await switchSession(sessions.value[0].id)
    } else {
      await createNewSession()
    }
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

// SSE 事件回调（仅保留系统事件，消息流已改用直连）
function onSSEEvent(_event: string, _data: Record<string, unknown>) {}

// 发送消息：调用私人对话直连端点，流式读取响应
async function sendMessage() {
  if (!inputText.value.trim() || sending.value || !workspace.value || !activeSessionId.value) return

  const text = inputText.value.trim()
  inputText.value = ''
  sending.value = true
  isTyping.value = true

  // 乐观更新：立即显示用户消息
  messages.value.push({
    id: `local-${Date.now()}`,
    sender_type: 'user',
    sender_id: authStore.user?.id || 'me',
    sender_name: authStore.user?.name || t('instanceChat.you'),
    content: text,
    created_at: new Date().toISOString(),
  })
  await scrollToBottom()

  // 更新会话预览
  const session = sessions.value.find((s) => s.id === activeSessionId.value)
  if (session) {
    session.last_message_at = new Date().toISOString()
    session.last_message_preview = text.slice(0, 60)
  }

  // 创建占位流式消息气泡
  const streamMsg: ChatMsg = {
    id: `stream-${Date.now()}`,
    sender_type: 'agent',
    sender_id: instanceId.value,
    sender_name: instance.value?.name || '',
    content: '',
    created_at: new Date().toISOString(),
    streaming: true,
  }

  try {
    const token = localStorage.getItem('portal_token') || ''
    const response = await fetch(
      `/api/v1/workspaces/${workspace.value.id}/agents/${instanceId.value}/chat`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({
          message: text,
          conversation_id: activeSessionId.value,
        }),
      },
    )

    if (!response.ok || !response.body) {
      throw new Error(`HTTP ${response.status}`)
    }

    // 第一个字节到达时结束思考指示器，推入流式消息气泡
    isTyping.value = false
    messages.value.push(streamMsg)
    await scrollToBottom()

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        const payload = line.slice(6)
        if (payload === '[DONE]') {
          streamMsg.streaming = false
          // 更新会话预览为最终回复内容
          if (session) session.last_message_preview = streamMsg.content.slice(0, 60)
          break
        }
        try {
          const parsed = JSON.parse(payload) as { content?: string; error?: string }
          if (parsed.error) {
            streamMsg.content = `[${parsed.error}]`
            streamMsg.streaming = false
          } else if (parsed.content) {
            streamMsg.content += parsed.content
            scrollToBottom()
          }
        } catch {
          // 忽略非 JSON 行
        }
      }
    }
  } catch {
    isTyping.value = false
    // 若气泡已推入则标记完成，否则移除
    if (messages.value.includes(streamMsg)) {
      streamMsg.streaming = false
    }
  } finally {
    sending.value = false
    streamMsg.streaming = false
  }
}

// 检测 textarea 中的斜杠命令，触发技能下拉框
function handleInput() {
  const ta = textareaRef.value
  if (!ta || skills.value.length === 0) return

  const cursor = ta.selectionStart ?? 0
  const text = ta.value

  // 从光标向前扫描，找到最近的 / 命令起始位置
  let slashIdx = -1
  for (let i = cursor - 1; i >= 0; i--) {
    if (text[i] === '/') {
      // / 需位于行首或空白之后
      if (i === 0 || /[\s\n]/.test(text[i - 1])) {
        slashIdx = i
      }
      break
    } else if (/[\s\n]/.test(text[i])) {
      break
    }
  }

  if (slashIdx >= 0) {
    slashPosition.value = slashIdx
    skillFilter.value = text.slice(slashIdx + 1, cursor)
    dropdownIndex.value = 0
    showSkillDropdown.value = filteredSkills.value.length > 0
  } else {
    showSkillDropdown.value = false
  }
}

// 从下拉框选中一个技能，将 /xxx 替换为 /skill_name 并关闭下拉框
function selectSkillFromDropdown(skill: SkillItem) {
  const ta = textareaRef.value
  if (!ta) return

  const cursor = ta.selectionStart ?? 0
  const text = ta.value
  const before = text.slice(0, slashPosition.value)
  const after = text.slice(cursor)
  const inserted = `/${skill.skill_name} `

  inputText.value = before + inserted + after
  showSkillDropdown.value = false

  nextTick(() => {
    const pos = before.length + inserted.length
    ta.setSelectionRange(pos, pos)
    ta.focus()
  })
}

// 按 Enter 发送（Shift+Enter 换行）；下拉框开启时 Enter/ArrowUp/ArrowDown/Esc 控制下拉框
function onKeydown(e: KeyboardEvent) {
  if (showSkillDropdown.value) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      dropdownIndex.value = Math.min(dropdownIndex.value + 1, filteredSkills.value.length - 1)
      return
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      dropdownIndex.value = Math.max(dropdownIndex.value - 1, 0)
      return
    }
    if (e.key === 'Enter') {
      e.preventDefault()
      const skill = filteredSkills.value[dropdownIndex.value]
      if (skill) selectSkillFromDropdown(skill)
      return
    }
    if (e.key === 'Escape') {
      showSkillDropdown.value = false
      return
    }
  }

  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendMessage()
  }
}

onMounted(async () => {
  await loadInstance()
  await findWorkspace()

  if (workspace.value) {
    await Promise.all([loadSessions(), loadSkills()])

    if (sessions.value.length > 0) {
      activeSessionId.value = sessions.value[0].id
      await loadSessionMessages()
    } else {
      await createNewSession()
    }
  }
})

onUnmounted(() => {})
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
    <div v-else class="flex-1 flex overflow-hidden">

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
                class="group w-full text-left px-3 py-2.5 flex flex-col gap-0.5 hover:bg-accent transition-colors relative"
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
                  <!-- 删除按钮：hover 时显示 -->
                  <button
                    class="shrink-0 opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-destructive/15 hover:text-destructive text-muted-foreground transition-all"
                    @click.stop="deleteSession(session.id)"
                  >
                    <Trash2 class="w-3 h-3" />
                  </button>
                </div>
                <p v-if="session.last_message_preview" class="text-[11px] text-muted-foreground truncate pl-1">
                  {{ session.last_message_preview }}
                  <span class="ml-1 text-muted-foreground/60">· {{ relativeTime(session.last_message_at) }}</span>
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
                  {{ cleanContent(msg.content) }}
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
            <!-- 文本输入和发送按钮（相对定位，用于锚定下拉框） -->
            <div class="relative flex items-end gap-2">
              <!-- 技能斜杠命令下拉框：显示在 textarea 上方 -->
              <div
                v-if="showSkillDropdown && filteredSkills.length > 0"
                class="absolute bottom-full left-0 mb-1 w-64 max-h-52 overflow-y-auto rounded-xl border border-border bg-popover shadow-lg z-50"
              >
                <div class="px-2.5 py-1.5 text-[11px] text-muted-foreground border-b border-border">
                  {{ t('instanceChat.skillSelect') }}
                </div>
                <button
                  v-for="(skill, idx) in filteredSkills"
                  :key="skill.skill_name"
                  class="w-full text-left px-3 py-2 flex flex-col gap-0.5 hover:bg-accent transition-colors"
                  :class="idx === dropdownIndex ? 'bg-accent' : ''"
                  @mousedown.prevent="selectSkillFromDropdown(skill)"
                >
                  <span class="text-sm font-medium">/{{ skill.skill_name }}</span>
                  <span v-if="skill.description" class="text-[11px] text-muted-foreground truncate">
                    {{ skill.description }}
                  </span>
                </button>
              </div>

              <textarea
                ref="textareaRef"
                v-model="inputText"
                rows="2"
                class="flex-1 resize-none rounded-xl border border-border bg-background px-3.5 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40 transition-colors placeholder:text-muted-foreground"
                :placeholder="t('instanceChat.placeholder', { name: instance?.name || 'AI 员工' })"
                @input="handleInput"
                @keydown="onKeydown"
                @blur="showSkillDropdown = false"
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
  </div>
</template>
