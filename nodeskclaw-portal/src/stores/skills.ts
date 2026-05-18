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
