<!--
  申请审核中心
  ---------------------------------
  - 顶级路由 /approvals，仅超管 / 任意组织 admin 可见（守卫在 router/index.ts）
  - 当前 Tab：
    · skills（启用）：技能上传/加载审核，列表来自 GET /admin/genes/pending-review
    · joinRequests（启用，需 multi_org）：组织加入申请审核
      列表来自 GET /admin/org-join-requests/pending
    · leaveRequests（启用，需 multi_org）：组织退出申请审核
      列表来自 GET /admin/org-leave-requests/pending
    · account（占位 disabled）：未来承载账号密码修改申请
    · feature（占位 disabled）：未来承载功能模块开放申请
  - 操作复用 stores/gene.ts（skills）+ services/orgJoinApi（join）+ services/orgLeaveApi（leave）
-->
<template>
  <div class="max-w-5xl mx-auto p-6 space-y-6">
    <!-- 页头 -->
    <div class="space-y-1">
      <h1 class="text-2xl font-semibold flex items-center gap-2">
        <ClipboardCheck class="w-6 h-6" />
        {{ t('approvals.title') }}
      </h1>
      <p class="text-sm text-muted-foreground">{{ t('approvals.subtitle') }}</p>
    </div>

    <!-- Tab 切换：skills 永久启用，joinRequests 仅 multi_org 启用时显示 -->
    <div class="flex gap-1 border-b border-border">
      <button
        v-for="tab in visibleTabs"
        :key="tab.key"
        :disabled="tab.disabled"
        :class="[
          'px-4 py-2 text-sm transition-colors border-b-2',
          activeTab === tab.key
            ? 'border-primary text-primary font-medium'
            : 'border-transparent text-muted-foreground',
          tab.disabled
            ? 'cursor-not-allowed opacity-50'
            : 'hover:text-foreground cursor-pointer',
        ]"
        @click="!tab.disabled && (activeTab = tab.key)"
      >
        {{ t(tab.labelKey) }}
        <span v-if="tab.disabled" class="ml-1 text-xs">({{ t('approvals.comingSoon') }})</span>
      </button>
    </div>

    <!-- 技能审核 Tab 内容 -->
    <div v-if="activeTab === 'skills'" class="space-y-4">
      <div v-if="loading" class="text-center py-12 text-sm text-muted-foreground">
        {{ t('common.loading') }}
      </div>
      <div
        v-else-if="pending.length === 0"
        class="text-center py-12 text-sm text-muted-foreground border border-dashed rounded-lg"
      >
        {{ t('approvals.empty') }}
      </div>
      <div v-else class="border rounded-lg overflow-hidden">
        <table class="w-full text-sm">
          <thead class="bg-muted/50">
            <tr class="text-left">
              <th class="px-4 py-2 font-medium">{{ t('approvals.columnName') }}</th>
              <th class="px-4 py-2 font-medium">{{ t('approvals.columnScope') }}</th>
              <th class="px-4 py-2 font-medium">{{ t('approvals.columnUploader') }}</th>
              <th class="px-4 py-2 font-medium">{{ t('approvals.columnSubmittedAt') }}</th>
              <th class="px-4 py-2 font-medium text-right">{{ t('approvals.columnActions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="gene in pending"
              :key="gene.id"
              class="border-t hover:bg-muted/30"
            >
              <td class="px-4 py-3">
                <div class="font-medium">{{ gene.name }}</div>
                <div class="text-xs text-muted-foreground">{{ gene.slug }}</div>
              </td>
              <td class="px-4 py-3">
                <span :class="scopeBadgeClass(gene.visibility)">
                  {{ scopeLabel(gene.visibility) }}
                </span>
              </td>
              <td class="px-4 py-3 text-muted-foreground">
                {{ uploaderLabel(gene) }}
              </td>
              <td class="px-4 py-3 text-muted-foreground">
                {{ formatDate(gene.created_at) }}
              </td>
              <td class="px-4 py-3 text-right space-x-2">
                <button
                  class="inline-flex items-center gap-1 px-3 py-1 text-xs rounded border border-green-500 text-green-700 hover:bg-green-50 disabled:opacity-50"
                  :disabled="reviewingId === gene.id"
                  @click="onReview(gene.id, 'approve')"
                >
                  <Check class="w-3 h-3" />
                  {{ t('approvals.approve') }}
                </button>
                <button
                  class="inline-flex items-center gap-1 px-3 py-1 text-xs rounded border border-red-500 text-red-700 hover:bg-red-50 disabled:opacity-50"
                  :disabled="reviewingId === gene.id"
                  @click="onReview(gene.id, 'reject')"
                >
                  <X class="w-3 h-3" />
                  {{ t('approvals.reject') }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 加入组织审核 Tab 内容 -->
    <div v-else-if="activeTab === 'joinRequests'" class="space-y-4">
      <div v-if="loadingJoin" class="text-center py-12 text-sm text-muted-foreground">
        {{ t('common.loading') }}
      </div>
      <div
        v-else-if="pendingJoin.length === 0"
        class="text-center py-12 text-sm text-muted-foreground border border-dashed rounded-lg"
      >
        {{ t('approvals.emptyJoinRequests') }}
      </div>
      <div v-else class="border rounded-lg overflow-hidden">
        <table class="w-full text-sm">
          <thead class="bg-muted/50">
            <tr class="text-left">
              <th class="px-4 py-2 font-medium">{{ t('approvals.columnRequester') }}</th>
              <th class="px-4 py-2 font-medium">{{ t('approvals.columnTargetOrg') }}</th>
              <th class="px-4 py-2 font-medium">{{ t('approvals.columnReason') }}</th>
              <th class="px-4 py-2 font-medium">{{ t('approvals.columnSubmittedAt') }}</th>
              <th class="px-4 py-2 font-medium text-right">{{ t('approvals.columnActions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="req in pendingJoin"
              :key="req.id"
              class="border-t hover:bg-muted/30"
            >
              <td class="px-4 py-3">
                <div class="font-medium">{{ requesterLabel(req) }}</div>
                <div v-if="req.requester_email" class="text-xs text-muted-foreground">
                  {{ req.requester_email }}
                </div>
              </td>
              <td class="px-4 py-3">
                <div class="font-medium">{{ req.org_name || req.org_slug || '-' }}</div>
                <div v-if="req.org_slug" class="text-xs text-muted-foreground">
                  {{ req.org_slug }}
                </div>
              </td>
              <td class="px-4 py-3 text-muted-foreground max-w-xs truncate" :title="req.reason || ''">
                {{ req.reason || '-' }}
              </td>
              <td class="px-4 py-3 text-muted-foreground">
                {{ formatDate(req.created_at) }}
              </td>
              <td class="px-4 py-3 text-right space-x-2">
                <button
                  class="inline-flex items-center gap-1 px-3 py-1 text-xs rounded border border-green-500 text-green-700 hover:bg-green-50 disabled:opacity-50"
                  :disabled="reviewingJoinId === req.id"
                  @click="onReviewJoin(req.id, 'approve')"
                >
                  <Check class="w-3 h-3" />
                  {{ t('approvals.approve') }}
                </button>
                <button
                  class="inline-flex items-center gap-1 px-3 py-1 text-xs rounded border border-red-500 text-red-700 hover:bg-red-50 disabled:opacity-50"
                  :disabled="reviewingJoinId === req.id"
                  @click="onReviewJoin(req.id, 'reject')"
                >
                  <X class="w-3 h-3" />
                  {{ t('approvals.reject') }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 退出组织审核 Tab 内容 -->
    <div v-else-if="activeTab === 'leaveRequests'" class="space-y-4">
      <div v-if="loadingLeave" class="text-center py-12 text-sm text-muted-foreground">
        {{ t('common.loading') }}
      </div>
      <div
        v-else-if="pendingLeave.length === 0"
        class="text-center py-12 text-sm text-muted-foreground border border-dashed rounded-lg"
      >
        {{ t('approvals.emptyLeaveRequests') }}
      </div>
      <div v-else class="border rounded-lg overflow-hidden">
        <table class="w-full text-sm">
          <thead class="bg-muted/50">
            <tr class="text-left">
              <th class="px-4 py-2 font-medium">{{ t('approvals.columnRequester') }}</th>
              <th class="px-4 py-2 font-medium">{{ t('approvals.columnLeavingOrg') }}</th>
              <th class="px-4 py-2 font-medium">{{ t('approvals.columnReason') }}</th>
              <th class="px-4 py-2 font-medium">{{ t('approvals.columnSubmittedAt') }}</th>
              <th class="px-4 py-2 font-medium text-right">{{ t('approvals.columnActions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="req in pendingLeave"
              :key="req.id"
              class="border-t hover:bg-muted/30"
            >
              <td class="px-4 py-3">
                <div class="font-medium flex items-center gap-2">
                  {{ leaveRequesterLabel(req) }}
                  <!-- admin 退出时高亮提醒，便于审核者评估"唯一 admin"风险 -->
                  <span
                    v-if="req.requester_role === 'admin'"
                    class="inline-block px-1.5 py-0.5 text-[10px] rounded bg-amber-100 text-amber-700"
                  >
                    admin
                  </span>
                </div>
                <div v-if="req.requester_email" class="text-xs text-muted-foreground">
                  {{ req.requester_email }}
                </div>
              </td>
              <td class="px-4 py-3">
                <div class="font-medium">{{ req.org_name || req.org_slug || '-' }}</div>
                <div v-if="req.org_slug" class="text-xs text-muted-foreground">
                  {{ req.org_slug }}
                </div>
              </td>
              <td class="px-4 py-3 text-muted-foreground max-w-xs truncate" :title="req.reason || ''">
                {{ req.reason || '-' }}
              </td>
              <td class="px-4 py-3 text-muted-foreground">
                {{ formatDate(req.created_at) }}
              </td>
              <td class="px-4 py-3 text-right space-x-2">
                <button
                  class="inline-flex items-center gap-1 px-3 py-1 text-xs rounded border border-green-500 text-green-700 hover:bg-green-50 disabled:opacity-50"
                  :disabled="reviewingLeaveId === req.id"
                  @click="onReviewLeave(req.id, 'approve')"
                >
                  <Check class="w-3 h-3" />
                  {{ t('approvals.approve') }}
                </button>
                <button
                  class="inline-flex items-center gap-1 px-3 py-1 text-xs rounded border border-red-500 text-red-700 hover:bg-red-50 disabled:opacity-50"
                  :disabled="reviewingLeaveId === req.id"
                  @click="onReviewLeave(req.id, 'reject')"
                >
                  <X class="w-3 h-3" />
                  {{ t('approvals.reject') }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 占位 Tab：账号修改 / 功能开放 -->
    <div
      v-else
      class="text-center py-16 text-sm text-muted-foreground border border-dashed rounded-lg"
    >
      {{ t('approvals.placeholderComingSoon') }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ClipboardCheck, Check, X } from 'lucide-vue-next'
import { useGeneStore, type GeneItem } from '@/stores/gene'
import { useToast } from '@/composables/useToast'
import { useFeature } from '@/composables/useFeature'
import { resolveApiErrorMessage } from '@/i18n/error'
import {
  listPendingJoinRequests,
  reviewJoinRequest,
  type JoinRequestInfo,
} from '@/services/orgJoinApi'
import {
  listPendingLeaveRequests,
  reviewLeaveRequest,
  type LeaveRequestInfo,
} from '@/services/orgLeaveApi'

const { t, locale } = useI18n()
const store = useGeneStore()
const toast = useToast()
const { isEnabled: hasMultiOrg } = useFeature('multi_org')

// 五类申请 Tab：skills 默认启用；joinRequests / leaveRequests 受 multi_org 控制；其余暂占位
type TabKey = 'skills' | 'joinRequests' | 'leaveRequests' | 'account' | 'feature'
interface TabDef {
  key: TabKey
  labelKey: string
  disabled: boolean
  requireFeature?: string
}
const allTabs: TabDef[] = [
  { key: 'skills', labelKey: 'approvals.tabSkills', disabled: false },
  { key: 'joinRequests', labelKey: 'approvals.tabJoinRequests', disabled: false, requireFeature: 'multi_org' },
  { key: 'leaveRequests', labelKey: 'approvals.tabLeaveRequests', disabled: false, requireFeature: 'multi_org' },
  { key: 'account', labelKey: 'approvals.tabAccount', disabled: true },
  { key: 'feature', labelKey: 'approvals.tabFeature', disabled: true },
]
// 仅渲染当前 edition 实际可用的 Tab（multi_org 关闭时同时隐藏 join + leave）
const visibleTabs = computed(() =>
  allTabs.filter(t => !t.requireFeature || (t.requireFeature === 'multi_org' && hasMultiOrg.value)),
)
const activeTab = ref<TabKey>('skills')

// === 技能审核（保留原行为） ============================================
const pending = ref<GeneItem[]>([])
const loading = ref(false)
const reviewingId = ref<string | null>(null)

async function loadPending() {
  loading.value = true
  try {
    const data = await store.fetchPendingReviewGenes()
    pending.value = (data as GeneItem[]) ?? []
  } catch {
    toast.error(t('approvals.loadFailed'))
  } finally {
    loading.value = false
  }
}

async function onReview(geneId: string, action: 'approve' | 'reject') {
  reviewingId.value = geneId
  try {
    await store.reviewGene(geneId, action)
    pending.value = pending.value.filter((g) => g.id !== geneId)
    toast.success(
      action === 'approve' ? t('approvals.approveSuccess') : t('approvals.rejectSuccess'),
    )
  } catch {
    toast.error(t('approvals.actionFailed'))
  } finally {
    reviewingId.value = null
  }
}

// === 组织加入审核 ====================================================
const pendingJoin = ref<JoinRequestInfo[]>([])
const loadingJoin = ref(false)
const reviewingJoinId = ref<string | null>(null)

async function loadPendingJoin() {
  if (!hasMultiOrg.value) return  // CE 模式无入口，避免无谓 403
  loadingJoin.value = true
  try {
    pendingJoin.value = await listPendingJoinRequests()
  } catch {
    toast.error(t('approvals.loadJoinRequestsFailed'))
  } finally {
    loadingJoin.value = false
  }
}

async function onReviewJoin(requestId: string, action: 'approve' | 'reject') {
  reviewingJoinId.value = requestId
  try {
    let note: string | undefined
    if (action === 'reject') {
      // 拒绝时弹 prompt 收集可选 note；取消视为不填备注但仍执行
      const input = window.prompt(t('approvals.rejectNotePlaceholder'))
      note = input?.trim() || undefined
    }
    await reviewJoinRequest(requestId, action, note)
    pendingJoin.value = pendingJoin.value.filter(r => r.id !== requestId)
    toast.success(
      action === 'approve' ? t('approvals.approveJoinSuccess') : t('approvals.rejectJoinSuccess'),
    )
  } catch {
    toast.error(t('approvals.actionFailed'))
  } finally {
    reviewingJoinId.value = null
  }
}

// === 组织退出审核 ====================================================
const pendingLeave = ref<LeaveRequestInfo[]>([])
const loadingLeave = ref(false)
const reviewingLeaveId = ref<string | null>(null)

async function loadPendingLeave() {
  if (!hasMultiOrg.value) return
  loadingLeave.value = true
  try {
    pendingLeave.value = await listPendingLeaveRequests()
  } catch {
    toast.error(t('approvals.loadLeaveRequestsFailed'))
  } finally {
    loadingLeave.value = false
  }
}

async function onReviewLeave(requestId: string, action: 'approve' | 'reject') {
  reviewingLeaveId.value = requestId
  try {
    let note: string | undefined
    if (action === 'reject') {
      const input = window.prompt(t('approvals.rejectNotePlaceholder'))
      note = input?.trim() || undefined
    }
    await reviewLeaveRequest(requestId, action, note)
    pendingLeave.value = pendingLeave.value.filter(r => r.id !== requestId)
    toast.success(
      action === 'approve' ? t('approvals.approveLeaveSuccess') : t('approvals.rejectLeaveSuccess'),
    )
  } catch (e: unknown) {
    // 退出审核有特殊业务错误（如唯一 admin），尽量把后端 message 透出
    toast.error(resolveApiErrorMessage(e, t('approvals.actionFailed')))
  } finally {
    reviewingLeaveId.value = null
  }
}

// === 共用 helpers =====================================================

// 加入申请的申请者展示：name → email → UUID 截短，避免裸显 UUID
function requesterLabel(req: JoinRequestInfo): string {
  if (req.requester_name) return req.requester_name
  if (req.requester_email) return req.requester_email
  if (req.user_id) return req.user_id.slice(0, 8) + '…'
  return '-'
}

// 退出申请的申请者展示：与 join 同模式，仅参数类型不同
function leaveRequesterLabel(req: LeaveRequestInfo): string {
  if (req.requester_name) return req.requester_name
  if (req.requester_email) return req.requester_email
  if (req.user_id) return req.user_id.slice(0, 8) + '…'
  return '-'
}

// 上传者展示：优先 name → email → UUID 截短
function uploaderLabel(gene: GeneItem): string {
  if (gene.created_by_name) return gene.created_by_name
  if (gene.created_by_email) return gene.created_by_email
  if (gene.created_by) return gene.created_by.slice(0, 8) + '…'
  return '-'
}

// 可见性 → 中文/英文标签 + 颜色样式（技能 Tab 用）
function scopeLabel(visibility?: string): string {
  if (visibility === 'public') return t('approvals.scopePublic')
  if (visibility === 'org_private') return t('approvals.scopeOrg')
  if (visibility === 'personal') return t('approvals.scopePersonal')
  return visibility ?? '-'
}

function scopeBadgeClass(visibility?: string): string {
  const base = 'inline-block px-2 py-0.5 text-xs rounded-full'
  if (visibility === 'public') return `${base} bg-blue-100 text-blue-700`
  if (visibility === 'org_private') return `${base} bg-amber-100 text-amber-700`
  return `${base} bg-gray-100 text-gray-700`
}

// 时间格式化：跟随当前语言
function formatDate(s?: string): string {
  if (!s) return '-'
  const d = new Date(s)
  const loc = locale.value === 'zh-CN' ? 'zh-CN' : 'en-US'
  return d.toLocaleString(loc, {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

onMounted(async () => {
  // 三个 Tab 数据并行预拉取，切换体感更顺
  await Promise.all([loadPending(), loadPendingJoin(), loadPendingLeave()])
})
</script>
