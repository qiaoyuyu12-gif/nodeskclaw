import { defineStore } from 'pinia'
import { ref } from 'vue'
import { kbApi, type KnowledgeBase } from '@/services/skills'

export const useSkillStore = defineStore('skills', () => {
  const knowledgeBases = ref<KnowledgeBase[]>([])
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

  return { knowledgeBases, loading, error, fetchKnowledgeBases }
})