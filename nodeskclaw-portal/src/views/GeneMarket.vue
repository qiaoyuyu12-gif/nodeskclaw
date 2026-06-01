<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  Search,
  Loader2,
  Star,
  Package,
  Code,
  Database,
  Cpu,
  Server,
  Shield,
  Zap,
  Wrench,
  Palette,
  MessageSquare,
  Network,
  Sparkles,
  Layers,
  Dna,
  Download,
  TrendingUp,
  AlertCircle,
  Activity,
  Check,
  X,
  Globe,
  HardDrive,
  Upload,
  FolderOpen,
  AlertTriangle,
  Code2,
  Trash2,
  type Component,
} from 'lucide-vue-next'
import { useGeneStore } from '@/stores/gene'
import type { GeneItem, GenomeItem, TemplateInfo } from '@/stores/gene'
import { useToast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth'
import { resolveApiErrorMessage } from '@/i18n/error'
import CustomSelect from '@/components/shared/CustomSelect.vue'
import { skillApi } from '@/services/skills'

const router = useRouter()
const store = useGeneStore()
const authStore = useAuthStore()  // 用于获取当前登录用户，判断删除权限
const toast = useToast()
const { t, locale } = useI18n()

const viewMode = ref<'genes' | 'templates' | 'local'>('genes')
const keyword = ref('')
const selectedCategory = ref<string | null>(null)
// 三栏归属过滤：默认进入「公共市场」；'personal' / 'org_private' / 'public'
const selectedVisibility = ref<string>('public')
const sortBy = ref('popularity')
const page = ref(1)
const pageSize = ref(12)

// ── 本地上传 Tab 状态 ──────────────────────────────
const showLocalUpload = ref(false)
const localUploading = ref(false)
const localError = ref<string | null>(null)
const localSuccess = ref<string | null>(null)
const localDragOver = ref(false)
const localFileInputRef = ref<HTMLInputElement>()
const selectedLocalFiles = ref<string[]>([])
const localFolderInputRef = ref<HTMLInputElement>()
// 上传目标库：默认 personal（个人 library，无需审核），可选 org / public
const uploadTarget = ref<'personal' | 'org' | 'public'>('personal')

async function handleLocalFile(file: File) {
  localError.value = '请使用文件夹上传功能'
  return
}

async function handleLocalFolder() {
  const input = localFolderInputRef.value
  if (!input?.files || input.files.length === 0) {
    localError.value = '请先选择文件夹'
    return
  }
  localUploading.value = true
  localError.value = null
  localSuccess.value = null
  try {
    await skillApi.uploadFolder(input.files, false, uploadTarget.value)
    localSuccess.value = uploadTarget.value === 'personal'
      ? '已上传到个人技能 library'
      : uploadTarget.value === 'org'
        ? '已提交到组织技能 library，等待组织管理员审核'
        : '已提交到公共市场，等待组织管理员审核'
    showLocalUpload.value = false
    selectedLocalFiles.value = []
    await loadData()
  } catch (e: any) {
    // 409 冲突：同名基因已存在，提示用户确认覆盖
    if (e?.response?.status === 409) {
      const msg = e?.response?.data?.message || ''
      if (msg.includes('已存在') || msg.includes('already exists')) {
        const folderName = input.files[0]?.webkitRelativePath?.split('/')[0] || '该文件夹'
        const ok = confirm(`${folderName} 基因已存在，是否覆盖原基因？`)
        if (ok) {
          // 重新上传，携带覆盖参数
          try {
            await skillApi.uploadFolder(input.files, true, uploadTarget.value)
            localSuccess.value = `基因已覆盖`
            showLocalUpload.value = false
            selectedLocalFiles.value = []
            await loadData()
          } catch (e2: any) {
            localError.value = e2?.response?.data?.message || '覆盖失败'
          }
        } else {
          localError.value = '已取消上传'
        }
      } else {
        localError.value = msg || '上传失败'
      }
    } else {
      localError.value = e instanceof Error ? e.message : '上传失败'
    }
  } finally {
    localUploading.value = false
  }
}

function onLocalFolderInput(e: Event) {
  const input = e.target as HTMLInputElement
  if (!input.files || input.files.length === 0) return
  selectedLocalFiles.value = Array.from(input.files).map(
    f => (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name
  )
}

const categories = ['开发', '数据', '运维', '网络', '创意', '沟通', '安全', '效率']

const sortOptions = ['popularity', 'rating', 'effectiveness', 'newest']

const geneMetaKeyMap: Record<string, string> = {
  开发: 'geneMeta.development',
  数据: 'geneMeta.data',
  运维: 'geneMeta.ops',
  网络: 'geneMeta.network',
  创意: 'geneMeta.creativity',
  沟通: 'geneMeta.communication',
  安全: 'geneMeta.security',
  效率: 'geneMeta.efficiency',
  性格: 'geneMeta.personality',
  能力: 'geneMeta.ability',
  知识: 'geneMeta.knowledge',
}

function localizeGeneMeta(value?: string) {
  if (!value) return ''
  const key = geneMetaKeyMap[value]
  if (!key) return value
  const translated = t(key)
  return translated === key ? value : translated
}

function getSortLabel(value: string) {
  const map: Record<string, string> = {
    popularity: 'geneMarket.sortPopularity',
    rating: 'geneMarket.sortRating',
    effectiveness: 'geneMarket.sortEffectiveness',
    newest: 'geneMarket.sortNewest',
  }
  const key = map[value]
  if (!key) return value
  const translated = t(key)
  return translated === key ? value : translated
}

const categorySelectOptions = computed(() => [
  { value: null, label: t('geneMarket.allCategories') },
  ...categories.map(c => ({ value: c, label: localizeGeneMeta(c) })),
])

const sortSelectOptions = computed(() =>
  sortOptions.map(s => ({ value: s, label: getSortLabel(s) }))
)

const iconMap: Record<string, typeof Package> = {
  code: Code,
  database: Database,
  cpu: Cpu,
  server: Server,
  shield: Shield,
  zap: Zap,
  wrench: Wrench,
  palette: Palette,
  message: MessageSquare,
  network: Network,
  sparkles: Sparkles,
  layers: Layers,
  package: Package,
}

function resolveIcon(iconName?: string) {
  if (!iconName) return Package
  const key = iconName.toLowerCase().replace(/[- ]/g, '')
  return iconMap[key] ?? iconMap[iconName] ?? Package
}

const evoStats = ref(store.geneStats)
const evoHotGenes = ref<GeneItem[]>([])
const evoActivity = ref<{ id: string; gene_slug: string; gene_name: string; metric_type: string; value: number; created_at?: string }[]>([])
const evoPending = ref<GeneItem[]>([])
const evoLoading = ref(false)
const evoActivityLoading = ref(false)
const evoPendingLoading = ref(false)
const evoReviewingId = ref<string | null>(null)

async function loadEvolution() {
  evoLoading.value = true
  try {
    await store.fetchGeneStats()
    evoStats.value = store.geneStats
    await store.fetchGenes({ sort: 'effectiveness', page_size: 10 })
    evoHotGenes.value = [...store.genes]
  } finally {
    evoLoading.value = false
  }
  evoActivityLoading.value = true
  store.fetchGeneActivity(50).then((data) => {
    evoActivity.value = data as typeof evoActivity.value
  }).finally(() => { evoActivityLoading.value = false })
  evoPendingLoading.value = true
  store.fetchPendingReviewGenes().then((data) => {
    evoPending.value = (data as GeneItem[]) ?? []
  }).finally(() => { evoPendingLoading.value = false })
}

async function handleReview(geneId: string, action: 'approve' | 'reject') {
  evoReviewingId.value = geneId
  try {
    await store.reviewGene(geneId, action)
    evoPending.value = evoPending.value.filter((g) => g.id !== geneId)
    toast.success(action === 'approve' ? t('geneMarket.reviewApproved') : t('geneMarket.reviewRejected'))
  } catch {
    toast.error(t('geneMarket.actionFailed'))
  } finally {
    evoReviewingId.value = null
  }
}

function formatMetricType(metricType: string): string {
  const map: Record<string, string> = {
    user_positive: 'geneMarket.metricUserPositive',
    user_negative: 'geneMarket.metricUserNegative',
    task_success: 'geneMarket.metricTaskSuccess',
    agent_self_eval: 'geneMarket.metricAgentSelfEval',
  }
  const key = map[metricType]
  if (!key) return metricType
  const translated = t(key)
  return translated === key ? metricType : translated
}

function formatDate(s?: string): string {
  if (!s) return '-'
  const d = new Date(s)
  const currentLocale = locale.value === 'zh-CN' ? 'zh-CN' : 'en-US'
  return d.toLocaleString(currentLocale, { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

const featuredItems = computed(() => {
  if (viewMode.value === 'genes') return store.featuredGenes
  return []
})

const hasFeatured = computed(() => featuredItems.value.length > 0 && selectedVisibility.value === 'public')

const totalCount = computed(() => {
  if (viewMode.value === 'genes') return store.totalGenes
  if (viewMode.value === 'templates') return store.totalTemplates
  return 0
})

const totalPages = computed(() => Math.ceil(totalCount.value / pageSize.value) || 1)
const canPrev = computed(() => page.value > 1)
const canNext = computed(() => page.value < totalPages.value)

/**
 * 判断当前用户是否有权限删除某个 gene。
 * 前端仅做显示层过滤（上传者本人 / 超管），
 * org admin 权限需查 membership，由后端兜底拦截。
 * 仅本地上传（source_registry === 'local'）的 gene 才显示删除按钮。
 */
function canDeleteGene(gene: GeneItem): boolean {
  if (gene.source_registry !== 'local') return false
  const me = authStore.user
  if (!me) return false
  return me.is_super_admin || gene.created_by === me.id
}

/**
 * 删除 gene 的确认 + 请求逻辑。
 * 后端 409（如个人技能已被 Agent 加载）会带 message_key，由 resolveApiErrorMessage 翻译为本地化 toast。
 */
async function onDeleteGene(gene: GeneItem) {
  if (!confirm(t('geneMarket.deleteConfirm', { name: gene.name }))) return
  try {
    await skillApi.deleteGene(gene.id)
    toast.success(t('geneMarket.deleteSuccess'))
    await loadData()
  } catch (e: unknown) {
    // 走统一错误解析：优先 message_key 翻译；缺失时回退为后端原文 message，再退到通用文案
    toast.error(resolveApiErrorMessage(e, t('geneMarket.deleteFailed')))
  }
}

/**
 * fork 一份 gene 到个人 / 组织 / 公共 library。
 * 权限校验在后端兜底，前端按 canForkFrom 决定按钮显示。
 * - personal：归属当前用户，无需审核
 * - org：归属当前组织，pending_owner 等组织 admin 审核
 * - public：visibility=public 但 pending_owner，需组织 admin 审核
 */
const forkingSlug = ref<string | null>(null)
async function onForkGene(gene: GeneItem, target: 'personal' | 'org' | 'public') {
  forkingSlug.value = gene.slug
  try {
    // 必须用 gene.id（UUID）传给后端：三向 fork 后同 slug 可在多 scope 并存，按 slug 查会冲突
    await store.forkGene(gene.id, target)
    // 按 target 选择对应 i18n 成功文案
    const successKey =
      target === 'personal'
        ? 'geneMarket.forkToPersonalSuccess'
        : target === 'org'
          ? 'geneMarket.forkToOrgSuccess'
          : 'geneMarket.forkToPublicSuccess'
    toast.success(t(successKey))
    // 当前正在浏览目标 scope 时刷新列表
    const visMatches =
      (target === 'personal' && selectedVisibility.value === 'personal') ||
      (target === 'org' && selectedVisibility.value === 'org_private') ||
      (target === 'public' && selectedVisibility.value === 'public')
    if (visMatches) await loadData()
  } catch (e: unknown) {
    // 统一错误解析：优先 message_key 翻译（如 fork_personal_forbidden / fork_org_forbidden）
    toast.error(resolveApiErrorMessage(e, t('geneMarket.forkFailed')))
  } finally {
    forkingSlug.value = null
  }
}

/**
 * 判断当前用户能将某 gene 作为源 fork 到哪些目标。
 * 与后端 fork_gene_to_library 的权限矩阵保持一致：
 *   - 源 personal：仅本人可 fork（→ org / public）
 *   - 源 org：本组成员可 fork（→ personal / public）
 *   - 源 public：任意登录用户可 fork（→ personal / org）
 * 同 scope 隐藏自身按钮；最终以后端 403 兜底，前端仅做显示层裁剪。
 */
function canForkFrom(gene: GeneItem): { personal: boolean; org: boolean; public: boolean } {
  const me = authStore.user
  const empty = { personal: false, org: false, public: false }
  if (!me) return empty

  const fromPersonal = gene.org_id == null && gene.created_by != null
  const fromPublic = gene.visibility === 'public'
  const fromOrg = !fromPersonal && !fromPublic && gene.org_id != null

  const allowed =
    me.is_super_admin ||
    fromPublic ||
    (fromPersonal && gene.created_by === me.id) ||
    (fromOrg && me.current_org_id === gene.org_id)
  if (!allowed) return empty

  // 隐藏同 scope；org / public 目标都需要有 current_org_id（前端拦一道，后端兜底）
  return {
    personal: !fromPersonal,
    org: !fromOrg && !!me.current_org_id,
    public: !fromPublic && !!me.current_org_id,
  }
}

async function loadData() {
  if (viewMode.value === 'genes') {
    await store.fetchGenes({
      keyword: keyword.value || undefined,
      category: selectedCategory.value || undefined,
      visibility: selectedVisibility.value || undefined,
      sort: sortBy.value,
      page: page.value,
      page_size: pageSize.value,
    })
  } else if (viewMode.value === 'templates') {
    await store.fetchTemplates({
      keyword: keyword.value || undefined,
      visibility: selectedVisibility.value || undefined,
      page: page.value,
      page_size: pageSize.value,
    })
  }
}

async function loadFeatured() {
  if (viewMode.value === 'genes') {
    await store.fetchFeaturedGenes()
  }
}

function goToTemplate(id: string) {
  router.push(`/gene-market/template/${id}`)
}

async function onMount() {
  await store.fetchGeneTags()
  await loadFeatured()
  await loadData()
}

onMounted(onMount)

watch([keyword, selectedVisibility, selectedCategory, sortBy, viewMode], () => {
  page.value = 1
  loadData()
})

watch(page, loadData)

function goToGene(slug: string) {
  router.push(`/gene-market/gene/${slug}`)
}

function goToGenome(id: string) {
  router.push(`/gene-market/genome/${id}`)
}

function hasNativeTools(gene: GeneItem): boolean {
  const toolAllow = gene.manifest?.tool_allow
  if (Array.isArray(toolAllow) && toolAllow.length > 0) return true
  const mcpServers = gene.manifest?.mcp_servers
  if (Array.isArray(mcpServers) && mcpServers.length > 0) return true
  const tags = gene.tags ?? []
  return tags.some((t) => ['mcp', 'tools'].includes(String(t).toLowerCase()))
}
</script>

<template>
  <div class="min-h-screen bg-background text-foreground">
    <div class="max-w-6xl mx-auto px-6 pt-6 pb-8">

      <!-- 页面标题 -->
      <h1 class="text-2xl font-bold mb-6">{{ t('geneMarket.title') }}</h1>

      <!-- 顶部 Tab 切换 -->
      <div class="flex gap-2 mb-6">
        <button
          :class="[
            'px-4 py-2 rounded-lg text-sm font-medium transition-colors',
            viewMode === 'genes'
              ? 'bg-primary/10 text-primary'
              : 'text-muted-foreground hover:text-foreground hover:bg-muted',
          ]"
          @click="viewMode = 'genes'"
        >
          {{ t('geneMarket.tabGenes') }}
        </button>
        <button
          :class="[
            'px-4 py-2 rounded-lg text-sm font-medium transition-colors',
            viewMode === 'templates'
              ? 'bg-primary/10 text-primary'
              : 'text-muted-foreground hover:text-foreground hover:bg-muted',
          ]"
          @click="viewMode = 'templates'"
        >
          {{ t('geneMarket.tabTemplates') }}
        </button>
        <button
          :class="[
            'px-4 py-2 rounded-lg text-sm font-medium transition-colors',
            viewMode === 'local'
              ? 'bg-primary/10 text-primary'
              : 'text-muted-foreground hover:text-foreground hover:bg-muted',
          ]"
          @click="viewMode = 'local'"
        >
          {{ t('geneMarket.tabLocal') }}
        </button>
      </div>

      <!-- 基因/模板/本地上传 Tab -->

        <!-- 归属三栏 Tab：个人 library / 组织 library / 公共市场（仅 genes/templates 视图） -->
        <div v-if="viewMode === 'genes' || viewMode === 'templates'" class="flex gap-2 mb-4">
          <button
            v-for="vis in [
              { value: 'public', key: 'geneMarket.scopePublic' },
              { value: 'org_private', key: 'geneMarket.scopeOrg' },
              { value: 'personal', key: 'geneMarket.scopePersonal' },
            ]"
            :key="vis.value"
            :class="[
              'px-4 py-2 rounded-lg text-sm font-medium transition-colors',
              selectedVisibility === vis.value
                ? 'bg-primary/10 text-primary'
                : 'bg-muted/50 text-muted-foreground hover:text-foreground hover:bg-muted',
            ]"
            @click="selectedVisibility = vis.value"
          >
            {{ t(vis.key) }}
          </button>
        </div>

        <!-- 搜索和筛选栏 -->
        <div class="flex flex-wrap gap-3 mb-6">
          <div class="relative flex-1 min-w-[200px]">
            <Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <input
              v-model="keyword"
              type="text"
              :placeholder="t('geneMarket.searchPlaceholder')"
              class="w-full pl-10 pr-4 py-2 rounded-lg border border-border bg-card text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
            />
          </div>

          <CustomSelect
            v-if="viewMode === 'genes'"
            v-model="selectedCategory"
            :options="categorySelectOptions"
          />

          <CustomSelect v-model="sortBy" :options="sortSelectOptions" />
        </div>

        <div v-if="store.loading" class="flex justify-center py-20">
          <Loader2 class="w-8 h-8 animate-spin text-muted-foreground" />
        </div>

        <template v-else>
          <section>
            <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
              <template v-if="viewMode === 'genes'">
              <div
                v-for="gene in store.genes"
                :key="gene.id"
                class="relative p-4 rounded-xl border border-border bg-card hover:border-primary/30 transition cursor-pointer"
                @click="goToGene(gene.slug)"
              >
                <!-- 删除按钮：仅本地上传 gene 且当前用户有权限时显示 -->
                <button
                  v-if="canDeleteGene(gene)"
                  class="absolute top-2 right-2 p-1 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition z-10"
                  :title="t('geneMarket.deleteGene')"
                  @click.stop="onDeleteGene(gene)"
                >
                  <Trash2 class="w-4 h-4" />
                </button>
                <div class="flex items-start gap-3 mb-2">
                  <div class="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
                    <component :is="resolveIcon(gene.icon)" class="w-5 h-5 text-primary" />
                  </div>
                  <div class="min-w-0 flex-1">
                    <div class="flex items-center gap-2 flex-wrap">
                      <span class="font-medium truncate">{{ gene.name }}</span>
                      <span class="shrink-0 text-xs px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                        v{{ gene.version }}
                      </span>
                      <span
                        v-if="gene.source_registry && gene.source_registry !== 'local'"
                        class="inline-flex items-center gap-1 px-1.5 py-0.5 text-xs rounded-full bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400"
                      >
                        <Globe class="w-3 h-3" />
                        {{ gene.source_registry_name || gene.source_registry }}
                      </span>
                      <span
                        v-else-if="gene.source_registry === 'local'"
                        class="inline-flex items-center gap-1 px-1.5 py-0.5 text-xs rounded-full bg-gray-50 text-gray-500 dark:bg-gray-800 dark:text-gray-400"
                      >
                        <HardDrive class="w-3 h-3" />
                        {{ t('gene.registryLocal') }}
                      </span>
                      <span
                        v-if="hasNativeTools(gene)"
                        class="shrink-0 bg-cyan-500/10 text-cyan-400 text-[10px] px-1.5 py-0.5 rounded"
                      >
                        {{ t('geneMarket.hasNativeTools') }}
                      </span>
                    </div>
                    <p class="text-xs text-muted-foreground line-clamp-2 mt-1">
                      {{ gene.short_description ?? gene.description ?? '' }}
                    </p>
                  </div>
                </div>
                <div class="flex flex-wrap gap-1 mt-2">
                  <span
                    v-for="tag in gene.tags.slice(0, 3)"
                    :key="tag"
                    class="text-xs px-2 py-0.5 rounded bg-primary/10 text-primary"
                  >
                    {{ localizeGeneMeta(tag) }}
                  </span>
                </div>
                <div class="flex items-center gap-3 mt-3 text-xs text-muted-foreground">
                  <span class="flex items-center gap-0.5">
                    <Star class="w-3.5 h-3.5 fill-amber-400 text-amber-400" />
                    {{ (gene.avg_rating ?? 0).toFixed(1) }}
                  </span>
                  <div class="flex-1 min-w-0">
                    <div class="h-1.5 rounded-full bg-muted overflow-hidden">
                      <div
                        class="h-full rounded-full bg-primary/60"
                        :style="{ width: `${Math.min(100, (gene.effectiveness_score ?? 0) * 100)}%` }"
                      />
                    </div>
                  </div>
                  <span class="shrink-0">{{ t('geneMarket.learnCount', { count: gene.install_count ?? 0 }) }}</span>
                </div>

                <!-- fork 按钮组：根据源 scope + 当前用户权限决定显示哪些目标按钮 -->
                <div
                  v-if="canForkFrom(gene).personal || canForkFrom(gene).org || canForkFrom(gene).public"
                  class="flex items-center gap-2 mt-3 pt-3 border-t border-border"
                >
                  <button
                    v-if="canForkFrom(gene).personal"
                    class="flex-1 inline-flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-md border border-border text-xs hover:border-primary/50 hover:text-primary transition-colors disabled:opacity-50"
                    :disabled="forkingSlug === gene.slug"
                    @click.stop="onForkGene(gene, 'personal')"
                  >
                    <Loader2 v-if="forkingSlug === gene.slug" class="w-3 h-3 animate-spin" />
                    <Download v-else class="w-3 h-3" />
                    {{ t('geneMarket.forkToPersonal') }}
                  </button>
                  <button
                    v-if="canForkFrom(gene).org"
                    class="flex-1 inline-flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-md border border-border text-xs hover:border-primary/50 hover:text-primary transition-colors disabled:opacity-50"
                    :disabled="forkingSlug === gene.slug"
                    @click.stop="onForkGene(gene, 'org')"
                  >
                    <Loader2 v-if="forkingSlug === gene.slug" class="w-3 h-3 animate-spin" />
                    <Download v-else class="w-3 h-3" />
                    {{ t('geneMarket.forkToOrg') }}
                  </button>
                  <button
                    v-if="canForkFrom(gene).public"
                    class="flex-1 inline-flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-md border border-border text-xs hover:border-primary/50 hover:text-primary transition-colors disabled:opacity-50"
                    :disabled="forkingSlug === gene.slug"
                    @click.stop="onForkGene(gene, 'public')"
                  >
                    <Loader2 v-if="forkingSlug === gene.slug" class="w-3 h-3 animate-spin" />
                    <Download v-else class="w-3 h-3" />
                    {{ t('geneMarket.forkToPublic') }}
                  </button>
                </div>
              </div>
              </template>
              <template v-else-if="viewMode === 'templates'">
              <div
                v-for="tpl in store.templates"
                :key="tpl.id"
                class="p-4 rounded-xl border border-border bg-card hover:border-primary/30 transition cursor-pointer"
                @click="goToTemplate(tpl.id)"
              >
                <div class="flex items-start gap-3 mb-2">
                  <div class="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
                    <component :is="resolveIcon(tpl.icon)" class="w-5 h-5 text-primary" />
                  </div>
                  <div class="min-w-0 flex-1">
                    <span class="font-medium truncate block">{{ tpl.name }}</span>
                    <p class="text-xs text-muted-foreground line-clamp-2 mt-1">
                      {{ tpl.short_description ?? tpl.description ?? '' }}
                    </p>
                  </div>
                </div>
                <div class="flex items-center gap-3 mt-3 text-xs text-muted-foreground">
                  <span class="flex items-center gap-1">
                    <Dna class="w-3.5 h-3.5" />
                    {{ t('template.geneCount', { count: tpl.gene_slugs?.length ?? 0 }) }}
                  </span>
                  <span class="flex items-center gap-1">
                    <Download class="w-3.5 h-3.5" />
                    {{ t('template.useCount', { count: tpl.use_count ?? 0 }) }}
                  </span>
                </div>
              </div>
              </template>
            </div>
          </section>

          <!-- ═══ 本地上传 Tab ═══ -->
          <div v-if="viewMode === 'local'" class="space-y-6">
            <div class="rounded-xl border-2 border-dashed border-blue-300 bg-blue-50 p-8">
              <div class="flex flex-col items-center gap-4">
                <FolderOpen class="w-10 h-10 text-blue-400" />
                <p class="text-sm text-gray-700 text-center font-medium">上传本地 SKILL 文件夹</p>
                <p class="text-xs text-gray-500 text-center max-w-md">
                  选择包含 <code class="bg-white px-1 rounded">SKILL.md</code> 的文件夹，系统自动解析并创建本地基因。
                  同时支持上传 ZIP 包。
                </p>

                <input
                  ref="localFolderInputRef"
                  type="file"
                  class="hidden"
                  webkitdirectory
                  multiple
                  @change="onLocalFolderInput"
                />
                <button
                  class="inline-flex items-center gap-2 rounded-lg border border-blue-300 bg-white px-4 py-2 text-sm text-blue-700 hover:bg-blue-50"
                  @click="localFolderInputRef?.click()"
                >
                  <FolderOpen class="w-4 h-4" />
                  选择文件夹
                </button>
              </div>

              <div v-if="selectedLocalFiles.length > 0" class="mt-4">
                <p class="text-xs font-medium text-gray-600 mb-2">
                  已选 {{ selectedLocalFiles.length }} 个文件：
                </p>
                <ul class="max-h-40 overflow-y-auto rounded-lg bg-white border border-gray-200 divide-y divide-gray-100">
                  <li
                    v-for="path in selectedLocalFiles"
                    :key="path"
                    class="flex items-center gap-2 px-3 py-1.5 text-xs"
                  >
                    <Code2 v-if="path.endsWith('.py')" class="w-3 h-3 text-blue-500 shrink-0" />
                    <FolderOpen v-else-if="path.includes('/')" class="w-3 h-3 text-gray-400 shrink-0" />
                    <span class="text-gray-600">{{ path }}</span>
                  </li>
                </ul>

                <!-- 上传目标库选择：personal 无需审核，org/public 需组织 admin 审核 -->
                <div class="mt-3 rounded-lg bg-white border border-gray-200 p-3">
                  <p class="text-xs font-medium text-gray-600 mb-2">上传到：</p>
                  <div class="flex flex-col gap-2">
                    <label class="flex items-start gap-2 cursor-pointer text-xs">
                      <input
                        v-model="uploadTarget"
                        type="radio"
                        value="personal"
                        class="mt-0.5"
                      />
                      <span class="text-gray-700">
                        <span class="font-medium">个人技能 library</span>
                        <span class="text-gray-500"> — 仅自己可见，立即可用</span>
                      </span>
                    </label>
                    <label class="flex items-start gap-2 cursor-pointer text-xs">
                      <input
                        v-model="uploadTarget"
                        type="radio"
                        value="org"
                        class="mt-0.5"
                      />
                      <span class="text-gray-700">
                        <span class="font-medium">组织技能 library</span>
                        <span class="text-gray-500"> — 组织内可见，需组织管理员审核</span>
                      </span>
                    </label>
                    <label class="flex items-start gap-2 cursor-pointer text-xs">
                      <input
                        v-model="uploadTarget"
                        type="radio"
                        value="public"
                        class="mt-0.5"
                      />
                      <span class="text-gray-700">
                        <span class="font-medium">公共市场</span>
                        <span class="text-gray-500"> — 所有用户可见，需组织管理员审核</span>
                      </span>
                    </label>
                  </div>
                </div>

                <div class="mt-3 flex justify-end">
                  <button
                    :disabled="localUploading"
                    class="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                    @click="handleLocalFolder"
                  >
                    <span v-if="localUploading" class="animate-spin inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full" />
                    <Upload v-else class="w-4 h-4" />
                    {{ localUploading ? '上传中...' : '确认上传' }}
                  </button>
                </div>
              </div>

              <div class="mt-4 flex flex-col items-center gap-2">
                <p class="text-xs text-gray-400">或上传 ZIP 包</p>
                <input
                  ref="localFileInputRef"
                  type="file"
                  accept=".zip"
                  class="hidden"
                  @change="(e: Event) => { const f = (e.target as HTMLInputElement).files?.[0]; if (f) handleLocalFile(f) }"
                />
                <button
                  class="inline-flex items-center gap-1.5 text-xs text-gray-500 underline underline-offset-2 hover:text-gray-700"
                  @click="localFileInputRef?.click()"
                >
                  点击选择 .zip 文件
                </button>
              </div>

              <div v-if="localUploading" class="mt-4 flex items-center gap-2 text-sm text-blue-600 justify-center">
                <span class="animate-spin inline-block w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full" />
                解析上传中...
              </div>
              <div v-if="localError" class="mt-4 flex items-start gap-2 rounded-lg bg-red-50 border border-red-200 px-4 py-3">
                <AlertTriangle class="w-4 h-4 text-red-500 shrink-0" />
                <p class="text-sm text-red-700">{{ localError }}</p>
              </div>
              <div v-if="localSuccess" class="mt-4 flex items-center gap-2 rounded-lg bg-green-50 border border-green-200 px-4 py-3">
                <Check class="w-4 h-4 text-green-500" />
                <p class="text-sm text-green-700">{{ localSuccess }}</p>
              </div>
            </div>
          </div>

          <div
            v-if="totalPages > 1"
            class="flex items-center justify-center gap-2 mt-8"
          >
            <button
              :disabled="!canPrev"
              :class="[
                'px-3 py-1.5 rounded-lg text-sm transition-colors',
                canPrev
                  ? 'text-foreground hover:bg-muted'
                  : 'text-muted-foreground cursor-not-allowed',
              ]"
              @click="page = Math.max(1, page - 1)"
            >
              {{ t('geneMarket.prevPage') }}
            </button>
            <span class="text-sm text-muted-foreground">
              {{ page }} / {{ totalPages }}
            </span>
            <button
              :disabled="!canNext"
              :class="[
                'px-3 py-1.5 rounded-lg text-sm transition-colors',
                canNext
                  ? 'text-foreground hover:bg-muted'
                  : 'text-muted-foreground cursor-not-allowed',
              ]"
              @click="page = Math.min(totalPages, page + 1)"
            >
              {{ t('geneMarket.nextPage') }}
            </button>
          </div>
        </template>
    </div>
  </div>
</template>