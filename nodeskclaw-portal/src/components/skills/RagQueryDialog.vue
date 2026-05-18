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
      <div class="flex items-center justify-between px-6 py-4 border-b">
        <div class="flex items-center gap-2">
          <MessageSquare class="w-5 h-5 text-blue-500" />
          <span class="font-semibold text-gray-900">{{ skillName }}</span>
        </div>
        <button class="text-gray-400 hover:text-gray-600" @click="emit('close')">
          <X class="w-5 h-5" />
        </button>
      </div>

      <div class="flex-1 overflow-y-auto px-6 py-4 space-y-3">
        <div v-if="!result && !loading" class="text-sm text-gray-400 text-center py-8">
          输入问题开始检索知识库
        </div>
        <div v-if="loading" class="text-sm text-gray-400 text-center py-8">检索中...</div>

        <div
          v-if="result?.degraded"
          class="flex items-start gap-2 rounded-lg bg-amber-50 border border-amber-200 px-4 py-3"
        >
          <AlertTriangle class="w-4 h-4 text-amber-500 mt-0.5 shrink-0" />
          <p class="text-sm text-amber-800">{{ result.message }}</p>
        </div>

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
