<script setup lang="ts">
import { ref, watch } from 'vue'
import {
  X,
  FileText,
  Loader2,
  AlertCircle,
  CheckCircle2,
  Clock,
  XCircle,
  ChevronLeft,
  ChevronRight,
} from 'lucide-vue-next'
import { kbApi } from '@/services/skills'
import type { KnowledgeBase, KbDocument } from '@/services/skills'
import { resolveApiErrorMessage } from '@/i18n/error'

const props = defineProps<{
  kb: KnowledgeBase | null
}>()

const emit = defineEmits<{
  close: []
}>()

const loading = ref(false)
const error = ref<string | null>(null)
const docs = ref<KbDocument[]>([])
const total = ref(0)
const page = ref(1)
const PAGE_SIZE = 30

// 解析运行状态文字和样式
function runStatus(doc: KbDocument) {
  const run = doc.run ?? '0'
  switch (run) {
    case '1': return { label: '解析中', color: 'text-blue-600 bg-blue-50', icon: 'running' }
    case '2': return { label: '已完成', color: 'text-green-600 bg-green-50', icon: 'done' }
    case '3': return { label: '失败', color: 'text-red-600 bg-red-50', icon: 'fail' }
    default:  return { label: '未开始', color: 'text-gray-500 bg-gray-100', icon: 'idle' }
  }
}

// 格式化文件大小
function formatSize(bytes?: number): string {
  if (!bytes) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

// 分片数取兼容字段
function chunkCount(doc: KbDocument): number | string {
  return doc.chunk_num ?? doc.chunk_count ?? '-'
}

async function load() {
  if (!props.kb) return
  loading.value = true
  error.value = null
  try {
    const result = await kbApi.documents(props.kb.id, page.value, PAGE_SIZE)
    docs.value = result.docs ?? []
    total.value = result.total ?? 0
  } catch (e) {
    error.value = resolveApiErrorMessage(e, '加载文档列表失败，请确认知识库连接正常')
  } finally {
    loading.value = false
  }
}

function prevPage() {
  if (page.value > 1) { page.value--; load() }
}
function nextPage() {
  if (page.value * PAGE_SIZE < total.value) { page.value++; load() }
}

// kb 变化时重置并加载
watch(
  () => props.kb,
  (kb) => {
    if (kb) { page.value = 1; load() }
    else { docs.value = []; total.value = 0 }
  },
  { immediate: true },
)
</script>

<template>
  <Teleport to="body">
    <!-- 遮罩 -->
    <Transition name="fade">
      <div
        v-if="kb"
        class="fixed inset-0 z-40 bg-black/30"
        @click="emit('close')"
      />
    </Transition>

    <!-- 右侧 drawer -->
    <Transition name="slide">
      <div
        v-if="kb"
        class="fixed top-0 right-0 z-50 h-full w-full max-w-md bg-card border-l border-border shadow-2xl flex flex-col"
      >
        <!-- 头部 -->
        <div class="flex items-center justify-between px-5 py-4 border-b border-border shrink-0">
          <div class="flex items-center gap-2 min-w-0">
            <FileText class="w-4 h-4 text-primary shrink-0" />
            <span class="font-semibold text-sm text-foreground truncate">{{ kb.name }}</span>
          </div>
          <button
            class="p-1.5 rounded-md text-muted-foreground hover:bg-muted transition-colors"
            @click="emit('close')"
          >
            <X class="w-4 h-4" />
          </button>
        </div>

        <!-- 内容区 -->
        <div class="flex-1 overflow-y-auto">
          <!-- 加载中 -->
          <div v-if="loading" class="flex items-center justify-center h-40">
            <Loader2 class="w-5 h-5 animate-spin text-muted-foreground" />
          </div>

          <!-- 错误 -->
          <div v-else-if="error" class="flex flex-col items-center justify-center h-40 gap-2 px-6 text-center">
            <AlertCircle class="w-6 h-6 text-destructive" />
            <p class="text-sm text-destructive">{{ error }}</p>
          </div>

          <!-- 空文档 -->
          <div v-else-if="docs.length === 0" class="flex flex-col items-center justify-center h-40 gap-2">
            <FileText class="w-6 h-6 text-muted-foreground/40" />
            <p class="text-sm text-muted-foreground">该知识库暂无文档</p>
          </div>

          <!-- 文档列表 -->
          <ul v-else class="divide-y divide-border">
            <li
              v-for="doc in docs"
              :key="doc.id"
              class="flex items-center gap-3 px-5 py-3 hover:bg-muted/40 transition-colors"
            >
              <FileText class="w-4 h-4 text-muted-foreground shrink-0" />
              <div class="flex-1 min-w-0">
                <p class="text-sm text-foreground truncate">{{ doc.name }}</p>
                <p class="text-xs text-muted-foreground mt-0.5">
                  {{ formatSize(doc.size) }}
                  <span v-if="chunkCount(doc) !== '-'" class="ml-2">· {{ chunkCount(doc) }} 分片</span>
                </p>
              </div>
              <!-- 解析状态 -->
              <span
                class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium shrink-0"
                :class="runStatus(doc).color"
              >
                <Loader2
                  v-if="runStatus(doc).icon === 'running'"
                  class="w-2.5 h-2.5 animate-spin"
                />
                <CheckCircle2 v-else-if="runStatus(doc).icon === 'done'" class="w-2.5 h-2.5" />
                <XCircle v-else-if="runStatus(doc).icon === 'fail'" class="w-2.5 h-2.5" />
                <Clock v-else class="w-2.5 h-2.5" />
                {{ runStatus(doc).label }}
              </span>
            </li>
          </ul>
        </div>

        <!-- 底部分页 -->
        <div
          v-if="total > PAGE_SIZE"
          class="flex items-center justify-between px-5 py-3 border-t border-border shrink-0 text-xs text-muted-foreground"
        >
          <span>共 {{ total }} 个文档</span>
          <div class="flex items-center gap-1">
            <button
              class="p-1 rounded hover:bg-muted disabled:opacity-40"
              :disabled="page === 1"
              @click="prevPage"
            >
              <ChevronLeft class="w-4 h-4" />
            </button>
            <span class="px-2">{{ page }} / {{ Math.ceil(total / PAGE_SIZE) }}</span>
            <button
              class="p-1 rounded hover:bg-muted disabled:opacity-40"
              :disabled="page * PAGE_SIZE >= total"
              @click="nextPage"
            >
              <ChevronRight class="w-4 h-4" />
            </button>
          </div>
        </div>
        <!-- 总数（无需分页时） -->
        <div
          v-else-if="total > 0"
          class="px-5 py-3 border-t border-border shrink-0 text-xs text-muted-foreground"
        >
          共 {{ total }} 个文档
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
/* 遮罩淡入淡出 */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* drawer 从右侧滑入 */
.slide-enter-active,
.slide-leave-active {
  transition: transform 0.25s ease;
}
.slide-enter-from,
.slide-leave-to {
  transform: translateX(100%);
}
</style>
