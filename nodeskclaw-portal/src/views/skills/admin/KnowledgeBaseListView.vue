<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { BookOpen, Plus, Trash2, Pencil, RefreshCw, CheckCircle2, XCircle, Circle } from 'lucide-vue-next'
import { useSkillStore } from '@/stores/skills'
import { kbApi } from '@/services/skills'
import type { KnowledgeBase } from '@/services/skills'
import KbSyncStatus from '@/components/skills/KbSyncStatus.vue'
import KnowledgeBasePreviewDrawer from '@/components/skills/KnowledgeBasePreviewDrawer.vue'

const router = useRouter()
const skillStore = useSkillStore()
const deleting = ref<string | null>(null)
const syncing = ref<string | null>(null)

// 预览 drawer 状态
const previewKb = ref<KnowledgeBase | null>(null)

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

async function sync(id: string) {
  syncing.value = id
  try {
    await kbApi.sync(id)
    // 刷新列表以获取最新 is_reachable 状态
    await skillStore.fetchKnowledgeBases()
  } finally {
    syncing.value = null
  }
}

function openPreview(kb: KnowledgeBase) {
  // 仅已连接的知识库支持预览
  if (!kb.is_reachable) return
  previewKb.value = kb
}
</script>

<template>
  <div class="max-w-5xl mx-auto px-6 py-8">
    <div class="flex items-center justify-between mb-6">
      <div class="flex items-center gap-3">
        <BookOpen class="w-6 h-6 text-primary" />
        <h1 class="text-xl font-semibold text-foreground">知识库管理</h1>
      </div>
      <button
        class="inline-flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
        @click="router.push('/admin/knowledge-bases/new')"
      >
        <Plus class="w-4 h-4" />
        新建知识库
      </button>
    </div>

    <div v-if="skillStore.loading" class="text-sm text-muted-foreground text-center py-16">加载中...</div>

    <div
      v-else-if="skillStore.knowledgeBases.length === 0"
      class="text-sm text-muted-foreground text-center py-16"
    >
      还没有知识库，点击「新建知识库」开始
    </div>

    <div v-else class="space-y-3">
      <div
        v-for="kb in skillStore.knowledgeBases"
        :key="kb.id"
        class="flex items-center justify-between rounded-xl border border-border bg-card px-5 py-4"
      >
        <!-- 点击左侧内容区打开预览，已连接时显示手形光标 -->
        <div
          class="flex items-center gap-4 flex-1 min-w-0"
          :class="kb.is_reachable ? 'cursor-pointer hover:opacity-80 transition-opacity' : 'cursor-default'"
          @click="openPreview(kb)"
        >
          <BookOpen class="w-5 h-5 text-muted-foreground shrink-0" />
          <div class="min-w-0">
            <p class="font-medium text-foreground text-sm">{{ kb.name }}</p>
            <p class="text-xs text-muted-foreground mt-0.5">{{ kb.ragflow_endpoint }}</p>
            <!-- 连接状态：已验证时显示时间 -->
            <p v-if="kb.last_checked_at" class="text-xs text-muted-foreground mt-0.5">
              上次验证：{{ new Date(kb.last_checked_at).toLocaleString('zh-CN') }}
            </p>
          </div>
          <KbSyncStatus :source-type="kb.source_type" />
          <!-- 连接状态标签 -->
          <span
            class="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium shrink-0"
            :class="{
              'bg-green-100 text-green-700': kb.is_reachable === true,
              'bg-red-100 text-red-700': kb.is_reachable === false && kb.last_checked_at !== null,
              'bg-gray-100 text-gray-500': kb.last_checked_at === null,
            }"
          >
            <CheckCircle2 v-if="kb.is_reachable === true" class="w-3 h-3" />
            <XCircle v-else-if="kb.is_reachable === false && kb.last_checked_at !== null" class="w-3 h-3" />
            <Circle v-else class="w-3 h-3" />
            <span v-if="kb.is_reachable === true">已连接</span>
            <span v-else-if="kb.is_reachable === false && kb.last_checked_at !== null">连接失败</span>
            <span v-else>未验证</span>
          </span>
        </div>
        <div class="flex items-center gap-2 ml-3 shrink-0">
          <!-- 连接验证按钮 -->
          <button
            class="p-2 rounded-lg text-muted-foreground hover:text-primary hover:bg-primary/10 disabled:opacity-40"
            :disabled="syncing === kb.id"
            :title="'验证连接'"
            @click.stop="sync(kb.id)"
          >
            <RefreshCw class="w-4 h-4" :class="{ 'animate-spin': syncing === kb.id }" />
          </button>
          <button
            class="p-2 rounded-lg text-muted-foreground hover:text-primary hover:bg-primary/10"
            @click.stop="router.push(`/admin/knowledge-bases/${kb.id}/edit`)"
          >
            <Pencil class="w-4 h-4" />
          </button>
          <button
            class="p-2 rounded-lg text-muted-foreground hover:text-destructive hover:bg-destructive/10 disabled:opacity-40"
            :disabled="deleting === kb.id"
            @click.stop="remove(kb.id)"
          >
            <Trash2 class="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- 知识库文档预览 drawer -->
  <KnowledgeBasePreviewDrawer :kb="previewKb" @close="previewKb = null" />
</template>
