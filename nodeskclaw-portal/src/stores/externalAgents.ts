import { defineStore } from 'pinia'
import { ref } from 'vue'
import { externalAgentApi, type ExternalAgent } from '@/services/externalAgents'

export const useExternalAgentStore = defineStore('externalAgents', () => {
  const agents = ref<ExternalAgent[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchAgents() {
    loading.value = true
    error.value = null
    try {
      agents.value = await externalAgentApi.list()
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '加载 Agent 列表失败'
    } finally {
      loading.value = false
    }
  }

  return { agents, loading, error, fetchAgents }
})
