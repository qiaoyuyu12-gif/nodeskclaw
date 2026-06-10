<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { BookOpen } from 'lucide-vue-next'
import { kbApi, type KnowledgeBaseCreate, type KnowledgeBase } from '@/services/skills'

const router = useRouter()
const route = useRoute()

const isEdit = !!route.params.id
const saving = ref(false)
const error = ref<string | null>(null)

const form = ref<KnowledgeBaseCreate>({
  name: '',
  ragflow_endpoint: '',
  ragflow_kb_id: '',
  api_key: '',
  source_type: 'doc',
})

onMounted(async () => {
  if (!isEdit) return
  try {
    const kbs = await kbApi.list()
    const kb = kbs.find((k: KnowledgeBase) => k.id === route.params.id)
    if (kb) {
      form.value.name = kb.name
      form.value.ragflow_endpoint = kb.ragflow_endpoint
      form.value.ragflow_kb_id = kb.ragflow_kb_id
      form.value.source_type = kb.source_type
    }
  } catch {
    error.value = '加载知识库信息失败'
  }
})

async function save() {
  error.value = null
  saving.value = true
  try {
    if (isEdit) {
      const updates: Partial<KnowledgeBaseCreate> = { ...form.value }
      if (!updates.api_key) delete updates.api_key
      await kbApi.update(route.params.id as string, updates)
    } else {
      await kbApi.create(form.value)
    }
    router.push('/admin/knowledge-bases')
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
      <BookOpen class="w-6 h-6 text-primary" />
      <h1 class="text-xl font-semibold text-foreground">
        {{ isEdit ? '编辑知识库' : '新建知识库' }}
      </h1>
    </div>

    <div class="rounded-xl border border-border bg-card p-6 space-y-5">
      <div v-if="error" class="rounded-lg bg-destructive/10 px-4 py-3 text-sm text-destructive">
        {{ error }}
      </div>

      <div>
        <label class="block text-sm font-medium text-foreground mb-1">知识库名称</label>
        <input
          v-model="form.name"
          class="w-full rounded-lg border border-input bg-background text-foreground px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
          placeholder="例如：产品手册知识库"
        />
      </div>

      <div>
        <label class="block text-sm font-medium text-foreground mb-1">RAGFlow 服务地址</label>
        <input
          v-model="form.ragflow_endpoint"
          class="w-full rounded-lg border border-input bg-background text-foreground px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
          placeholder="http://ragflow:9380"
        />
      </div>

      <div>
        <label class="block text-sm font-medium text-foreground mb-1">RAGFlow Dataset ID</label>
        <input
          v-model="form.ragflow_kb_id"
          class="w-full rounded-lg border border-input bg-background text-foreground px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
          placeholder="从 RAGFlow 控制台获取"
        />
      </div>

      <div>
        <label class="block text-sm font-medium text-foreground mb-1">
          API Key{{ isEdit ? '（留空则不更新）' : '' }}
        </label>
        <input
          v-model="form.api_key"
          type="password"
          class="w-full rounded-lg border border-input bg-background text-foreground px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
          placeholder="RAGFlow API Key"
        />
      </div>

      <div>
        <label class="block text-sm font-medium text-foreground mb-1">知识来源类型</label>
        <select
          v-model="form.source_type"
          class="w-full rounded-lg border border-input bg-background text-foreground px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
        >
          <option value="doc">文档（Word/PDF）</option>
          <option value="system">业务系统数据</option>
          <option value="mixed">混合</option>
        </select>
      </div>

      <div class="flex gap-3 pt-2">
        <button
          class="flex-1 rounded-lg bg-primary text-primary-foreground py-2 text-sm font-medium hover:opacity-90 disabled:opacity-50"
          :disabled="saving"
          @click="save"
        >
          {{ saving ? '保存中...' : '保存' }}
        </button>
        <button
          class="flex-1 rounded-lg border border-border text-foreground py-2 text-sm hover:bg-muted/50"
          @click="router.push('/admin/knowledge-bases')"
        >
          取消
        </button>
      </div>
    </div>
  </div>
</template>
