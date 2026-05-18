<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Brain, Upload, Trash2, ToggleLeft, ToggleRight, FileArchive, CheckCircle2, AlertCircle } from 'lucide-vue-next'
import { useSkillStore } from '@/stores/skills'
import { skillApi } from '@/services/skills'

const skillStore = useSkillStore()
const showUpload = ref(false)
const uploading = ref(false)
const uploadError = ref<string | null>(null)
const uploadSuccess = ref<string | null>(null)
const dragOver = ref(false)
const fileInputRef = ref<HTMLInputElement>()

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

async function handleFile(file: File) {
  if (!file.name.endsWith('.zip')) {
    uploadError.value = '请上传 .zip 格式的技能包'
    return
  }
  uploading.value = true
  uploadError.value = null
  uploadSuccess.value = null
  try {
    const skill = await skillApi.upload(file)
    uploadSuccess.value = `技能「${skill.name}」上传成功`
    showUpload.value = false
    await skillStore.fetchSkills()
  } catch (e: unknown) {
    uploadError.value = e instanceof Error ? e.message : '上传失败，请检查 skill.md 格式'
  } finally {
    uploading.value = false
  }
}

function onFileInput(e: Event) {
  const input = e.target as HTMLInputElement
  if (input.files?.[0]) handleFile(input.files[0])
}

function onDrop(e: DragEvent) {
  dragOver.value = false
  const file = e.dataTransfer?.files?.[0]
  if (file) handleFile(file)
}

const typeLabel: Record<string, string> = { rag_query: '知识库问答', gene: 'Gene 技能', composite: '复合技能' }
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
        @click="showUpload = !showUpload; uploadError = null; uploadSuccess = null"
      >
        <Upload class="w-4 h-4" />
        上传技能包
      </button>
    </div>

    <!-- Upload zone -->
    <div v-if="showUpload" class="mb-6 rounded-xl border-2 border-dashed border-blue-300 bg-blue-50 p-6">
      <div
        class="flex flex-col items-center gap-3 py-4 rounded-lg transition-colors"
        :class="dragOver ? 'bg-blue-100' : ''"
        @dragover.prevent="dragOver = true"
        @dragleave.prevent="dragOver = false"
        @drop.prevent="onDrop"
      >
        <FileArchive class="w-10 h-10 text-blue-400" />
        <p class="text-sm text-gray-600 text-center">
          将 <span class="font-medium">.zip 技能包</span> 拖拽到此处，或
          <button
            class="text-blue-600 underline underline-offset-2 hover:text-blue-700"
            @click="fileInputRef?.click()"
          >
            点击选择文件
          </button>
        </p>
        <p class="text-xs text-gray-400 text-center">
          ZIP 包须包含 <code class="bg-white px-1 rounded">skill.md</code>（YAML frontmatter 声明 name / type / kb_id）
        </p>
        <input ref="fileInputRef" type="file" accept=".zip" class="hidden" @change="onFileInput" />
      </div>

      <div v-if="uploading" class="mt-4 flex items-center gap-2 text-sm text-blue-600">
        <span class="animate-spin inline-block w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full" />
        上传解析中...
      </div>
      <div v-if="uploadError" class="mt-4 flex items-start gap-2 rounded-lg bg-red-50 border border-red-200 px-4 py-3">
        <AlertCircle class="w-4 h-4 text-red-500 mt-0.5 shrink-0" />
        <p class="text-sm text-red-700">{{ uploadError }}</p>
      </div>

      <!-- skill.md format hint -->
      <div class="mt-4 rounded-lg bg-white border border-gray-200 p-4">
        <p class="text-xs font-medium text-gray-600 mb-2">skill.md 格式示例：</p>
        <pre class="text-xs text-gray-500 font-mono leading-relaxed">---
name: 产品文档问答
type: rag_query
kb_id: &lt;知识库UUID&gt;
config:
  top_k: 5
---

（可选）Markdown 格式的技能说明...</pre>
      </div>
    </div>

    <!-- Success toast -->
    <div
      v-if="uploadSuccess"
      class="mb-4 flex items-center gap-2 rounded-lg bg-green-50 border border-green-200 px-4 py-3"
    >
      <CheckCircle2 class="w-4 h-4 text-green-500 shrink-0" />
      <p class="text-sm text-green-700">{{ uploadSuccess }}</p>
    </div>

    <div v-if="skillStore.loading" class="text-sm text-gray-400 text-center py-16">加载中...</div>
    <div v-else-if="skillStore.skills.length === 0" class="text-sm text-gray-400 text-center py-16">
      还没有技能定义，点击「上传技能包」开始
    </div>
    <div v-else class="space-y-3">
      <div
        v-for="skill in skillStore.skills"
        :key="skill.id"
        class="flex items-center justify-between rounded-xl border border-gray-200 bg-white px-5 py-4"
      >
        <div class="flex items-center gap-4 min-w-0">
          <Brain class="w-5 h-5 text-gray-400 shrink-0" />
          <div class="min-w-0">
            <p class="font-medium text-gray-900 text-sm">{{ skill.name }}</p>
            <p class="text-xs text-gray-400 mt-0.5">{{ typeLabel[skill.type] }}</p>
            <p v-if="skill.description" class="text-xs text-gray-500 mt-1 truncate max-w-xs">
              {{ skill.description }}
            </p>
          </div>
          <span
            class="shrink-0 rounded-full px-2 py-0.5 text-xs"
            :class="skill.enabled ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'"
          >
            {{ skill.enabled ? '启用' : '停用' }}
          </span>
        </div>
        <div class="flex items-center gap-1 shrink-0">
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
