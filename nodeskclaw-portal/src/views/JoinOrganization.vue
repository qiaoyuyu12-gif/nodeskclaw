<!--
  申请加入组织
  ----------
  - 仅 multi_org feature 启用时可访问（route meta 检查 + 后端二次校验）
  - 已加入组织的用户也能从其他入口进来申请加入"其他组织"
  - 表单：组织标识（可搜索下拉，列出所有已注册组织）+ 申请理由（可选）
  - 提交成功后展示状态卡片 + 列出我的全部申请历史
-->
<template>
  <div class="max-w-2xl mx-auto p-6 space-y-6">
    <!-- 页头 -->
    <div class="space-y-1">
      <h1 class="text-2xl font-semibold flex items-center gap-2">
        <UserPlus class="w-6 h-6" />
        {{ t('joinOrg.title') }}
      </h1>
      <p class="text-sm text-muted-foreground">{{ t('joinOrg.subtitle') }}</p>
    </div>

    <!-- 申请表单 -->
    <div class="border rounded-lg p-5 space-y-4 bg-card">
      <!-- 组织选择下拉（可搜索） -->
      <div class="space-y-1" ref="orgPickerRef">
        <label class="text-sm font-medium">{{ t('joinOrg.slugLabel') }}</label>
        <div class="relative">
          <!-- 搜索输入框 -->
          <input
            ref="orgInputRef"
            v-model="orgSearch"
            :placeholder="selectedOrg ? `${selectedOrg.name} (${selectedOrg.slug})` : t('joinOrg.slugPlaceholder')"
            :disabled="submitting || loadingOrgs"
            class="w-full border rounded px-3 py-2 text-sm bg-background pr-8"
            autocomplete="off"
            @focus="openPicker"
            @input="openPicker"
            @keydown.escape="closePicker"
            @keydown.enter.prevent="selectHighlighted"
            @keydown.arrow-down.prevent="moveHighlight(1)"
            @keydown.arrow-up.prevent="moveHighlight(-1)"
          />
          <!-- 清除按钮 -->
          <button
            v-if="selectedOrg"
            class="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            tabindex="-1"
            @mousedown.prevent="clearSelection"
          >
            <X class="w-3.5 h-3.5" />
          </button>
          <!-- 加载指示 -->
          <Loader2
            v-else-if="loadingOrgs"
            class="absolute right-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 animate-spin text-muted-foreground"
          />

          <!-- 下拉面板 -->
          <div
            v-if="pickerOpen && !loadingOrgs"
            class="absolute z-50 left-0 right-0 top-full mt-1 max-h-56 overflow-y-auto rounded-md border border-border bg-card shadow-lg"
          >
            <div
              v-if="filteredOrgs.length === 0"
              class="px-3 py-2 text-xs text-muted-foreground"
            >
              {{ t('joinOrg.slugNoMatch') }}
            </div>
            <button
              v-for="(org, idx) in filteredOrgs"
              :key="org.id"
              type="button"
              :class="[
                'w-full text-left px-3 py-2 text-sm flex items-center justify-between gap-2 transition-colors',
                idx === highlightIdx
                  ? 'bg-primary/10 text-primary'
                  : 'hover:bg-muted/50',
              ]"
              @mouseenter="highlightIdx = idx"
              @mousedown.prevent="selectOrg(org)"
            >
              <span class="font-medium truncate">{{ org.name }}</span>
              <span class="shrink-0 text-xs text-muted-foreground font-mono">{{ org.slug }}</span>
            </button>
          </div>
        </div>
        <p class="text-xs text-muted-foreground">{{ t('joinOrg.slugHint') }}</p>
      </div>

      <div class="space-y-1">
        <label class="text-sm font-medium">{{ t('joinOrg.reasonLabel') }}</label>
        <textarea
          v-model="form.reason"
          :placeholder="t('joinOrg.reasonPlaceholder')"
          :disabled="submitting"
          rows="3"
          maxlength="500"
          class="w-full border rounded px-3 py-2 text-sm bg-background resize-none"
        />
      </div>

      <button
        :disabled="!canSubmit || submitting"
        class="inline-flex items-center gap-2 px-4 py-2 text-sm rounded bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50"
        @click="onSubmit"
      >
        <Loader2 v-if="submitting" class="w-4 h-4 animate-spin" />
        {{ t('joinOrg.submit') }}
      </button>
    </div>

    <!-- 我的申请历史 -->
    <div class="space-y-3">
      <h2 class="text-base font-semibold">{{ t('joinOrg.historyTitle') }}</h2>
      <div v-if="loadingHistory" class="text-center py-8 text-sm text-muted-foreground">
        {{ t('common.loading') }}
      </div>
      <div
        v-else-if="myRequests.length === 0"
        class="text-center py-8 text-sm text-muted-foreground border border-dashed rounded-lg"
      >
        {{ t('joinOrg.historyEmpty') }}
      </div>
      <ul v-else class="space-y-2">
        <li
          v-for="req in myRequests"
          :key="req.id"
          class="border rounded-lg p-3 flex items-center justify-between gap-3 bg-card"
        >
          <div class="min-w-0 flex-1">
            <div class="text-sm font-medium truncate">
              {{ req.org_name || req.org_slug || req.org_id }}
            </div>
            <div class="text-xs text-muted-foreground">
              {{ formatDate(req.created_at) }} · {{ statusLabel(req.status) }}
              <span v-if="req.review_note" class="ml-2">— {{ req.review_note }}</span>
            </div>
          </div>
          <button
            v-if="req.status === 'pending'"
            class="text-xs text-red-600 hover:underline"
            :disabled="cancellingId === req.id"
            @click="onCancel(req.id)"
          >
            {{ t('joinOrg.cancel') }}
          </button>
        </li>
      </ul>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, reactive } from 'vue'
import { useI18n } from 'vue-i18n'
import { UserPlus, Loader2, X } from 'lucide-vue-next'
import { useToast } from '@/composables/useToast'
import { resolveApiErrorMessage } from '@/i18n/error'
import {
  submitJoinRequest,
  listMyJoinRequests,
  cancelMyJoinRequest,
  listOrgDirectory,
  type JoinRequestInfo,
  type JoinRequestStatus,
  type OrgDirectoryItem,
} from '@/services/orgJoinApi'

const { t, locale } = useI18n()
const toast = useToast()

// ── 组织下拉选择 ────────────────────────────────────────────

const orgPickerRef = ref<HTMLElement | null>(null)
const orgInputRef = ref<HTMLInputElement | null>(null)
const allOrgs = ref<OrgDirectoryItem[]>([])
const loadingOrgs = ref(false)
const orgSearch = ref('')
const selectedOrg = ref<OrgDirectoryItem | null>(null)
const pickerOpen = ref(false)
const highlightIdx = ref(0)

// 按搜索词过滤：匹配 name 或 slug（忽略大小写）
const filteredOrgs = computed(() => {
  const q = orgSearch.value.trim().toLowerCase()
  if (!q) return allOrgs.value
  return allOrgs.value.filter(
    o => o.name.toLowerCase().includes(q) || o.slug.toLowerCase().includes(q),
  )
})

async function loadOrgs() {
  loadingOrgs.value = true
  try {
    allOrgs.value = await listOrgDirectory()
  } catch {
    toast.error(t('joinOrg.slugLoadFailed'))
  } finally {
    loadingOrgs.value = false
  }
}

function openPicker() {
  pickerOpen.value = true
  highlightIdx.value = 0
}

function closePicker() {
  pickerOpen.value = false
  // 关闭时若没有有效选中，清空搜索框以还原 placeholder 显示
  if (!selectedOrg.value) orgSearch.value = ''
}

function selectOrg(org: OrgDirectoryItem) {
  selectedOrg.value = org
  orgSearch.value = ''   // 清空搜索词，让 placeholder 显示选中组织
  form.slug = org.slug
  pickerOpen.value = false
}

function clearSelection() {
  selectedOrg.value = null
  form.slug = ''
  orgSearch.value = ''
  orgInputRef.value?.focus()
}

function selectHighlighted() {
  if (!pickerOpen.value) return
  const org = filteredOrgs.value[highlightIdx.value]
  if (org) selectOrg(org)
}

function moveHighlight(dir: 1 | -1) {
  const max = filteredOrgs.value.length - 1
  highlightIdx.value = Math.max(0, Math.min(max, highlightIdx.value + dir))
}

// 点击组件外部关闭下拉
function onDocClick(e: MouseEvent) {
  if (pickerOpen.value && orgPickerRef.value && !orgPickerRef.value.contains(e.target as Node)) {
    closePicker()
  }
}

// ── 表单状态 ────────────────────────────────────────────────

const form = reactive({ slug: '', reason: '' })
const submitting = ref(false)
const canSubmit = computed(() => form.slug.trim().length > 0)

async function onSubmit() {
  if (!canSubmit.value) return
  submitting.value = true
  try {
    await submitJoinRequest(form.slug.trim(), form.reason.trim() || undefined)
    toast.success(t('joinOrg.submitted'))
    form.slug = ''
    form.reason = ''
    selectedOrg.value = null
    orgSearch.value = ''
    await loadHistory()
  } catch (e: unknown) {
    toast.error(resolveApiErrorMessage(e, t('joinOrg.submitFailed')))
  } finally {
    submitting.value = false
  }
}

// ── 我的申请历史 ────────────────────────────────────────────

const myRequests = ref<JoinRequestInfo[]>([])
const loadingHistory = ref(false)
const cancellingId = ref<string | null>(null)

async function loadHistory() {
  loadingHistory.value = true
  try {
    myRequests.value = await listMyJoinRequests()
  } catch (e: unknown) {
    toast.error(resolveApiErrorMessage(e, t('joinOrg.loadFailed')))
  } finally {
    loadingHistory.value = false
  }
}

async function onCancel(id: string) {
  cancellingId.value = id
  try {
    await cancelMyJoinRequest(id)
    toast.success(t('joinOrg.cancelled'))
    await loadHistory()
  } catch (e: unknown) {
    toast.error(resolveApiErrorMessage(e, t('joinOrg.cancelFailed')))
  } finally {
    cancellingId.value = null
  }
}

function statusLabel(s: JoinRequestStatus): string {
  return t(`joinOrg.status.${s}`)
}

function formatDate(iso?: string): string {
  if (!iso) return '-'
  const d = new Date(iso)
  const loc = locale.value === 'zh-CN' ? 'zh-CN' : 'en-US'
  return d.toLocaleString(loc, {
    month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

onMounted(async () => {
  document.addEventListener('click', onDocClick, true)
  await Promise.all([loadOrgs(), loadHistory()])
})

onUnmounted(() => {
  document.removeEventListener('click', onDocClick, true)
})
</script>
