<script setup lang="ts">
import { ref, watch } from 'vue'
import { Database, Plus, Trash2, Loader2, CheckCircle, XCircle } from 'lucide-vue-next'
import { instanceKbApi, kbApi } from '@/services/skills'
import type { InstanceKnowledgeBase, KnowledgeBase } from '@/services/skills'
import { useToast } from '@/composables/useToast'
import KbSyncStatus from '@/components/skills/KbSyncStatus.vue'

const props = defineProps<{
  instanceId: string
  canEdit: boolean
}>()

const toast = useToast()
const loading = ref(false)
const attaching = ref(false)
const bindings = ref<InstanceKnowledgeBase[]>([])

// 选择器弹窗状态
const showSelector = ref(false)
const availableKbs = ref<KnowledgeBase[]>([])
const selectorLoading = ref(false)

async function fetchBindings() {
  loading.value = true
  try {
    bindings.value = await instanceKbApi.list(props.instanceId)
  } finally {
    loading.value = false
  }
}

async function openSelector() {
  showSelector.value = true
  selectorLoading.value = true
  try {
    const all = await kbApi.list()
    const attachedIds = new Set(bindings.value.map(b => b.kb_id))
    // 只显示已 sync 验证通过且未绑定的知识库
    availableKbs.value = all.filter(kb => kb.is_reachable && !attachedIds.has(kb.id))
  } finally {
    selectorLoading.value = false
  }
}

async function attachKb(kb: KnowledgeBase) {
  attaching.value = true
  try {
    const binding = await instanceKbApi.attach(props.instanceId, kb.id)
    bindings.value = [binding, ...bindings.value]
    availableKbs.value = availableKbs.value.filter(k => k.id !== kb.id)
    toast.success(`已绑定知识库「${kb.name}」`)
    if (availableKbs.value.length === 0) showSelector.value = false
  } catch (e: unknown) {
    const msg = (e as { response?: { data?: { message?: string } } })?.response?.data?.message || '绑定失败'
    toast.error(msg)
  } finally {
    attaching.value = false
  }
}

async function detachKb(binding: InstanceKnowledgeBase) {
  try {
    await instanceKbApi.detach(props.instanceId, binding.kb_id)
    bindings.value = bindings.value.filter(b => b.id !== binding.id)
    toast.success(`已移除知识库「${binding.kb.name}」`)
  } catch (e: unknown) {
    const msg = (e as { response?: { data?: { message?: string } } })?.response?.data?.message || '移除失败'
    toast.error(msg)
  }
}

watch(() => props.instanceId, (val) => {
  if (val) fetchBindings()
}, { immediate: true })
</script>

<template>
  <div class="p-3 rounded-lg border border-border bg-card space-y-2">
    <!-- 标题行 -->
    <div class="flex items-center justify-between">
      <div class="flex items-center gap-1.5">
        <Database class="w-3.5 h-3.5 text-muted-foreground" />
        <h4 class="text-xs font-medium text-muted-foreground">外挂知识库</h4>
      </div>
      <button
        v-if="canEdit"
        class="flex items-center gap-1 px-2 py-1 rounded-md text-xs text-primary hover:bg-primary/10 transition-colors"
        @click="openSelector"
      >
        <Plus class="w-3 h-3" />
        添加
      </button>
    </div>

    <!-- 加载中 -->
    <div v-if="loading" class="flex items-center justify-center py-4">
      <Loader2 class="w-4 h-4 animate-spin text-muted-foreground" />
    </div>

    <!-- 空状态 -->
    <div v-else-if="bindings.length === 0" class="py-3 text-center">
      <Database class="w-5 h-5 mx-auto mb-1 text-muted-foreground/40" />
      <p class="text-xs text-muted-foreground">暂无外挂知识库</p>
    </div>

    <!-- 绑定列表 -->
    <div v-else class="space-y-1.5">
      <div
        v-for="binding in bindings"
        :key="binding.id"
        class="flex items-center justify-between p-2 rounded-md bg-muted/30"
      >
        <div class="flex items-center gap-2 min-w-0">
          <CheckCircle class="w-3.5 h-3.5 text-green-500 shrink-0" />
          <span class="text-xs font-medium truncate">{{ binding.kb.name }}</span>
          <KbSyncStatus :source-type="binding.kb.source_type" />
        </div>
        <button
          v-if="canEdit"
          class="ml-2 p-1 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors shrink-0"
          @click="detachKb(binding)"
        >
          <Trash2 class="w-3 h-3" />
        </button>
      </div>
    </div>

    <!-- 选择器弹窗 -->
    <Teleport to="body">
      <div v-if="showSelector" class="fixed inset-0 z-50 flex items-center justify-center">
        <div class="absolute inset-0 bg-black/40" @click="showSelector = false" />
        <div class="relative bg-card border border-border rounded-xl p-5 w-full max-w-sm shadow-xl space-y-3">
          <div class="flex items-center justify-between">
            <h3 class="text-sm font-semibold">选择知识库</h3>
            <button class="p-1 rounded hover:bg-muted transition-colors" @click="showSelector = false">
              <XCircle class="w-4 h-4 text-muted-foreground" />
            </button>
          </div>

          <div v-if="selectorLoading" class="flex items-center justify-center py-6">
            <Loader2 class="w-5 h-5 animate-spin text-muted-foreground" />
          </div>
          <div v-else-if="availableKbs.length === 0" class="py-6 text-center">
            <p class="text-xs text-muted-foreground">没有可用的已连接知识库</p>
            <p class="text-[10px] text-muted-foreground/70 mt-1">请先在知识库管理页完成连接验证（Sync）</p>
          </div>
          <div v-else class="space-y-1.5 max-h-60 overflow-y-auto">
            <button
              v-for="kb in availableKbs"
              :key="kb.id"
              class="w-full flex items-center justify-between p-2.5 rounded-lg border border-border hover:border-primary/50 hover:bg-primary/5 transition-colors text-left"
              :disabled="attaching"
              @click="attachKb(kb)"
            >
              <div class="flex items-center gap-2 min-w-0">
                <Database class="w-3.5 h-3.5 text-primary shrink-0" />
                <span class="text-xs font-medium truncate">{{ kb.name }}</span>
                <KbSyncStatus :source-type="kb.source_type" />
              </div>
              <Plus class="w-3.5 h-3.5 text-primary shrink-0 ml-2" />
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
