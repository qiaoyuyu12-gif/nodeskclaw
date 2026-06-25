<script setup lang="ts">
import { ref, computed, nextTick, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import {
  ChevronLeft,
  Plus,
  Trash2,
  Paperclip,
  X,
  Send,
  FileText,
} from 'lucide-vue-next'
import { externalAgentApi } from '@/services/externalAgents'
import type {
  AttachmentItemWithUrl,
  AttachmentUploadResponse,
  ChatMessage,
  ChatSession,
} from '@/services/externalAgents'
import { useExternalAgentStore } from '@/stores/externalAgents'

// ── 路由 ─────────────────────────────────────────────────────────────────────
const route = useRoute()
const agentId = route.params.id as string

// ── Store ────────────────────────────────────────────────────────────────────
const agentStore = useExternalAgentStore()

const agent = computed(() => agentStore.agents.find((a) => a.id === agentId) ?? null)

// ── 会话状态 ──────────────────────────────────────────────────────────────────
const sessions = ref<ChatSession[]>([])
const currentSessionId = ref<string | null>(null)
const sessionsLoading = ref(false)

// ── 消息状态 ──────────────────────────────────────────────────────────────────
interface LocalMessage {
  id?: string
  role: 'user' | 'assistant'
  content: string
  attachments?: AttachmentItemWithUrl[]
  streaming?: boolean
}

const messages = ref<LocalMessage[]>([])
const messagesLoading = ref(false)
const isStreaming = ref(false)
const inputText = ref('')
const messagesEndRef = ref<HTMLElement | null>(null)

// ── 附件状态 ──────────────────────────────────────────────────────────────────
interface PendingAttachment extends AttachmentUploadResponse {
  previewUrl?: string
}

const pendingAttachments = ref<PendingAttachment[]>([])
const isUploading = ref(false)
const fileInputRef = ref<HTMLInputElement | null>(null)

// ── 初始化 ────────────────────────────────────────────────────────────────────
onMounted(async () => {
  if (!agentStore.agents.length) {
    await agentStore.fetchAgents()
  }
  await loadSessions()
})

// ── 会话操作 ──────────────────────────────────────────────────────────────────
async function loadSessions() {
  sessionsLoading.value = true
  try {
    sessions.value = await externalAgentApi.listSessions(agentId)
    if (sessions.value.length > 0) {
      await switchSession(sessions.value[0].id)
    }
  } catch (e) {
    console.error('加载会话列表失败', e)
  } finally {
    sessionsLoading.value = false
  }
}

async function newSession() {
  const session = await externalAgentApi.createSession(agentId)
  sessions.value.unshift(session)
  await switchSession(session.id)
}

async function switchSession(sessionId: string) {
  if (currentSessionId.value === sessionId) return
  currentSessionId.value = sessionId
  messages.value = []
  messagesLoading.value = true
  try {
    const history = await externalAgentApi.getMessages(agentId, sessionId)
    messages.value = history.map((m: ChatMessage) => ({
      id: m.id,
      role: m.role,
      content: m.content,
      attachments: m.attachments ?? undefined,
    }))
    await scrollToBottom()
  } catch (e) {
    console.error('加载消息历史失败', e)
  } finally {
    messagesLoading.value = false
  }
}

async function deleteSession(sessionId: string, e: Event) {
  e.stopPropagation()
  await externalAgentApi.deleteSession(agentId, sessionId)
  sessions.value = sessions.value.filter((s) => s.id !== sessionId)
  if (currentSessionId.value === sessionId) {
    messages.value = []
    currentSessionId.value = null
    if (sessions.value.length > 0) {
      await switchSession(sessions.value[0].id)
    }
  }
}

// ── 附件操作 ──────────────────────────────────────────────────────────────────
function openFilePicker() {
  fileInputRef.value?.click()
}

async function handleFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = ''
  if (!files.length || !currentSessionId.value) return

  isUploading.value = true
  for (const file of files) {
    try {
      const result = await externalAgentApi.uploadAttachment(agentId, file)
      const pending: PendingAttachment = { ...result }
      if (file.type.startsWith('image/')) {
        pending.previewUrl = URL.createObjectURL(file)
      }
      pendingAttachments.value.push(pending)
    } catch (err) {
      console.error('附件上传失败', err)
    }
  }
  isUploading.value = false
}

function removePendingAttachment(index: number) {
  const att = pendingAttachments.value[index]
  if (att.previewUrl) URL.revokeObjectURL(att.previewUrl)
  pendingAttachments.value.splice(index, 1)
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)}KB`
  return `${(bytes / 1024 / 1024).toFixed(1)}MB`
}

// ── 发送消息 ──────────────────────────────────────────────────────────────────
async function send() {
  const text = inputText.value.trim()
  if ((!text && !pendingAttachments.value.length) || isStreaming.value) return
  if (!currentSessionId.value) {
    await newSession()
    if (!currentSessionId.value) return
  }

  const attachmentsToSend: AttachmentItemWithUrl[] = pendingAttachments.value.map((a) => ({
    name: a.name,
    size: a.size,
    content_type: a.content_type,
    storage_key: a.storage_key,
    url: a.url,
  }))

  messages.value.push({
    role: 'user',
    content: text,
    attachments: attachmentsToSend.length ? attachmentsToSend : undefined,
  })

  inputText.value = ''
  pendingAttachments.value = []
  isStreaming.value = true

  const assistantIndex = messages.value.length
  messages.value.push({ role: 'assistant', content: '', streaming: true })
  await scrollToBottom()

  try {
    const res = await externalAgentApi.chatStream(
      agentId,
      text,
      currentSessionId.value,
      attachmentsToSend.length ? attachmentsToSend : undefined,
    )

    if (!res.body) throw new Error('响应无 body')
    const reader = res.body.getReader()
    const decoder = new TextDecoder()

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      const raw = decoder.decode(value, { stream: true })
      for (const line of raw.split('\n')) {
        if (!line.startsWith('data: ')) continue
        try {
          const payload = JSON.parse(line.slice(6))
          if (payload.chunk) {
            messages.value[assistantIndex].content += payload.chunk
            await scrollToBottom()
          } else if (payload.error) {
            messages.value[assistantIndex].content += `[错误: ${payload.error}]`
          }
        } catch {
          // 忽略非 JSON 行
        }
      }
    }
  } catch (e) {
    messages.value[assistantIndex].content += '[连接失败]'
  } finally {
    messages.value[assistantIndex].streaming = false
    isStreaming.value = false

    const session = sessions.value.find((s) => s.id === currentSessionId.value)
    if (session && !session.title && text) {
      session.title = text.slice(0, 50)
    }
    if (session) {
      sessions.value = [session, ...sessions.value.filter((s) => s.id !== session.id)]
    }
  }
}

async function scrollToBottom() {
  await nextTick()
  messagesEndRef.value?.scrollIntoView({ behavior: 'smooth' })
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}

// ── 内容渲染（linkify）────────────────────────────────────────────────────────
function renderContent(text: string): string {
  const escaped = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/\n/g, '<br>')
  return escaped.replace(
    /(https?:\/\/[^\s&<>"]+)/g,
    '<a href="$1" target="_blank" rel="noopener noreferrer" class="text-blue-600 underline break-all">$1</a>',
  )
}

function formatRelativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes}分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}小时前`
  return `${Math.floor(hours / 24)}天前`
}
</script>

<template>
  <div class="flex h-screen ea-chat-root">
    <!-- 左侧会话列表 -->
    <aside class="w-60 flex-shrink-0 border-r border-border flex flex-col">
      <div class="flex items-center justify-between px-3 py-3 border-b border-border">
        <button
          class="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
          @click="$router.back()"
        >
          <ChevronLeft :size="16" />
          返回
        </button>
        <button
          class="flex items-center gap-1 text-sm text-primary hover:text-primary/80"
          @click="newSession"
        >
          <Plus :size="16" />
          新建
        </button>
      </div>

      <div class="px-3 py-2 border-b border-border">
        <div class="flex items-center gap-2">
          <span v-if="agent?.icon_emoji" class="text-lg">{{ agent.icon_emoji }}</span>
          <span class="text-sm font-medium text-foreground truncate">{{ agent?.name }}</span>
        </div>
        <div class="flex items-center gap-1 mt-0.5">
          <span
            class="w-1.5 h-1.5 rounded-full"
            :class="agent?.is_reachable ? 'bg-green-500' : 'bg-muted-foreground'"
          />
          <span class="text-xs text-muted-foreground">
            {{ agent?.is_reachable ? '已连接' : '未连接' }}
          </span>
        </div>
      </div>

      <div class="flex-1 overflow-y-auto py-1">
        <div v-if="sessionsLoading" class="px-3 py-4 text-xs text-muted-foreground text-center">
          加载中...
        </div>
        <div v-else-if="!sessions.length" class="px-3 py-4 text-xs text-muted-foreground text-center">
          暂无对话，点击「新建」开始
        </div>
        <button
          v-for="s in sessions"
          :key="s.id"
          class="w-full text-left px-3 py-2 group flex items-start justify-between gap-1 hover:bg-muted/50 transition-colors"
          :class="s.id === currentSessionId ? 'bg-primary/10' : ''"
          @click="switchSession(s.id)"
        >
          <div class="flex-1 min-w-0">
            <p class="text-sm text-foreground truncate">
              {{ s.title || '新对话' }}
            </p>
            <p class="text-xs text-muted-foreground">{{ formatRelativeTime(s.updated_at) }}</p>
          </div>
          <button
            class="opacity-0 group-hover:opacity-100 p-0.5 text-muted-foreground hover:text-red-400 transition-opacity"
            @click="deleteSession(s.id, $event)"
          >
            <Trash2 :size="13" />
          </button>
        </button>
      </div>
    </aside>

    <!-- 右侧聊天区 -->
    <div class="flex-1 flex flex-col min-w-0">
      <div class="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        <div
          v-if="!currentSessionId && !messagesLoading"
          class="flex flex-col items-center justify-center h-full gap-3 text-muted-foreground"
        >
          <span v-if="agent?.icon_emoji" class="text-4xl">{{ agent.icon_emoji }}</span>
          <p class="text-sm">{{ agent?.description || '开始与 Agent 对话' }}</p>
        </div>

        <div v-if="messagesLoading" class="flex justify-center py-8">
          <span class="text-sm text-muted-foreground">加载历史消息...</span>
        </div>

        <template v-if="!messagesLoading">
          <div
            v-for="(msg, i) in messages"
            :key="i"
            class="flex"
            :class="msg.role === 'user' ? 'justify-end' : 'justify-start'"
          >
            <div v-if="msg.role === 'user'" class="max-w-[70%] space-y-1">
              <div v-if="msg.attachments?.length" class="flex flex-wrap gap-2 justify-end">
                <a
                  v-for="att in msg.attachments"
                  :key="att.storage_key"
                  :href="att.url"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="block"
                >
                  <img
                    v-if="att.content_type.startsWith('image/')"
                    :src="att.url"
                    :alt="att.name"
                    class="h-24 w-auto rounded-lg object-cover border border-border"
                  />
                  <div
                    v-else
                    class="flex items-center gap-2 px-3 py-2 bg-card border border-border rounded-lg text-xs text-muted-foreground"
                  >
                    <FileText :size="14" />
                    <span class="truncate max-w-[160px]">{{ att.name }}</span>
                    <span class="text-muted-foreground/60">{{ formatFileSize(att.size) }}</span>
                  </div>
                </a>
              </div>
              <div
                v-if="msg.content"
                class="px-4 py-2.5 bg-primary text-primary-foreground text-sm rounded-2xl rounded-tr-sm whitespace-pre-wrap"
              >
                {{ msg.content }}
              </div>
            </div>

            <div v-else class="max-w-[70%]">
              <div
                class="px-4 py-2.5 bg-secondary text-secondary-foreground text-sm rounded-2xl rounded-tl-sm ea-msg-assistant"
              >
                <!-- eslint-disable-next-line vue/no-v-html -->
                <span v-html="renderContent(msg.content)" />
                <span
                  v-if="msg.streaming"
                  class="inline-block w-0.5 h-3.5 bg-muted-foreground ml-0.5 animate-pulse"
                />
              </div>
            </div>
          </div>
        </template>

        <div ref="messagesEndRef" />
      </div>

      <div class="border-t border-border px-4 py-3">
        <div v-if="pendingAttachments.length" class="flex flex-wrap gap-2 mb-2">
          <div
            v-for="(att, idx) in pendingAttachments"
            :key="att.storage_key"
            class="relative group"
          >
            <img
              v-if="att.content_type.startsWith('image/')"
              :src="att.previewUrl ?? att.url"
              :alt="att.name"
              class="h-16 w-auto rounded-lg object-cover border border-border"
            />
            <div
              v-else
              class="flex items-center gap-2 px-3 py-2 bg-muted rounded-lg text-xs text-muted-foreground border border-border"
            >
              <FileText :size="14" />
              <span class="truncate max-w-[100px]">{{ att.name }}</span>
            </div>
            <button
              class="absolute -top-1.5 -right-1.5 w-4 h-4 bg-foreground text-background rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
              @click="removePendingAttachment(idx)"
            >
              <X :size="10" />
            </button>
          </div>
          <div v-if="isUploading" class="flex items-center px-3 py-2 text-xs text-muted-foreground">
            上传中...
          </div>
        </div>

        <div class="flex items-end gap-2">
          <button
            class="p-2 text-muted-foreground hover:text-foreground transition-colors flex-shrink-0"
            :disabled="!currentSessionId || isStreaming"
            @click="openFilePicker"
          >
            <Paperclip :size="18" />
          </button>
          <input
            ref="fileInputRef"
            type="file"
            multiple
            class="hidden"
            @change="handleFileChange"
          />

          <textarea
            v-model="inputText"
            rows="1"
            class="flex-1 resize-none rounded-xl border border-border bg-background text-foreground placeholder:text-muted-foreground px-3 py-2 text-sm focus:outline-none focus:border-primary/50 max-h-32 overflow-y-auto ea-textarea"
            :class="{ 'opacity-50': !currentSessionId }"
            placeholder="输入消息，Enter 发送，Shift+Enter 换行"
            :disabled="!currentSessionId || isStreaming"
            @keydown="handleKeydown"
          />

          <button
            class="p-2 bg-primary text-primary-foreground rounded-xl hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex-shrink-0"
            :disabled="(!inputText.trim() && !pendingAttachments.length) || isStreaming || !currentSessionId"
            @click="send"
          >
            <Send :size="16" />
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 直接绑定 CSS 变量，绕过 Tailwind v4 oklch 链路解析问题 */
.ea-chat-root {
  background-color: var(--background);
  color: var(--foreground);
}

.ea-msg-assistant {
  background-color: var(--secondary);
  color: var(--secondary-foreground);
}

.ea-textarea {
  background-color: var(--background);
  color: var(--foreground);
}
</style>
