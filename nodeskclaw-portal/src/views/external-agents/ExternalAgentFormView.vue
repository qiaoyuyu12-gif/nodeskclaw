<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { Bot, X } from 'lucide-vue-next'
import { externalAgentApi, type ExternalAgentCreate } from '@/services/externalAgents'

const router = useRouter()
const route = useRoute()

const isEdit = !!route.params.id
const saving = ref(false)
const error = ref<string | null>(null)

// 能力标签输入框（逗号分隔后拆分为数组）
const capInput = ref('')

const form = ref<ExternalAgentCreate & { api_key: string }>({
  name: '',
  endpoint: '',
  api_key: '',
  protocol: 'openai_compatible',
  description: '',
  capabilities: [],
  icon_emoji: '',
  theme_color: '',
})

onMounted(async () => {
  if (!isEdit) return
  try {
    const agents = await externalAgentApi.list()
    const agent = agents.find((a) => a.id === route.params.id)
    if (agent) {
      form.value.name = agent.name
      form.value.endpoint = agent.endpoint
      form.value.protocol = agent.protocol
      form.value.description = agent.description ?? ''
      form.value.capabilities = agent.capabilities
      form.value.icon_emoji = agent.icon_emoji ?? ''
      form.value.theme_color = agent.theme_color ?? ''
      capInput.value = agent.capabilities.join('，')
    }
  } catch {
    error.value = '加载 Agent 信息失败'
  }
})

function parseCaps(raw: string): string[] {
  return raw
    .split(/[,，\s]+/)
    .map((s) => s.trim())
    .filter(Boolean)
}

function removeTag(cap: string) {
  form.value.capabilities = form.value.capabilities.filter((c) => c !== cap)
  capInput.value = form.value.capabilities.join('，')
}

function onCapInputBlur() {
  form.value.capabilities = parseCaps(capInput.value)
}

async function save() {
  error.value = null
  saving.value = true
  form.value.capabilities = parseCaps(capInput.value)
  try {
    if (isEdit) {
      const updates: Record<string, unknown> = {
        name: form.value.name,
        endpoint: form.value.endpoint,
        protocol: form.value.protocol,
        description: form.value.description || undefined,
        capabilities: form.value.capabilities,
        icon_emoji: form.value.icon_emoji || undefined,
        theme_color: form.value.theme_color || undefined,
      }
      if (form.value.api_key) updates.api_key = form.value.api_key
      await externalAgentApi.update(route.params.id as string, updates)
    } else {
      await externalAgentApi.create({
        ...form.value,
        api_key: form.value.api_key || undefined,
        description: form.value.description || undefined,
        icon_emoji: form.value.icon_emoji || undefined,
        theme_color: form.value.theme_color || undefined,
      })
    }
    router.push('/agents')
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '保存失败，请检查配置'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="max-w-2xl mx-auto px-6 py-8">
    <div class="flex items-center gap-3 mb-6">
      <Bot class="w-6 h-6 text-primary" />
      <h1 class="text-xl font-semibold text-foreground">
        {{ isEdit ? '编辑 Agent' : '添加专用 Agent' }}
      </h1>
    </div>

    <div class="rounded-xl border border-border bg-card p-6 space-y-5">
      <div v-if="error" class="rounded-lg bg-destructive/10 px-4 py-3 text-sm text-destructive">
        {{ error }}
      </div>

      <!-- 名称 -->
      <div>
        <label class="block text-sm font-medium text-foreground mb-1">Agent 名称<span class="text-destructive ml-0.5">*</span></label>
        <input
          v-model="form.name"
          class="w-full rounded-lg border border-input bg-background text-foreground px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
          placeholder="例如：数据分析专家"
        />
      </div>

      <!-- 服务地址 -->
      <div>
        <label class="block text-sm font-medium text-foreground mb-1">服务地址<span class="text-destructive ml-0.5">*</span></label>
        <input
          v-model="form.endpoint"
          class="w-full rounded-lg border border-input bg-background text-foreground px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
          placeholder="http://agent.example.com:8000"
        />
        <p class="text-xs text-muted-foreground mt-1">Agent 服务的根地址，不含路径</p>
      </div>

      <!-- API Key -->
      <div>
        <label class="block text-sm font-medium text-foreground mb-1">
          API Key{{ isEdit ? '（留空则不更新）' : '' }}
        </label>
        <input
          v-model="form.api_key"
          type="password"
          class="w-full rounded-lg border border-input bg-background text-foreground px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
          placeholder="Bearer Token 或 API Key"
        />
      </div>

      <!-- 协议 -->
      <div>
        <label class="block text-sm font-medium text-foreground mb-1">通信协议</label>
        <select
          v-model="form.protocol"
          class="w-full rounded-lg border border-input bg-background text-foreground px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
        >
          <option value="openai_compatible">OpenAI 兼容（/v1/chat/completions）</option>
          <option value="custom">自定义（/chat + /health）</option>
        </select>
      </div>

      <!-- 简介 -->
      <div>
        <label class="block text-sm font-medium text-foreground mb-1">简介</label>
        <textarea
          v-model="form.description"
          rows="2"
          class="w-full rounded-lg border border-input bg-background text-foreground px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 resize-none"
          placeholder="一句话描述该 Agent 的专长"
        />
      </div>

      <!-- 能力标签 -->
      <div>
        <label class="block text-sm font-medium text-foreground mb-1">能力标签</label>
        <!-- 已添加的标签 -->
        <div v-if="form.capabilities.length" class="flex flex-wrap gap-1.5 mb-2">
          <span
            v-for="cap in form.capabilities"
            :key="cap"
            class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-secondary text-secondary-foreground text-xs"
          >
            {{ cap }}
            <button type="button" class="text-muted-foreground hover:text-foreground" @click="removeTag(cap)">
              <X class="w-3 h-3" />
            </button>
          </span>
        </div>
        <input
          v-model="capInput"
          class="w-full rounded-lg border border-input bg-background text-foreground px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
          placeholder="代码审查，SQL生成，报告撰写（逗号或空格分隔）"
          @blur="onCapInputBlur"
        />
      </div>

      <!-- 图标 & 主题色（一行两列） -->
      <div class="grid grid-cols-2 gap-4">
        <div>
          <label class="block text-sm font-medium text-foreground mb-1">图标 Emoji</label>
          <input
            v-model="form.icon_emoji"
            class="w-full rounded-lg border border-input bg-background text-foreground px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
            placeholder="🤖"
            maxlength="2"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-foreground mb-1">主题色</label>
          <div class="flex gap-2 items-center">
            <input
              v-model="form.theme_color"
              type="color"
              class="h-9 w-12 rounded-lg border border-input cursor-pointer bg-background p-0.5"
            />
            <input
              v-model="form.theme_color"
              class="flex-1 rounded-lg border border-input bg-background text-foreground px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
              placeholder="#7c3aed"
            />
          </div>
        </div>
      </div>

      <!-- 操作按钮 -->
      <div class="flex gap-3 pt-2">
        <button
          class="flex-1 rounded-lg bg-primary text-primary-foreground py-2 text-sm font-medium hover:opacity-90 disabled:opacity-50"
          :disabled="saving || !form.name || !form.endpoint"
          @click="save"
        >
          {{ saving ? '保存中...' : '保存' }}
        </button>
        <button
          class="flex-1 rounded-lg border border-border text-foreground py-2 text-sm hover:bg-muted/50"
          @click="router.push('/agents')"
        >
          取消
        </button>
      </div>
    </div>
  </div>
</template>
