<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Bot, Send, Loader2, AlertCircle, RefreshCw } from 'lucide-vue-next'
import { externalAgentApi, type ExternalAgent } from '@/services/externalAgents'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const agentId = computed(() => route.params.id as string)

// ── Agent 信息 ────────────────────────────────
const agent = ref<ExternalAgent | null>(null)
const agentLoading = ref(true)
const agentError = ref('')

// ── 消息列表 ─────────────────────────────────
interface Msg {
  id: string
  role: 'user' | 'assistant'
  content: string
  streaming?: boolean
}

const messages = ref<Msg[]>([])
const input = ref('')
const sending = ref(false)
const scrollEl = ref<HTMLDivElement>()

// custom 协议（mom_agent）使用稳定 session_id 维持多轮记忆
// 每次进入聊天页生成一个新 session，刷新/清除后重新生成
const chatSessionId = ref(crypto.randomUUID())

// 历史记录（发送给 API）
const history = computed<Array<{ role: string; content: string }>>(() =>
  messages.value.map((m) => ({ role: m.role, content: m.content })),
)

onMounted(async () => {
  try {
    const list = await externalAgentApi.list()
    agent.value = list.find((a) => a.id === agentId.value) ?? null
    if (!agent.value) agentError.value = 'Agent 不存在或已被删除'
  } catch (e: unknown) {
    agentError.value = e instanceof Error ? e.message : '加载 Agent 失败'
  } finally {
    agentLoading.value = false
  }
})

async function scrollToBottom() {
  await nextTick()
  if (scrollEl.value) {
    scrollEl.value.scrollTop = scrollEl.value.scrollHeight
  }
}

async function send() {
  const text = input.value.trim()
  if (!text || sending.value || !agent.value) return

  input.value = ''
  sending.value = true

  // 追加用户消息
  messages.value.push({ id: Date.now().toString(), role: 'user', content: text })
  await scrollToBottom()

  // 创建占位 assistant 消息（流式追加）
  const assistantId = (Date.now() + 1).toString()
  messages.value.push({ id: assistantId, role: 'assistant', content: '', streaming: true })
  await scrollToBottom()

  try {
    const messagesForApi = [
      ...history.value.slice(0, -1), // 去掉刚加入的空 assistant 占位
      { role: 'user', content: text },
    ]
    const resp = await externalAgentApi.chatStream(agentId.value, messagesForApi, chatSessionId.value)

    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`)
    }

    const reader = resp.body?.getReader()
    const decoder = new TextDecoder()

    if (!reader) throw new Error('无法读取响应流')

    let buffer = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      // 按 SSE 行解析
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''

      for (const line of lines) {
        if (!line.startsWith('data:')) continue
        const raw = line.slice(5).trim()
        try {
          const payload = JSON.parse(raw)
          if (payload.done) {
            break
          }
          if (payload.error) {
            const msg = messages.value.find((m) => m.id === assistantId)
            if (msg) msg.content = `[错误] ${payload.error}`
          } else if (payload.chunk) {
            const msg = messages.value.find((m) => m.id === assistantId)
            if (msg) {
              msg.content += payload.chunk
              await scrollToBottom()
            }
          }
        } catch {
          // 忽略非 JSON 行
        }
      }
    }
  } catch (e: unknown) {
    const msg = messages.value.find((m) => m.id === assistantId)
    if (msg) msg.content = `[连接失败] ${e instanceof Error ? e.message : '未知错误'}`
  } finally {
    const msg = messages.value.find((m) => m.id === assistantId)
    if (msg) msg.streaming = false
    sending.value = false
    await scrollToBottom()
  }
}

function clearMessages() {
  if (!confirm('确定清除所有对话记录吗？')) return
  messages.value = []
  // 重置 session_id，下次对话在 agent 侧也是全新会话
  chatSessionId.value = crypto.randomUUID()
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}
</script>

<template>
  <div class="flex flex-col h-screen bg-background">
    <!-- 顶部导航栏 -->
    <header class="h-14 flex items-center gap-3 px-4 border-b border-border bg-card/80 backdrop-blur-sm shrink-0">
      <button
        class="p-2 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/50"
        @click="router.push('/agents')"
      >
        <ArrowLeft class="w-4 h-4" />
      </button>
      <div class="flex items-center gap-2 flex-1 min-w-0">
        <span v-if="agent?.icon_emoji" class="text-xl leading-none">{{ agent.icon_emoji }}</span>
        <Bot v-else class="w-5 h-5 text-muted-foreground shrink-0" />
        <span class="font-semibold text-foreground text-sm truncate">
          {{ agent?.name ?? '...' }}
        </span>
        <!-- 连接状态小点 -->
        <span
          v-if="agent"
          class="w-2 h-2 rounded-full shrink-0"
          :class="agent.is_reachable ? 'bg-green-500' : 'bg-gray-300'"
          :title="agent.is_reachable ? '已连接' : '未验证或连接失败'"
        />
      </div>
      <button
        v-if="messages.length"
        class="p-2 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/50"
        title="清除对话"
        @click="clearMessages"
      >
        <RefreshCw class="w-4 h-4" />
      </button>
    </header>

    <!-- 加载中 / 错误 -->
    <div v-if="agentLoading" class="flex-1 flex items-center justify-center text-muted-foreground text-sm">
      <Loader2 class="w-5 h-5 animate-spin mr-2" />
      加载中...
    </div>
    <div
      v-else-if="agentError"
      class="flex-1 flex flex-col items-center justify-center gap-3 text-muted-foreground"
    >
      <AlertCircle class="w-8 h-8 text-destructive" />
      <p class="text-sm">{{ agentError }}</p>
      <button
        class="text-xs text-primary hover:underline"
        @click="router.push('/agents')"
      >
        返回 Agent 列表
      </button>
    </div>

    <!-- 聊天区域 -->
    <template v-else>
      <!-- 消息列表 -->
      <div ref="scrollEl" class="flex-1 overflow-y-auto px-4 py-6 space-y-4">
        <!-- 欢迎语 -->
        <div v-if="messages.length === 0" class="flex flex-col items-center justify-center h-full text-center">
          <span v-if="agent?.icon_emoji" class="text-5xl mb-4">{{ agent.icon_emoji }}</span>
          <Bot v-else class="w-12 h-12 text-muted-foreground/40 mb-4" />
          <p class="font-semibold text-foreground mb-1">{{ agent?.name }}</p>
          <p v-if="agent?.description" class="text-sm text-muted-foreground max-w-sm">
            {{ agent.description }}
          </p>
          <div v-if="agent?.capabilities.length" class="flex flex-wrap justify-center gap-1.5 mt-3">
            <span
              v-for="cap in agent.capabilities"
              :key="cap"
              class="text-xs px-2.5 py-0.5 rounded-full bg-secondary text-secondary-foreground"
            >
              {{ cap }}
            </span>
          </div>
          <p class="text-xs text-muted-foreground mt-6">发送消息开始对话</p>
        </div>

        <!-- 消息气泡 -->
        <div
          v-for="msg in messages"
          :key="msg.id"
          class="flex"
          :class="msg.role === 'user' ? 'justify-end' : 'justify-start'"
        >
          <!-- assistant 头像 -->
          <div v-if="msg.role === 'assistant'" class="w-7 h-7 rounded-full bg-primary/10 flex items-center justify-center shrink-0 mr-2 mt-0.5">
            <span v-if="agent?.icon_emoji" class="text-sm leading-none">{{ agent.icon_emoji }}</span>
            <Bot v-else class="w-3.5 h-3.5 text-primary" />
          </div>

          <div
            class="max-w-[72%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap"
            :class="
              msg.role === 'user'
                ? 'bg-primary text-primary-foreground rounded-br-sm'
                : 'bg-card border border-border text-foreground rounded-bl-sm'
            "
          >
            <span>{{ msg.content }}</span>
            <!-- 流式光标 -->
            <span v-if="msg.streaming" class="inline-block w-0.5 h-4 bg-current animate-pulse ml-0.5 align-middle" />
          </div>

          <!-- 用户头像 -->
          <div v-if="msg.role === 'user'" class="w-7 h-7 rounded-full bg-primary flex items-center justify-center shrink-0 ml-2 mt-0.5">
            <span class="text-[10px] text-primary-foreground font-bold">
              {{ authStore.user?.name?.[0]?.toUpperCase() ?? 'U' }}
            </span>
          </div>
        </div>
      </div>

      <!-- 输入框 -->
      <div class="px-4 py-3 border-t border-border bg-card/80 backdrop-blur-sm shrink-0">
        <div class="flex items-end gap-2 rounded-xl border border-input bg-background px-3 py-2 focus-within:ring-2 focus-within:ring-primary/30">
          <textarea
            v-model="input"
            rows="1"
            class="flex-1 bg-transparent text-sm text-foreground resize-none focus:outline-none max-h-32"
            placeholder="输入消息，Enter 发送，Shift+Enter 换行"
            :disabled="sending"
            @keydown="onKeydown"
          />
          <button
            class="p-1.5 rounded-lg bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-40 shrink-0"
            :disabled="!input.trim() || sending"
            @click="send"
          >
            <Loader2 v-if="sending" class="w-4 h-4 animate-spin" />
            <Send v-else class="w-4 h-4" />
          </button>
        </div>
      </div>
    </template>
  </div>
</template>
