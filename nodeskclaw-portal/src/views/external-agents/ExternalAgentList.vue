<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Bot, Plus, RefreshCw, CheckCircle2, XCircle, Circle, MessageSquare, Pencil, Trash2 } from 'lucide-vue-next'
import { useExternalAgentStore } from '@/stores/externalAgents'
import { externalAgentApi, type ExternalAgent } from '@/services/externalAgents'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const store = useExternalAgentStore()
const authStore = useAuthStore()

const syncing = ref<string | null>(null)
const deleting = ref<string | null>(null)

// org admin 才能看到管理操作
const isAdmin = computed(
  () => authStore.user?.portal_org_role === 'admin' || authStore.user?.is_super_admin,
)

onMounted(() => store.fetchAgents())

async function sync(agent: ExternalAgent) {
  syncing.value = agent.id
  try {
    await externalAgentApi.sync(agent.id)
    await store.fetchAgents()
  } finally {
    syncing.value = null
  }
}

async function remove(agent: ExternalAgent) {
  if (!confirm(`确定删除 Agent「${agent.name}」吗？`)) return
  deleting.value = agent.id
  try {
    await externalAgentApi.remove(agent.id)
    await store.fetchAgents()
  } finally {
    deleting.value = null
  }
}

function statusClass(agent: ExternalAgent) {
  if (agent.is_reachable) return 'bg-green-100 text-green-700'
  if (agent.last_checked_at) return 'bg-red-100 text-red-700'
  return 'bg-gray-100 text-gray-500'
}

function statusLabel(agent: ExternalAgent) {
  if (agent.is_reachable) return '已连接'
  if (agent.last_checked_at) return '连接失败'
  return '未验证'
}

function formatTime(ts: string | null) {
  if (!ts) return ''
  return new Date(ts).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}
</script>

<template>
  <div class="max-w-6xl mx-auto px-6 py-8">
    <!-- 页头 -->
    <div class="flex items-center justify-between mb-6">
      <div class="flex items-center gap-3">
        <Bot class="w-6 h-6 text-primary" />
        <h1 class="text-xl font-semibold text-foreground">专用 Agent</h1>
        <span class="text-xs text-muted-foreground">运行在外部服务器上的专用 AI Agent</span>
      </div>
      <button
        v-if="isAdmin"
        class="inline-flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
        @click="router.push('/org-settings/external-agents/new')"
      >
        <Plus class="w-4 h-4" />
        添加 Agent
      </button>
    </div>

    <!-- 加载中 -->
    <div v-if="store.loading" class="text-sm text-muted-foreground text-center py-20">
      加载中...
    </div>

    <!-- 空状态 -->
    <div
      v-else-if="store.agents.length === 0"
      class="flex flex-col items-center justify-center py-24 text-center"
    >
      <Bot class="w-12 h-12 text-muted-foreground/40 mb-4" />
      <p class="text-sm font-medium text-foreground mb-1">还没有接入专用 Agent</p>
      <p class="text-xs text-muted-foreground mb-4">
        由管理员添加运行在外部服务器的专用 AI Agent，连接后即可在此发起对话
      </p>
      <button
        v-if="isAdmin"
        class="inline-flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
        @click="router.push('/org-settings/external-agents/new')"
      >
        <Plus class="w-4 h-4" />
        添加 Agent
      </button>
    </div>

    <!-- 能力卡片网格 -->
    <div v-else class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      <div
        v-for="agent in store.agents"
        :key="agent.id"
        class="relative rounded-xl border border-border bg-card overflow-hidden flex flex-col"
      >
        <!-- 主题色装饰条 -->
        <div
          class="h-1 w-full shrink-0"
          :style="agent.theme_color ? `background:${agent.theme_color}` : 'background: var(--primary)'"
        />

        <!-- 卡片主体 -->
        <div class="flex-1 p-4 flex flex-col gap-3">
          <!-- 名称行 -->
          <div class="flex items-start gap-2">
            <span v-if="agent.icon_emoji" class="text-2xl leading-none shrink-0 mt-0.5">
              {{ agent.icon_emoji }}
            </span>
            <Bot v-else class="w-6 h-6 text-muted-foreground shrink-0 mt-0.5" />
            <div class="flex-1 min-w-0">
              <p class="font-semibold text-foreground text-sm leading-tight truncate">{{ agent.name }}</p>
              <!-- 协议 badge -->
              <span class="mt-0.5 inline-block text-[10px] font-medium px-1.5 py-0.5 rounded bg-violet-100 text-violet-700">
                {{ agent.protocol === 'openai_compatible' ? 'OpenAI 兼容' : '自定义协议' }}
              </span>
            </div>
          </div>

          <!-- 简介 -->
          <p v-if="agent.description" class="text-xs text-muted-foreground line-clamp-2">
            {{ agent.description }}
          </p>

          <!-- 能力标签 -->
          <div v-if="agent.capabilities.length" class="flex flex-wrap gap-1">
            <span
              v-for="cap in agent.capabilities"
              :key="cap"
              class="text-[10px] px-2 py-0.5 rounded-full bg-secondary text-secondary-foreground"
            >
              {{ cap }}
            </span>
          </div>

          <!-- 连接状态 -->
          <div class="flex items-center gap-1.5">
            <span
              class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium"
              :class="statusClass(agent)"
            >
              <CheckCircle2 v-if="agent.is_reachable" class="w-3 h-3" />
              <XCircle v-else-if="agent.last_checked_at" class="w-3 h-3" />
              <Circle v-else class="w-3 h-3" />
              {{ statusLabel(agent) }}
            </span>
            <span v-if="agent.last_checked_at" class="text-[10px] text-muted-foreground">
              {{ formatTime(agent.last_checked_at) }}
            </span>
          </div>
        </div>

        <!-- 操作栏 -->
        <div class="px-4 py-3 border-t border-border bg-muted/20 flex items-center gap-2">
          <button
            class="flex-1 inline-flex items-center justify-center gap-1.5 rounded-lg bg-primary text-primary-foreground py-1.5 text-xs font-medium hover:opacity-90"
            @click="router.push(`/agents/${agent.id}/chat`)"
          >
            <MessageSquare class="w-3.5 h-3.5" />
            发起对话
          </button>
          <button
            v-if="isAdmin"
            class="p-1.5 rounded-lg text-muted-foreground hover:text-primary hover:bg-primary/10 disabled:opacity-40"
            :disabled="syncing === agent.id"
            title="验证连接"
            @click="sync(agent)"
          >
            <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': syncing === agent.id }" />
          </button>
          <button
            v-if="isAdmin"
            class="p-1.5 rounded-lg text-muted-foreground hover:text-primary hover:bg-primary/10"
            @click="router.push(`/org-settings/external-agents/${agent.id}/edit`)"
          >
            <Pencil class="w-3.5 h-3.5" />
          </button>
          <button
            v-if="isAdmin"
            class="p-1.5 rounded-lg text-muted-foreground hover:text-destructive hover:bg-destructive/10 disabled:opacity-40"
            :disabled="deleting === agent.id"
            @click="remove(agent)"
          >
            <Trash2 class="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
