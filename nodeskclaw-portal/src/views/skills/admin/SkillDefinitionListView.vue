<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  Brain, Upload, Trash2, ToggleLeft, ToggleRight,
  FileArchive, FolderOpen, CheckCircle2, AlertCircle, Code2,
} from 'lucide-vue-next'
import { useSkillStore } from '@/stores/skills'
import { skillApi, type Skill } from '@/services/skills'

const skillStore = useSkillStore()

// ── ZIP 上传相关状态 ─────────────────────────────────────────
const showZipUpload = ref(false)
const zipUploading = ref(false)
const zipError = ref<string | null>(null)
const zipSuccess = ref<string | null>(null)
const zipDragOver = ref(false)
const zipFileInputRef = ref<HTMLInputElement>()

// ── 文件夹上传相关状态 ────────────────────────────────────────
const showFolderUpload = ref(false)
const folderUploading = ref(false)
const folderError = ref<string | null>(null)
const folderSuccess = ref<string | null>(null)
const folderFileInputRef = ref<HTMLInputElement>()

// 当前选中文件夹的文件列表（供预览展示）
const selectedFolderFiles = ref<string[]>([])

onMounted(() => skillStore.fetchSkills())

// ── 技能类型标签映射 ──────────────────────────────────────────
const typeLabel: Record<string, string> = {
  rag_query: '知识库问答',
  gene: 'Gene 技能',
  composite: '复合技能',
  tool: 'Python 工具',   // 文件夹上传的新类型
}

// ── 通用操作 ─────────────────────────────────────────────────

/** 切换技能启用/停用状态 */
async function toggleEnabled(skillId: string, current: boolean) {
  await skillApi.update(skillId, { enabled: !current })
  await skillStore.fetchSkills()
}

/** 删除技能（软删除） */
async function remove(id: string) {
  if (!confirm('确定删除该技能？')) return
  await skillApi.remove(id)
  await skillStore.fetchSkills()
}

// ── ZIP 上传 ──────────────────────────────────────────────────

/** 处理 ZIP 文件上传 */
async function handleZipFile(file: File) {
  if (!file.name.endsWith('.zip')) {
    zipError.value = '请上传 .zip 格式的技能包'
    return
  }
  zipUploading.value = true
  zipError.value = null
  zipSuccess.value = null
  try {
    const skill = await skillApi.upload(file)
    zipSuccess.value = `技能「${skill.name}」上传成功`
    showZipUpload.value = false
    await skillStore.fetchSkills()
  } catch (e: unknown) {
    zipError.value = e instanceof Error ? e.message : '上传失败，请检查 skill.md 格式'
  } finally {
    zipUploading.value = false
  }
}

function onZipFileInput(e: Event) {
  const input = e.target as HTMLInputElement
  if (input.files?.[0]) handleZipFile(input.files[0])
}

function onZipDrop(e: DragEvent) {
  zipDragOver.value = false
  const file = e.dataTransfer?.files?.[0]
  if (file) handleZipFile(file)
}

// ── 文件夹上传 ────────────────────────────────────────────────

/**
 * 文件夹选择后的预览：显示文件列表，等待用户点击确认上传。
 * webkitdirectory input 触发后进入此函数。
 */
function onFolderInput(e: Event) {
  const input = e.target as HTMLInputElement
  if (!input.files || input.files.length === 0) return

  // 展示选中的文件相对路径（预览用）
  selectedFolderFiles.value = Array.from(input.files).map(
    (f) => (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name
  )
}

/** 确认并执行文件夹上传 */
async function submitFolderUpload() {
  const input = folderFileInputRef.value
  if (!input?.files || input.files.length === 0) {
    folderError.value = '请先选择技能文件夹'
    return
  }

  folderUploading.value = true
  folderError.value = null
  folderSuccess.value = null
  try {
    // 调用 uploadFolder：将所有文件以 multipart 形式发送到 /upload-folder
    const skill = await skillApi.uploadFolder(input.files)
    folderSuccess.value = `技能「${skill.name}」上传成功`
    showFolderUpload.value = false
    selectedFolderFiles.value = []
    await skillStore.fetchSkills()
  } catch (e: unknown) {
    folderError.value = e instanceof Error ? e.message : '上传失败，请检查 skill.md 格式'
  } finally {
    folderUploading.value = false
  }
}

/** 判断文件是否为入口脚本（高亮显示） */
function isEntryScript(path: string, skills: Skill[]): boolean {
  return path.endsWith('.py') && !path.includes('/')
}
</script>

<template>
  <div class="max-w-5xl mx-auto px-6 py-8">
    <!-- 页面标题和操作按钮 -->
    <div class="flex items-center justify-between mb-6">
      <div class="flex items-center gap-3">
        <Brain class="w-6 h-6 text-blue-500" />
        <h1 class="text-xl font-semibold text-gray-900">技能定义</h1>
      </div>
      <div class="flex items-center gap-2">
        <!-- ZIP 压缩包上传按钮 -->
        <button
          class="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
          @click="showZipUpload = !showZipUpload; showFolderUpload = false; zipError = null"
        >
          <FileArchive class="w-4 h-4" />
          ZIP 包上传
        </button>
        <!-- 文件夹上传按钮 -->
        <button
          class="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          @click="showFolderUpload = !showFolderUpload; showZipUpload = false; folderError = null"
        >
          <FolderOpen class="w-4 h-4" />
          上传文件夹
        </button>
      </div>
    </div>

    <!-- ── ZIP 上传区域 ── -->
    <div v-if="showZipUpload" class="mb-6 rounded-xl border-2 border-dashed border-gray-300 bg-gray-50 p-6">
      <div
        class="flex flex-col items-center gap-3 py-4 rounded-lg transition-colors"
        :class="zipDragOver ? 'bg-gray-100' : ''"
        @dragover.prevent="zipDragOver = true"
        @dragleave.prevent="zipDragOver = false"
        @drop.prevent="onZipDrop"
      >
        <FileArchive class="w-10 h-10 text-gray-400" />
        <p class="text-sm text-gray-600 text-center">
          将 <span class="font-medium">.zip 技能包</span> 拖拽到此处，或
          <button
            class="text-blue-600 underline underline-offset-2 hover:text-blue-700"
            @click="zipFileInputRef?.click()"
          >
            点击选择文件
          </button>
        </p>
        <p class="text-xs text-gray-400 text-center">
          ZIP 包须包含 <code class="bg-white px-1 rounded">skill.md</code>
        </p>
        <input ref="zipFileInputRef" type="file" accept=".zip" class="hidden" @change="onZipFileInput" />
      </div>
      <div v-if="zipUploading" class="mt-4 flex items-center gap-2 text-sm text-blue-600">
        <span class="animate-spin inline-block w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full" />
        上传解析中...
      </div>
      <div v-if="zipError" class="mt-4 flex items-start gap-2 rounded-lg bg-red-50 border border-red-200 px-4 py-3">
        <AlertCircle class="w-4 h-4 text-red-500 mt-0.5 shrink-0" />
        <p class="text-sm text-red-700">{{ zipError }}</p>
      </div>
    </div>

    <!-- ── 文件夹上传区域 ── -->
    <div v-if="showFolderUpload" class="mb-6 rounded-xl border-2 border-dashed border-blue-300 bg-blue-50 p-6">
      <div class="flex flex-col items-center gap-3">
        <FolderOpen class="w-10 h-10 text-blue-400" />
        <p class="text-sm text-gray-700 text-center font-medium">上传 Skill 文件夹</p>
        <p class="text-xs text-gray-500 text-center max-w-md">
          文件夹内须包含 <code class="bg-white px-1 rounded">skill.md</code>（声明 name/type），
          其余文件（Python 脚本、<code class="bg-white px-1 rounded">assets/</code>、
          <code class="bg-white px-1 rounded">reference/</code> 等）按需保留。
          上传后所有内容内联为 JSON 供 agent 命中。
        </p>
        <!-- webkitdirectory 输入：选择整个文件夹 -->
        <input
          ref="folderFileInputRef"
          type="file"
          class="hidden"
          webkitdirectory
          multiple
          @change="onFolderInput"
        />
        <button
          class="inline-flex items-center gap-2 rounded-lg border border-blue-300 bg-white px-4 py-2 text-sm text-blue-700 hover:bg-blue-50"
          @click="folderFileInputRef?.click()"
        >
          <FolderOpen class="w-4 h-4" />
          选择文件夹
        </button>
      </div>

      <!-- 已选文件预览列表 -->
      <div v-if="selectedFolderFiles.length > 0" class="mt-4">
        <p class="text-xs font-medium text-gray-600 mb-2">
          已选 {{ selectedFolderFiles.length }} 个文件：
        </p>
        <ul class="max-h-40 overflow-y-auto rounded-lg bg-white border border-gray-200 divide-y divide-gray-100">
          <li
            v-for="path in selectedFolderFiles"
            :key="path"
            class="flex items-center gap-2 px-3 py-1.5 text-xs"
          >
            <!-- 脚本文件用代码图标高亮 -->
            <Code2 v-if="path.endsWith('.py')" class="w-3 h-3 text-blue-500 shrink-0" />
            <FolderOpen v-else-if="path.includes('/')" class="w-3 h-3 text-gray-400 shrink-0" />
            <span v-else class="w-3 h-3 shrink-0" />
            <span :class="path.endsWith('skill.md') ? 'font-medium text-blue-700' : 'text-gray-600'">
              {{ path }}
            </span>
          </li>
        </ul>

        <!-- 确认上传按钮 -->
        <div class="mt-3 flex justify-end">
          <button
            :disabled="folderUploading"
            class="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            @click="submitFolderUpload"
          >
            <span
              v-if="folderUploading"
              class="animate-spin inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full"
            />
            <Upload v-else class="w-4 h-4" />
            {{ folderUploading ? '上传中...' : '确认上传' }}
          </button>
        </div>
      </div>

      <!-- skill.md 格式说明 -->
      <div class="mt-4 rounded-lg bg-white border border-gray-200 p-4">
        <p class="text-xs font-medium text-gray-600 mb-2">skill.md 格式（type=tool 示例）：</p>
        <pre class="text-xs text-gray-500 font-mono leading-relaxed">---
name: 数据分析工具
type: tool
config:
  entry: main.py
  input_schema:
    type: object
    properties:
      query:
        type: string
---

工具描述（Markdown）...</pre>
      </div>

      <div v-if="folderError" class="mt-4 flex items-start gap-2 rounded-lg bg-red-50 border border-red-200 px-4 py-3">
        <AlertCircle class="w-4 h-4 text-red-500 mt-0.5 shrink-0" />
        <p class="text-sm text-red-700">{{ folderError }}</p>
      </div>
    </div>

    <!-- 成功提示 -->
    <div
      v-if="zipSuccess || folderSuccess"
      class="mb-4 flex items-center gap-2 rounded-lg bg-green-50 border border-green-200 px-4 py-3"
    >
      <CheckCircle2 class="w-4 h-4 text-green-500 shrink-0" />
      <p class="text-sm text-green-700">{{ zipSuccess || folderSuccess }}</p>
    </div>

    <!-- 技能列表 -->
    <div v-if="skillStore.loading" class="text-sm text-gray-400 text-center py-16">加载中...</div>
    <div v-else-if="skillStore.skills.length === 0" class="text-sm text-gray-400 text-center py-16">
      还没有技能定义，点击「上传文件夹」或「ZIP 包上传」开始
    </div>
    <div v-else class="space-y-3">
      <div
        v-for="skill in skillStore.skills"
        :key="skill.id"
        class="flex items-center justify-between rounded-xl border border-gray-200 bg-white px-5 py-4"
      >
        <div class="flex items-center gap-4 min-w-0">
          <!-- tool 类型用代码图标区分 -->
          <Code2 v-if="skill.type === 'tool'" class="w-5 h-5 text-blue-500 shrink-0" />
          <Brain v-else class="w-5 h-5 text-gray-400 shrink-0" />
          <div class="min-w-0">
            <p class="font-medium text-gray-900 text-sm">{{ skill.name }}</p>
            <p class="text-xs text-gray-400 mt-0.5">{{ typeLabel[skill.type] ?? skill.type }}</p>
            <p v-if="skill.description" class="text-xs text-gray-500 mt-1 truncate max-w-xs">
              {{ skill.description }}
            </p>
            <!-- tool 类型显示入口脚本 -->
            <p v-if="skill.type === 'tool' && skill.manifest?.entry" class="text-xs text-blue-500 mt-0.5">
              入口：{{ skill.manifest.entry }}
              <span v-if="skill.manifest.scripts" class="ml-1 text-gray-400">
                （{{ Object.keys(skill.manifest.scripts).length }} 个脚本）
              </span>
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
