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
