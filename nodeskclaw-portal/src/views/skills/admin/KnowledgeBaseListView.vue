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
        <div class="flex items-center gap-4">
          <BookOpen class="w-5 h-5 text-muted-foreground shrink-0" />
          <div>
            <p class="font-medium text-foreground text-sm">{{ kb.name }}</p>
            <p class="text-xs text-muted-foreground mt-0.5">{{ kb.ragflow_endpoint }}</p>
          </div>
          <KbSyncStatus :source-type="kb.source_type" />
        </div>
        <div class="flex items-center gap-2">
          <button
            class="p-2 rounded-lg text-muted-foreground hover:text-primary hover:bg-primary/10"
            @click="router.push(`/admin/knowledge-bases/${kb.id}/edit`)"
          >
            <Pencil class="w-4 h-4" />
          </button>
          <button
            class="p-2 rounded-lg text-muted-foreground hover:text-destructive hover:bg-destructive/10 disabled:opacity-40"
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
