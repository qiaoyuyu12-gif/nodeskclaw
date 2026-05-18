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
