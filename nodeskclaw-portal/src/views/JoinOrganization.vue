<!--
  申请加入组织
  ----------
  - 仅 multi_org feature 启用时可访问（route meta 检查 + 后端二次校验）
  - 已加入组织的用户也能从其他入口进来申请加入"其他组织"
  - 表单：组织标识 (slug) + 申请理由（可选）
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
      <div class="space-y-1">
        <label class="text-sm font-medium">{{ t('joinOrg.slugLabel') }}</label>
        <input
          v-model.trim="form.slug"
          :placeholder="t('joinOrg.slugPlaceholder')"
          :disabled="submitting"
          class="w-full border rounded px-3 py-2 text-sm bg-background"
        />
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
import { ref, computed, onMounted, reactive } from 'vue'
import { useI18n } from 'vue-i18n'
import { UserPlus, Loader2 } from 'lucide-vue-next'
import { useToast } from '@/composables/useToast'
import { resolveApiErrorMessage } from '@/i18n/error'
import {
  submitJoinRequest,
  listMyJoinRequests,
  cancelMyJoinRequest,
  type JoinRequestInfo,
  type JoinRequestStatus,
} from '@/services/orgJoinApi'

const { t, locale } = useI18n()
const toast = useToast()

// 表单状态
const form = reactive({ slug: '', reason: '' })
const submitting = ref(false)

// 我的申请历史
const myRequests = ref<JoinRequestInfo[]>([])
const loadingHistory = ref(false)
const cancellingId = ref<string | null>(null)

const canSubmit = computed(() => form.slug.trim().length > 0)

// 提交申请：成功后清空表单 + 刷新列表
async function onSubmit() {
  if (!canSubmit.value) return
  submitting.value = true
  try {
    await submitJoinRequest(form.slug.trim(), form.reason.trim() || undefined)
    toast.success(t('joinOrg.submitted'))
    form.slug = ''
    form.reason = ''
    await loadHistory()
  } catch (e: unknown) {
    toast.error(resolveApiErrorMessage(e, t('joinOrg.submitFailed')))
  } finally {
    submitting.value = false
  }
}

// 拉取我提交的全部申请（含历史终态）
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

// 撤回 pending 申请：成功后从列表中移除
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

// 状态文案：复用 approvals 已有词条 + 新增 cancelled
function statusLabel(s: JoinRequestStatus): string {
  return t(`joinOrg.status.${s}`)
}

// 时间格式化：跟随当前语言
function formatDate(iso?: string): string {
  if (!iso) return '-'
  const d = new Date(iso)
  const loc = locale.value === 'zh-CN' ? 'zh-CN' : 'en-US'
  return d.toLocaleString(loc, {
    month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

onMounted(loadHistory)
</script>
