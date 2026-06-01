<!--
  申请审核中心
  ---------------------------------
  - 顶级路由 /approvals，仅超管 / 任意组织 admin 可见（守卫在 router/index.ts）
  - 当前 Tab：
    · skills（启用）：技能上传/加载审核，列表来自 GET /admin/genes/pending-review
    · account（占位 disabled）：未来承载账号密码修改申请
    · feature（占位 disabled）：未来承载功能模块开放申请
  - 操作复用 stores/gene.ts 已有的 fetchPendingReviewGenes / reviewGene
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

    <!-- Tab 切换：当前仅 skills 启用，其他显示「即将上线」 -->
    <div class="flex gap-1 border-b border-border">
      <button
        v-for="tab in tabs"
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
                {{ gene.created_by ?? '-' }}
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
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ClipboardCheck, Check, X } from 'lucide-vue-next'
import { useGeneStore, type GeneItem } from '@/stores/gene'
import { useToast } from '@/composables/useToast'

const { t, locale } = useI18n()
const store = useGeneStore()
const toast = useToast()

// 三类申请 Tab：当前仅 skills 启用
type TabKey = 'skills' | 'account' | 'feature'
const tabs: { key: TabKey; labelKey: string; disabled: boolean }[] = [
  { key: 'skills', labelKey: 'approvals.tabSkills', disabled: false },
  { key: 'account', labelKey: 'approvals.tabAccount', disabled: true },
  { key: 'feature', labelKey: 'approvals.tabFeature', disabled: true },
]
const activeTab = ref<TabKey>('skills')

// 待审列表 + 加载/操作中状态
const pending = ref<GeneItem[]>([])
const loading = ref(false)
const reviewingId = ref<string | null>(null)

// 拉取待审列表（权限由后端按当前用户过滤）
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

// approve / reject：成功后从列表移除，失败保留并 toast
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

// 可见性 → 中文/英文标签 + 颜色样式
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

onMounted(loadPending)
</script>
