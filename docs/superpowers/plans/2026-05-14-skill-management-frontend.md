# Skill Management + RAGFlow — Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add "技能库" (Skill Library) to nodeskclaw-portal: admin views for managing knowledge bases and skill definitions, employee view for browsing and querying skills via RAG Q&A.

**Architecture:** Axios API module in `src/services/skills.ts`; Pinia store in `src/stores/skills.ts`; four admin views under `src/views/skills/admin/`; one employee view at `src/views/skills/SkillListView.vue`; two shared components under `src/components/skills/`; new routes registered in `src/router/index.ts`; navigation entries added to existing sidebar.

**Prerequisite:** Backend plan (`2026-05-14-skill-management-backend.md`) must be deployed and the dev server running at `http://localhost:4510`.

**Tech Stack:** Vue 3 (Composition API, `<script setup>`), Pinia, Vue Router, Axios (via `src/services/api.ts`), Tailwind CSS, lucide-vue-next

---

## File Map

**Create:**
- `src/services/skills.ts` — typed API wrappers for all skill endpoints
- `src/stores/skills.ts` — Pinia store for skill/KB state
- `src/views/skills/SkillListView.vue` — employee: skill card grid + RAG query entry
- `src/views/skills/admin/KnowledgeBaseListView.vue` — admin: KB list with sync status
- `src/views/skills/admin/KnowledgeBaseFormView.vue` — admin: create/edit KB form
- `src/views/skills/admin/SkillDefinitionListView.vue` — admin: skill list with enable/disable
- `src/views/skills/admin/SkillBindingView.vue` — admin: bind skills to Agent instances
- `src/components/skills/RagQueryDialog.vue` — employee RAG Q&A modal
- `src/components/skills/KbSyncStatus.vue` — sync state badge

**Modify:**
- `src/router/index.ts` — register 5 new routes
- Sidebar component (find it with `grep -r "sidebar\|nav-item" src/ --include="*.vue" -l | head -3`) — add "技能库" entry

---

## Task 1: API Service Module

**Files:**
- Create: `src/services/skills.ts`

- [ ] **Step 1: Write the API module**

```typescript
// src/services/skills.ts
import api from './api'

export interface KnowledgeBase {
  id: string
  org_id: string
  name: string
  ragflow_kb_id: string
  ragflow_endpoint: string
  source_type: 'doc' | 'system' | 'mixed'
  created_at: string
  updated_at: string
}

export interface KnowledgeBaseCreate {
  name: string
  ragflow_endpoint: string
  ragflow_kb_id: string
  api_key: string
  source_type: 'doc' | 'system' | 'mixed'
}

export interface KnowledgeBaseUpdate {
  name?: string
  ragflow_endpoint?: string
  ragflow_kb_id?: string
  api_key?: string
  source_type?: 'doc' | 'system' | 'mixed'
}

export interface Skill {
  id: string
  org_id: string
  name: string
  type: 'rag_query' | 'gene' | 'composite'
  kb_id: string | null
  config: Record<string, unknown>
  enabled: boolean
  created_at: string
}

export interface SkillCreate {
  name: string
  type: 'rag_query' | 'gene' | 'composite'
  kb_id?: string
  config?: Record<string, unknown>
}

export interface SkillUpdate {
  name?: string
  kb_id?: string
  config?: Record<string, unknown>
  enabled?: boolean
}

export interface QueryResult {
  degraded: boolean
  message: string | null
  results: Array<{ content: string; score?: number; [key: string]: unknown }>
}

// Knowledge Base API
export const kbApi = {
  list: () =>
    api.get<{ data: KnowledgeBase[] }>('/knowledge-bases').then((r) => r.data.data),

  create: (body: KnowledgeBaseCreate) =>
    api.post<{ data: KnowledgeBase }>('/knowledge-bases', body).then((r) => r.data.data),

  update: (id: string, body: KnowledgeBaseUpdate) =>
    api.patch<{ data: KnowledgeBase }>(`/knowledge-bases/${id}`, body).then((r) => r.data.data),

  remove: (id: string) => api.delete(`/knowledge-bases/${id}`),
}

// Skill API
export const skillApi = {
  listAdmin: (type?: string) =>
    api
      .get<{ data: Skill[] }>('/skills', { params: type ? { skill_type: type } : {} })
      .then((r) => r.data.data),

  listMy: () => api.get<{ data: Skill[] }>('/skills/my').then((r) => r.data.data),

  create: (body: SkillCreate) =>
    api.post<{ data: Skill }>('/skills', body).then((r) => r.data.data),

  update: (id: string, body: SkillUpdate) =>
    api.patch<{ data: Skill }>(`/skills/${id}`, body).then((r) => r.data.data),

  remove: (id: string) => api.delete(`/skills/${id}`),

  bind: (skillId: string, instanceId: string) =>
    api.post(`/skills/${skillId}/bind`, { instance_id: instanceId }),

  unbind: (skillId: string, instanceId: string) =>
    api.delete(`/skills/${skillId}/bind/${instanceId}`),

  query: (skillId: string, question: string) =>
    api
      .post<{ data: QueryResult }>(`/skills/${skillId}/query`, { question })
      .then((r) => r.data.data),
}
```

- [ ] **Step 2: Commit**

```bash
git add src/services/skills.ts
git commit -m "feat(skill): add skill API service module"
```

---

## Task 2: Pinia Store

**Files:**
- Create: `src/stores/skills.ts`

- [ ] **Step 1: Write the store**

```typescript
// src/stores/skills.ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { kbApi, skillApi, type KnowledgeBase, type Skill } from '@/services/skills'

export const useSkillStore = defineStore('skills', () => {
  const knowledgeBases = ref<KnowledgeBase[]>([])
  const skills = ref<Skill[]>([])
  const mySkills = ref<Skill[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchKnowledgeBases() {
    loading.value = true
    error.value = null
    try {
      knowledgeBases.value = await kbApi.list()
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '加载知识库失败'
    } finally {
      loading.value = false
    }
  }

  async function fetchSkills(type?: string) {
    loading.value = true
    error.value = null
    try {
      skills.value = await skillApi.listAdmin(type)
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '加载技能失败'
    } finally {
      loading.value = false
    }
  }

  async function fetchMySkills() {
    loading.value = true
    error.value = null
    try {
      mySkills.value = await skillApi.listMy()
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '加载技能失败'
    } finally {
      loading.value = false
    }
  }

  return {
    knowledgeBases,
    skills,
    mySkills,
    loading,
    error,
    fetchKnowledgeBases,
    fetchSkills,
    fetchMySkills,
  }
})
```

- [ ] **Step 2: Commit**

```bash
git add src/stores/skills.ts
git commit -m "feat(skill): add skills Pinia store"
```

---

## Task 3: Shared Components

**Files:**
- Create: `src/components/skills/KbSyncStatus.vue`
- Create: `src/components/skills/RagQueryDialog.vue`

- [ ] **Step 1: Create KbSyncStatus badge component**

```vue
<!-- src/components/skills/KbSyncStatus.vue -->
<script setup lang="ts">
defineProps<{ sourceType: 'doc' | 'system' | 'mixed' }>()

const labelMap = { doc: '文档', system: '系统数据', mixed: '混合' }
const colorMap = {
  doc: 'bg-blue-100 text-blue-700',
  system: 'bg-purple-100 text-purple-700',
  mixed: 'bg-amber-100 text-amber-700',
}
</script>

<template>
  <span
    class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium"
    :class="colorMap[sourceType]"
  >
    {{ labelMap[sourceType] }}
  </span>
</template>
```

- [ ] **Step 2: Create RagQueryDialog component**

```vue
<!-- src/components/skills/RagQueryDialog.vue -->
<script setup lang="ts">
import { ref } from 'vue'
import { MessageSquare, X, Send, AlertTriangle } from 'lucide-vue-next'
import { skillApi, type QueryResult } from '@/services/skills'

const props = defineProps<{ skillId: string; skillName: string }>()
const emit = defineEmits<{ close: [] }>()

const question = ref('')
const result = ref<QueryResult | null>(null)
const loading = ref(false)

async function submit() {
  if (!question.value.trim()) return
  loading.value = true
  result.value = null
  try {
    result.value = await skillApi.query(props.skillId, question.value.trim())
  } catch {
    result.value = { degraded: true, message: '请求失败，请稍后重试', results: [] }
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
    <div class="w-full max-w-2xl rounded-2xl bg-white shadow-xl flex flex-col max-h-[80vh]">
      <!-- Header -->
      <div class="flex items-center justify-between px-6 py-4 border-b">
        <div class="flex items-center gap-2">
          <MessageSquare class="w-5 h-5 text-blue-500" />
          <span class="font-semibold text-gray-900">{{ skillName }}</span>
        </div>
        <button class="text-gray-400 hover:text-gray-600" @click="emit('close')">
          <X class="w-5 h-5" />
        </button>
      </div>

      <!-- Results -->
      <div class="flex-1 overflow-y-auto px-6 py-4 space-y-3">
        <div v-if="!result && !loading" class="text-sm text-gray-400 text-center py-8">
          输入问题开始检索知识库
        </div>
        <div v-if="loading" class="text-sm text-gray-400 text-center py-8">检索中...</div>

        <!-- Degraded state -->
        <div
          v-if="result?.degraded"
          class="flex items-start gap-2 rounded-lg bg-amber-50 border border-amber-200 px-4 py-3"
        >
          <AlertTriangle class="w-4 h-4 text-amber-500 mt-0.5 shrink-0" />
          <p class="text-sm text-amber-800">{{ result.message }}</p>
        </div>

        <!-- Results -->
        <template v-if="result && !result.degraded">
          <div v-if="result.results.length === 0" class="text-sm text-gray-400 text-center py-4">
            未找到相关内容
          </div>
          <div
            v-for="(chunk, i) in result.results"
            :key="i"
            class="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3"
          >
            <p class="text-sm text-gray-700 whitespace-pre-wrap">{{ chunk.content }}</p>
            <p v-if="chunk.score != null" class="mt-1 text-xs text-gray-400">
              相关度 {{ (Number(chunk.score) * 100).toFixed(0) }}%
            </p>
          </div>
        </template>
      </div>

      <!-- Input -->
      <div class="px-6 py-4 border-t flex gap-2">
        <input
          v-model="question"
          class="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          placeholder="请输入问题..."
          @keydown.enter.prevent="submit"
        />
        <button
          class="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          :disabled="loading || !question.trim()"
          @click="submit"
        >
          <Send class="w-4 h-4" />
          发送
        </button>
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 3: Commit**

```bash
git add src/components/skills/
git commit -m "feat(skill): add KbSyncStatus badge and RagQueryDialog components"
```

---

## Task 4: Employee Skill View

**Files:**
- Create: `src/views/skills/SkillListView.vue`

- [ ] **Step 1: Create the employee skill list view**

```vue
<!-- src/views/skills/SkillListView.vue -->
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Brain } from 'lucide-vue-next'
import { useSkillStore } from '@/stores/skills'
import RagQueryDialog from '@/components/skills/RagQueryDialog.vue'
import type { Skill } from '@/services/skills'

const skillStore = useSkillStore()

const activeSkill = ref<Skill | null>(null)

onMounted(() => skillStore.fetchMySkills())

function openQuery(skill: Skill) {
  activeSkill.value = skill
}
</script>

<template>
  <div class="max-w-5xl mx-auto px-6 py-8">
    <div class="flex items-center gap-3 mb-6">
      <Brain class="w-6 h-6 text-blue-500" />
      <h1 class="text-xl font-semibold text-gray-900">技能库</h1>
    </div>

    <div v-if="skillStore.loading" class="text-sm text-gray-400 text-center py-16">加载中...</div>

    <div
      v-else-if="skillStore.mySkills.length === 0"
      class="text-sm text-gray-400 text-center py-16"
    >
      暂无可用技能，请联系管理员配置
    </div>

    <div v-else class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      <div
        v-for="skill in skillStore.mySkills"
        :key="skill.id"
        class="rounded-xl border border-gray-200 bg-white p-5 shadow-sm hover:shadow-md transition-shadow cursor-pointer"
        @click="openQuery(skill)"
      >
        <div class="flex items-start justify-between gap-2">
          <div class="flex items-center gap-2">
            <Brain class="w-5 h-5 text-blue-400 shrink-0" />
            <span class="font-medium text-gray-900 text-sm">{{ skill.name }}</span>
          </div>
          <span
            v-if="skill.type === 'rag_query'"
            class="shrink-0 rounded-full bg-blue-50 px-2 py-0.5 text-xs text-blue-600"
          >
            知识库
          </span>
        </div>
        <p class="mt-3 text-xs text-gray-400">点击开始问答</p>
      </div>
    </div>
  </div>

  <RagQueryDialog
    v-if="activeSkill"
    :skill-id="activeSkill.id"
    :skill-name="activeSkill.name"
    @close="activeSkill = null"
  />
</template>
```

- [ ] **Step 2: Commit**

```bash
git add src/views/skills/SkillListView.vue
git commit -m "feat(skill): add employee skill list view with RAG query"
```

---

## Task 5: Admin — Knowledge Base Views

**Files:**
- Create: `src/views/skills/admin/KnowledgeBaseListView.vue`
- Create: `src/views/skills/admin/KnowledgeBaseFormView.vue`

- [ ] **Step 1: Create the KB list view**

```vue
<!-- src/views/skills/admin/KnowledgeBaseListView.vue -->
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { BookOpen, Plus, Trash2, Pencil } from 'lucide-vue-next'
import { useSkillStore } from '@/stores/skills'
import { kbApi } from '@/services/skills'
import KbSyncStatus from '@/components/skills/KbSyncStatus.vue'

const router = useRouter()
const skillStore = useSkillStore()
const deleting = ref<string | null>(null)

onMounted(() => skillStore.fetchKnowledgeBases())

async function remove(id: string) {
  if (!confirm('确定删除该知识库吗？')) return
  deleting.value = id
  try {
    await kbApi.remove(id)
    await skillStore.fetchKnowledgeBases()
  } finally {
    deleting.value = null
  }
}
</script>

<template>
  <div class="max-w-5xl mx-auto px-6 py-8">
    <div class="flex items-center justify-between mb-6">
      <div class="flex items-center gap-3">
        <BookOpen class="w-6 h-6 text-blue-500" />
        <h1 class="text-xl font-semibold text-gray-900">知识库管理</h1>
      </div>
      <button
        class="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        @click="router.push('/admin/knowledge-bases/new')"
      >
        <Plus class="w-4 h-4" />
        新建知识库
      </button>
    </div>

    <div v-if="skillStore.loading" class="text-sm text-gray-400 text-center py-16">加载中...</div>

    <div
      v-else-if="skillStore.knowledgeBases.length === 0"
      class="text-sm text-gray-400 text-center py-16"
    >
      还没有知识库，点击「新建知识库」开始
    </div>

    <div v-else class="space-y-3">
      <div
        v-for="kb in skillStore.knowledgeBases"
        :key="kb.id"
        class="flex items-center justify-between rounded-xl border border-gray-200 bg-white px-5 py-4"
      >
        <div class="flex items-center gap-4">
          <BookOpen class="w-5 h-5 text-gray-400 shrink-0" />
          <div>
            <p class="font-medium text-gray-900 text-sm">{{ kb.name }}</p>
            <p class="text-xs text-gray-400 mt-0.5">{{ kb.ragflow_endpoint }}</p>
          </div>
          <KbSyncStatus :source-type="kb.source_type" />
        </div>
        <div class="flex items-center gap-2">
          <button
            class="p-2 rounded-lg text-gray-400 hover:text-blue-600 hover:bg-blue-50"
            @click="router.push(`/admin/knowledge-bases/${kb.id}/edit`)"
          >
            <Pencil class="w-4 h-4" />
          </button>
          <button
            class="p-2 rounded-lg text-gray-400 hover:text-red-600 hover:bg-red-50 disabled:opacity-40"
            :disabled="deleting === kb.id"
            @click="remove(kb.id)"
          >
            <Trash2 class="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 2: Create the KB form view**

```vue
<!-- src/views/skills/admin/KnowledgeBaseFormView.vue -->
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
      <BookOpen class="w-6 h-6 text-blue-500" />
      <h1 class="text-xl font-semibold text-gray-900">
        {{ isEdit ? '编辑知识库' : '新建知识库' }}
      </h1>
    </div>

    <div class="rounded-xl border border-gray-200 bg-white p-6 space-y-5">
      <div v-if="error" class="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
        {{ error }}
      </div>

      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">知识库名称</label>
        <input
          v-model="form.name"
          class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          placeholder="例如：产品手册知识库"
        />
      </div>

      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">RAGFlow 服务地址</label>
        <input
          v-model="form.ragflow_endpoint"
          class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          placeholder="http://ragflow:9380"
        />
      </div>

      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">RAGFlow Dataset ID</label>
        <input
          v-model="form.ragflow_kb_id"
          class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          placeholder="从 RAGFlow 控制台获取"
        />
      </div>

      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">
          API Key{{ isEdit ? '（留空则不更新）' : '' }}
        </label>
        <input
          v-model="form.api_key"
          type="password"
          class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          placeholder="RAGFlow API Key"
        />
      </div>

      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">知识来源类型</label>
        <select
          v-model="form.source_type"
          class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="doc">文档（Word/PDF）</option>
          <option value="system">业务系统数据</option>
          <option value="mixed">混合</option>
        </select>
      </div>

      <div class="flex gap-3 pt-2">
        <button
          class="flex-1 rounded-lg bg-blue-600 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          :disabled="saving"
          @click="save"
        >
          {{ saving ? '保存中...' : '保存' }}
        </button>
        <button
          class="flex-1 rounded-lg border border-gray-300 py-2 text-sm text-gray-700 hover:bg-gray-50"
          @click="router.push('/admin/knowledge-bases')"
        >
          取消
        </button>
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 3: Commit**

```bash
git add src/views/skills/admin/KnowledgeBaseListView.vue \
        src/views/skills/admin/KnowledgeBaseFormView.vue
git commit -m "feat(skill): add admin knowledge base list and form views"
```

---

## Task 6: Admin — Skill Definition & Binding Views

**Files:**
- Create: `src/views/skills/admin/SkillDefinitionListView.vue`
- Create: `src/views/skills/admin/SkillBindingView.vue`

- [ ] **Step 1: Create skill definition list view**

```vue
<!-- src/views/skills/admin/SkillDefinitionListView.vue -->
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Brain, Plus, Trash2, ToggleLeft, ToggleRight } from 'lucide-vue-next'
import { useSkillStore } from '@/stores/skills'
import { skillApi } from '@/services/skills'

const skillStore = useSkillStore()
const showForm = ref(false)
const saving = ref(false)
const error = ref<string | null>(null)

const form = ref({ name: '', type: 'rag_query' as const, kb_id: '', config: '{}' })

onMounted(() => skillStore.fetchSkills())

async function toggleEnabled(skillId: string, current: boolean) {
  await skillApi.update(skillId, { enabled: !current })
  await skillStore.fetchSkills()
}

async function remove(id: string) {
  if (!confirm('确定删除该技能？')) return
  await skillApi.remove(id)
  await skillStore.fetchSkills()
}

async function submit() {
  error.value = null
  saving.value = true
  try {
    let config: Record<string, unknown> = {}
    try {
      config = JSON.parse(form.value.config)
    } catch {
      error.value = 'Config 必须是合法的 JSON'
      saving.value = false
      return
    }
    await skillApi.create({
      name: form.value.name,
      type: form.value.type,
      kb_id: form.value.kb_id || undefined,
      config,
    })
    showForm.value = false
    form.value = { name: '', type: 'rag_query', kb_id: '', config: '{}' }
    await skillStore.fetchSkills()
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '创建失败'
  } finally {
    saving.value = false
  }
}

const typeLabel = { rag_query: '知识库问答', gene: 'Gene 技能', composite: '复合技能' }
</script>

<template>
  <div class="max-w-5xl mx-auto px-6 py-8">
    <div class="flex items-center justify-between mb-6">
      <div class="flex items-center gap-3">
        <Brain class="w-6 h-6 text-blue-500" />
        <h1 class="text-xl font-semibold text-gray-900">技能定义</h1>
      </div>
      <button
        class="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        @click="showForm = !showForm"
      >
        <Plus class="w-4 h-4" />
        新建技能
      </button>
    </div>

    <!-- Inline create form -->
    <div v-if="showForm" class="mb-6 rounded-xl border border-blue-200 bg-blue-50 p-5 space-y-4">
      <div v-if="error" class="text-sm text-red-700 bg-red-50 rounded-lg px-3 py-2">{{ error }}</div>
      <div class="grid grid-cols-2 gap-4">
        <div>
          <label class="block text-xs font-medium text-gray-600 mb-1">技能名称</label>
          <input
            v-model="form.name"
            class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="例如：产品文档问答"
          />
        </div>
        <div>
          <label class="block text-xs font-medium text-gray-600 mb-1">类型</label>
          <select
            v-model="form.type"
            class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="rag_query">知识库问答</option>
            <option value="gene">Gene 技能</option>
            <option value="composite">复合技能</option>
          </select>
        </div>
        <div>
          <label class="block text-xs font-medium text-gray-600 mb-1">知识库 ID（rag_query 必填）</label>
          <input
            v-model="form.kb_id"
            class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="知识库 ID"
          />
        </div>
        <div>
          <label class="block text-xs font-medium text-gray-600 mb-1">Config (JSON)</label>
          <input
            v-model="form.config"
            class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder='{"top_k": 5}'
          />
        </div>
      </div>
      <div class="flex gap-2">
        <button
          class="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          :disabled="saving"
          @click="submit"
        >
          {{ saving ? '创建中...' : '创建' }}
        </button>
        <button
          class="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
          @click="showForm = false"
        >
          取消
        </button>
      </div>
    </div>

    <div v-if="skillStore.loading" class="text-sm text-gray-400 text-center py-16">加载中...</div>
    <div v-else-if="skillStore.skills.length === 0" class="text-sm text-gray-400 text-center py-16">
      还没有技能定义
    </div>
    <div v-else class="space-y-3">
      <div
        v-for="skill in skillStore.skills"
        :key="skill.id"
        class="flex items-center justify-between rounded-xl border border-gray-200 bg-white px-5 py-4"
      >
        <div class="flex items-center gap-4">
          <Brain class="w-5 h-5 text-gray-400 shrink-0" />
          <div>
            <p class="font-medium text-gray-900 text-sm">{{ skill.name }}</p>
            <p class="text-xs text-gray-400 mt-0.5">{{ typeLabel[skill.type] }}</p>
          </div>
          <span
            class="rounded-full px-2 py-0.5 text-xs"
            :class="skill.enabled ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'"
          >
            {{ skill.enabled ? '启用' : '停用' }}
          </span>
        </div>
        <div class="flex items-center gap-1">
          <button
            class="p-2 rounded-lg text-gray-400 hover:text-blue-600 hover:bg-blue-50"
            :title="skill.enabled ? '停用' : '启用'"
            @click="toggleEnabled(skill.id, skill.enabled)"
          >
            <ToggleRight v-if="skill.enabled" class="w-4 h-4" />
            <ToggleLeft v-else class="w-4 h-4" />
          </button>
          <button
            class="p-2 rounded-lg text-gray-400 hover:text-red-600 hover:bg-red-50"
            @click="remove(skill.id)"
          >
            <Trash2 class="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 2: Create skill binding view**

```vue
<!-- src/views/skills/admin/SkillBindingView.vue -->
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Link, Unlink } from 'lucide-vue-next'
import { skillApi } from '@/services/skills'
import { useSkillStore } from '@/stores/skills'
import api from '@/services/api'

interface Instance {
  id: string
  name: string
}

const skillStore = useSkillStore()
const instances = ref<Instance[]>([])
const selectedSkill = ref<string>('')
const selectedInstance = ref<string>('')
const loading = ref(false)
const message = ref<{ type: 'success' | 'error'; text: string } | null>(null)

onMounted(async () => {
  await skillStore.fetchSkills()
  const res = await api.get<{ data: Instance[] }>('/instances')
  instances.value = res.data.data ?? []
})

async function bind() {
  if (!selectedSkill.value || !selectedInstance.value) return
  loading.value = true
  message.value = null
  try {
    await skillApi.bind(selectedSkill.value, selectedInstance.value)
    message.value = { type: 'success', text: '绑定成功' }
  } catch (e: unknown) {
    message.value = { type: 'error', text: e instanceof Error ? e.message : '绑定失败' }
  } finally {
    loading.value = false
  }
}

async function unbind() {
  if (!selectedSkill.value || !selectedInstance.value) return
  loading.value = true
  message.value = null
  try {
    await skillApi.unbind(selectedSkill.value, selectedInstance.value)
    message.value = { type: 'success', text: '解绑成功' }
  } catch (e: unknown) {
    message.value = { type: 'error', text: e instanceof Error ? e.message : '解绑失败' }
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="max-w-2xl mx-auto px-6 py-8">
    <div class="flex items-center gap-3 mb-6">
      <Link class="w-6 h-6 text-blue-500" />
      <h1 class="text-xl font-semibold text-gray-900">技能绑定</h1>
    </div>

    <div class="rounded-xl border border-gray-200 bg-white p-6 space-y-5">
      <div
        v-if="message"
        class="rounded-lg px-4 py-3 text-sm"
        :class="message.type === 'success' ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'"
      >
        {{ message.text }}
      </div>

      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">选择技能</label>
        <select
          v-model="selectedSkill"
          class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="" disabled>请选择技能</option>
          <option v-for="s in skillStore.skills" :key="s.id" :value="s.id">{{ s.name }}</option>
        </select>
      </div>

      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">选择 Agent 实例</label>
        <select
          v-model="selectedInstance"
          class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="" disabled>请选择实例</option>
          <option v-for="i in instances" :key="i.id" :value="i.id">{{ i.name }}</option>
        </select>
      </div>

      <div class="flex gap-3 pt-2">
        <button
          class="flex-1 inline-flex items-center justify-center gap-1.5 rounded-lg bg-blue-600 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          :disabled="loading || !selectedSkill || !selectedInstance"
          @click="bind"
        >
          <Link class="w-4 h-4" />
          绑定
        </button>
        <button
          class="flex-1 inline-flex items-center justify-center gap-1.5 rounded-lg border border-gray-300 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          :disabled="loading || !selectedSkill || !selectedInstance"
          @click="unbind"
        >
          <Unlink class="w-4 h-4" />
          解绑
        </button>
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 3: Commit**

```bash
git add src/views/skills/admin/SkillDefinitionListView.vue \
        src/views/skills/admin/SkillBindingView.vue
git commit -m "feat(skill): add admin skill definition and binding views"
```

---

## Task 7: Router & Navigation

**Files:**
- Modify: `src/router/index.ts`
- Modify: sidebar component (find path with `grep -rl "sidebar\|SideNav\|NavItem" src/ --include="*.vue" | head -3`)

- [ ] **Step 1: Register new routes in `src/router/index.ts`**

Find the `ceRoutes` or main routes array and add:

```typescript
// Employee route
{
  path: '/skills',
  name: 'SkillList',
  component: () => import('@/views/skills/SkillListView.vue'),
  meta: { requiresAuth: true },
},
// Admin routes
{
  path: '/admin/knowledge-bases',
  name: 'AdminKnowledgeBaseList',
  component: () => import('@/views/skills/admin/KnowledgeBaseListView.vue'),
  meta: { requiresAuth: true },
},
{
  path: '/admin/knowledge-bases/new',
  name: 'AdminKnowledgeBaseNew',
  component: () => import('@/views/skills/admin/KnowledgeBaseFormView.vue'),
  meta: { requiresAuth: true },
},
{
  path: '/admin/knowledge-bases/:id/edit',
  name: 'AdminKnowledgeBaseEdit',
  component: () => import('@/views/skills/admin/KnowledgeBaseFormView.vue'),
  meta: { requiresAuth: true },
},
{
  path: '/admin/skills',
  name: 'AdminSkillDefinitionList',
  component: () => import('@/views/skills/admin/SkillDefinitionListView.vue'),
  meta: { requiresAuth: true },
},
{
  path: '/admin/skills/bind',
  name: 'AdminSkillBinding',
  component: () => import('@/views/skills/admin/SkillBindingView.vue'),
  meta: { requiresAuth: true },
},
```

- [ ] **Step 2: Find the sidebar component**

```bash
grep -rl "sidebar\|SideNav\|nav-item\|router-link" src/ --include="*.vue" | head -5
```

Open the file that contains the main navigation links (typically has "实例", "工作区" etc.).

- [ ] **Step 3: Add navigation entries to the sidebar**

In the employee navigation section (where you see links to instances/workspaces), add:

```vue
<router-link
  to="/skills"
  class="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-gray-700 hover:bg-gray-100"
  active-class="bg-gray-100 font-medium"
>
  <Brain class="w-4 h-4" />
  技能库
</router-link>
```

In the admin navigation section (where you see org settings etc.), add:

```vue
<router-link
  to="/admin/knowledge-bases"
  class="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-gray-700 hover:bg-gray-100"
  active-class="bg-gray-100 font-medium"
>
  <BookOpen class="w-4 h-4" />
  知识库管理
</router-link>
<router-link
  to="/admin/skills"
  class="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-gray-700 hover:bg-gray-100"
  active-class="bg-gray-100 font-medium"
>
  <Brain class="w-4 h-4" />
  技能定义
</router-link>
```

Make sure `Brain` and `BookOpen` are imported from `lucide-vue-next` at the top of the sidebar component.

- [ ] **Step 4: Start the dev server and verify all routes load**

```bash
cd nodeskclaw-portal
npm run dev
```

Check each route loads without errors:
- http://localhost:4517/skills
- http://localhost:4517/admin/knowledge-bases
- http://localhost:4517/admin/knowledge-bases/new
- http://localhost:4517/admin/skills
- http://localhost:4517/admin/skills/bind

- [ ] **Step 5: Commit**

```bash
git add src/router/index.ts <sidebar-component-path>
git commit -m "feat(skill): register routes and add sidebar navigation"
```

---

## Task 8: End-to-End Smoke Test

- [ ] **Step 1: Start backend and frontend**

```bash
# Terminal 1 — backend
cd nodeskclaw-backend && uv run uvicorn app.main:app --reload --port 4510

# Terminal 2 — frontend
cd nodeskclaw-portal && npm run dev
```

- [ ] **Step 2: Admin flow — create knowledge base**

1. Log in as an org admin at http://localhost:4517
2. Navigate to "知识库管理" in sidebar
3. Click "新建知识库", fill in a RAGFlow endpoint and dataset ID
4. Save — confirm the KB appears in the list with the correct source type badge

- [ ] **Step 3: Admin flow — create skill and bind**

1. Navigate to "技能定义"
2. Create a `rag_query` skill referencing the KB created above
3. Navigate to "技能绑定", select the skill and an instance, click "绑定"
4. Confirm success message

- [ ] **Step 4: Employee flow — query skill**

1. Log in as a regular org member
2. Navigate to "技能库" — the skill created above should appear
3. Click the skill card, enter a question, click "发送"
4. Confirm results appear (or degraded message if RAGFlow is unreachable)

- [ ] **Step 5: Commit final smoke test marker**

```bash
git commit --allow-empty -m "chore(skill): e2e smoke test passed"
```
