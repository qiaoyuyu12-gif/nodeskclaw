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
} from 'lucide-vue-next'
import { useGeneStore } from '@/stores/gene'
import type { GeneItem, GenomeItem, TemplateInfo } from '@/stores/gene'
import { useToast } from '@/composables/useToast'
import CustomSelect from '@/components/shared/CustomSelect.vue'
import { skillApi } from '@/services/skills'

const router = useRouter()
const store = useGeneStore()
const toast = useToast()
const { t, locale } = useI18n()

const viewMode = ref<'genes' | 'genomes' | 'templates' | 'evolution' | 'local'>('genes')
const keyword = ref('')
const selectedTag = ref<string | null>(null)
const selectedCategory = ref<string | null>(null)
const selectedVisibility = ref<string | null>(null)
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

async function handleLocalFile(file: File) {
  if (!file.name.endsWith('.zip')) {
    localError.value = '请上传 .zip 格式的技能包'
    return
  }
  localUploading.value = true
  localError.value = null
  localSuccess.value = null
  try {
    const res = await api.post('/genes/upload-folder', toFormData([file]))
    localSuccess.value = `本地基因「${res.data.data?.name}」上传成功`
    await loadData()
  } catch (e: unknown) {
    localError.value = e instanceof Error ? e.message : '上传失败'
  } finally {
    localUploading.value = false
  }
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
    await skillApi.uploadFolder(input.files)
    localSuccess.value = `本地基因上传成功`
    showLocalUpload.value = false
    selectedLocalFiles.value = []
    await loadData()
  } catch (e: unknown) {
    localError.value = e instanceof Error ? e.message : '上传失败'
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

function toFormData(files: File[]): FormData {
  const form = new FormData()
  for (const file of files) {
    form.append('files', file, file.name)
  }
  return form
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
  if (viewMode.value === 'genomes') return store.featuredGenomes
  return []
})

const hasFeatured = computed(() => featuredItems.value.length > 0 && selectedVisibility.value !== 'org_private')

const totalCount = computed(() => {
  if (viewMode.value === 'genes') return store.totalGenes
  if (viewMode.value === 'genomes') return store.totalGenomes
  if (viewMode.value === 'templates') return store.totalTemplates
  return 0
})

const totalPages = computed(() => Math.ceil(totalCount.value / pageSize.value) || 1)
const canPrev = computed(() => page.value > 1)
const canNext = computed(() => page.value < totalPages.value)

async function loadData() {
  if (viewMode.value === 'genes') {
    await store.fetchGenes({
      keyword: keyword.value || undefined,
      tag: selectedTag.value || undefined,
      category: selectedCategory.value || undefined,
      visibility: selectedVisibility.value || undefined,
      sort: sortBy.value,
      page: page.value,
      page_size: pageSize.value,
    })
  } else if (viewMode.value === 'genomes') {
    await store.fetchGenomes({
      keyword: keyword.value || undefined,
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
  } else if (viewMode.value === 'genomes') {
    await store.fetchFeaturedGenomes()
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

let keywordTimer: ReturnType<typeof setTimeout> | null = null

watch(keyword, () => {
  if (keywordTimer) clearTimeout(keywordTimer)
  keywordTimer = setTimeout(() => {
    page.value = 1
    loadData()
  }, 300)
})

watch([viewMode, selectedTag, selectedCategory, selectedVisibility, sortBy], () => {
  page.value = 1
  if (viewMode.value === 'evolution') {
    loadEvolution()
  } else if (viewMode.value === 'templates') {
    loadData()
  } else {
    loadFeatured()
    loadData()
  }
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
  <div class="flex flex-col h-[calc(100vh-3.5rem)] bg-background text-foreground">
    <div class="shrink-0 border-b border-border">
      <div class="max-w-6xl mx-auto px-6 pt-8 pb-4">
        <h1 class="text-2xl font-bold mb-4">{{ t('geneMarket.title') }}</h1>

        <div class="flex flex-wrap items-center gap-2">
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
              viewMode === 'genomes'
                ? 'bg-primary/10 text-primary'
                : 'text-muted-foreground hover:text-foreground hover:bg-muted',
            ]"
            @click="viewMode = 'genomes'"
          >
            {{ t('geneMarket.tabGenomes') }}
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
              viewMode === 'evolution'
                ? 'bg-primary/10 text-primary'
                : 'text-muted-foreground hover:text-foreground hover:bg-muted',
            ]"
            @click="viewMode = 'evolution'"
          >
            {{ t('geneMarket.tabEvolution') }}
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
      </div>
    </div>

    <div class="flex-1 min-h-0 overflow-y-auto">
      <div class="max-w-6xl mx-auto px-6 pt-6 pb-8">

      <!-- 进化趋势 Tab -->
      <template v-if="viewMode === 'evolution'">
        <div v-if="evoLoading" class="flex items-center justify-center py-24">
          <Loader2 class="w-8 h-8 animate-spin text-muted-foreground" />
        </div>
        <template v-else>
          <div class="grid grid-cols-2 md:grid-cols-5 gap-4 mb-8">
            <div class="rounded-xl border border-border bg-card p-4">
              <div class="flex items-center gap-2 text-muted-foreground mb-1">
                <Dna class="w-4 h-4" />
                <span class="text-sm">{{ t('geneMarket.evoTotalGenes') }}</span>
              </div>
              <div class="text-2xl font-bold">{{ evoStats?.total_genes ?? 0 }}</div>
            </div>
            <div class="rounded-xl border border-border bg-card p-4">
              <div class="flex items-center gap-2 text-muted-foreground mb-1">
                <Download class="w-4 h-4" />
                <span class="text-sm">{{ t('geneMarket.evoTotalInstalls') }}</span>
              </div>
              <div class="text-2xl font-bold">{{ evoStats?.total_installs ?? 0 }}</div>
            </div>
            <div class="rounded-xl border border-border bg-card p-4">
              <div class="flex items-center gap-2 text-muted-foreground mb-1">
                <TrendingUp class="w-4 h-4" />
                <span class="text-sm">{{ t('geneMarket.evoLearning') }}</span>
              </div>
              <div class="text-2xl font-bold">{{ evoStats?.learning_count ?? 0 }}</div>
            </div>
            <div class="rounded-xl border border-border bg-card p-4">
              <div class="flex items-center gap-2 text-muted-foreground mb-1">
                <AlertCircle class="w-4 h-4" />
                <span class="text-sm">{{ t('geneMarket.evoFailed') }}</span>
              </div>
              <div class="text-2xl font-bold">{{ evoStats?.failed_count ?? 0 }}</div>
            </div>
            <div class="rounded-xl border border-border bg-card p-4">
              <div class="flex items-center gap-2 text-muted-foreground mb-1">
                <Sparkles class="w-4 h-4" />
                <span class="text-sm">{{ t('geneMarket.evoAgentCreated') }}</span>
              </div>
              <div class="text-2xl font-bold">{{ evoStats?.agent_created_count ?? 0 }}</div>
            </div>
          </div>

          <div class="grid md:grid-cols-2 gap-6 mb-8">
            <div class="rounded-xl border border-border bg-card overflow-hidden">
              <div class="px-4 py-3 border-b border-border">
                <h2 class="font-semibold">{{ t('geneMarket.evoHotGenes') }}</h2>
              </div>
              <div class="divide-y divide-border max-h-[320px] overflow-y-auto">
                <div
                  v-for="(g, i) in evoHotGenes"
                  :key="g.id"
                  class="px-4 py-3 flex items-center justify-between gap-4 cursor-pointer hover:bg-muted/50 transition-colors"
                  @click="goToGene(g.slug)"
                >
                  <span class="text-muted-foreground w-6">{{ i + 1 }}</span>
                  <div class="min-w-0 flex-1">
                    <div class="flex items-center gap-2">
                      <span class="font-medium truncate">{{ g.name }}</span>
                      <span
                        v-if="hasNativeTools(g)"
                        class="shrink-0 bg-cyan-500/10 text-cyan-400 text-[10px] px-1.5 py-0.5 rounded"
                      >
                        {{ t('geneMarket.hasNativeTools') }}
                      </span>
                    </div>
                    <div class="text-xs text-muted-foreground">{{ g.slug }}</div>
                  </div>
                  <div class="shrink-0">
                    <div class="text-sm font-medium">{{ Math.round((g.effectiveness_score ?? 0) * 100) }}%</div>
                    <div class="w-16 h-1.5 rounded-full bg-muted overflow-hidden">
                      <div
                        class="h-full rounded-full bg-primary"
                        :style="{ width: `${Math.min(100, (g.effectiveness_score ?? 0) * 100)}%` }"
                      />
                    </div>
                  </div>
                </div>
                <div v-if="evoHotGenes.length === 0" class="px-4 py-8 text-center text-muted-foreground text-sm">
                  {{ t('geneMarket.evoNoData') }}
                </div>
              </div>
            </div>

            <div class="rounded-xl border border-border bg-card overflow-hidden">
              <div class="px-4 py-3 border-b border-border flex items-center gap-2">
                <Activity class="w-4 h-4" />
                <h2 class="font-semibold">{{ t('geneMarket.evoActivity') }}</h2>
              </div>
              <div class="divide-y divide-border max-h-[320px] overflow-y-auto">
                <div v-if="evoActivityLoading" class="px-4 py-8 flex justify-center">
                  <Loader2 class="w-6 h-6 animate-spin text-muted-foreground" />
                </div>
                <div
                  v-else
                  v-for="a in evoActivity"
                  :key="a.id"
                  class="px-4 py-2.5 text-sm"
                >
                  <span class="font-medium">{{ a.gene_name }}</span>
                  <span class="text-muted-foreground mx-1">{{ formatMetricType(a.metric_type) }}</span>
                  <span class="text-muted-foreground">{{ formatDate(a.created_at) }}</span>
                </div>
                <div v-if="!evoActivityLoading && evoActivity.length === 0" class="px-4 py-8 text-center text-muted-foreground text-sm">
                  {{ t('geneMarket.evoNoActivity') }}
                </div>
              </div>
            </div>
          </div>

          <div class="rounded-xl border border-border bg-card overflow-hidden">
            <div class="px-4 py-3 border-b border-border">
              <h2 class="font-semibold">{{ t('geneMarket.evoPendingReview') }}</h2>
            </div>
            <div v-if="evoPendingLoading" class="px-4 py-8 flex justify-center">
              <Loader2 class="w-6 h-6 animate-spin text-muted-foreground" />
            </div>
            <div v-else-if="evoPending.length === 0" class="px-4 py-8 text-center text-muted-foreground text-sm">
              {{ t('geneMarket.evoNoPending') }}
            </div>
            <div v-else class="divide-y divide-border">
              <div
                v-for="g in evoPending"
                :key="g.id"
                class="px-4 py-3 flex items-center justify-between gap-4"
              >
                <div class="min-w-0 flex-1">
                  <div class="font-medium">{{ g.name }}</div>
                  <div class="text-sm text-muted-foreground">{{ g.slug }} · {{ g.review_status }}</div>
                </div>
                <div class="flex items-center gap-2 shrink-0">
                  <button
                    class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm bg-green-500/10 text-green-600 hover:bg-green-500/20 disabled:opacity-50"
                    :disabled="evoReviewingId === g.id"
                    @click="handleReview(g.id, 'approve')"
                  >
                    <Loader2 v-if="evoReviewingId === g.id" class="w-4 h-4 animate-spin" />
                    <Check v-else class="w-4 h-4" />
                    {{ t('geneMarket.approve') }}
                  </button>
                  <button
                    class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm bg-red-500/10 text-red-600 hover:bg-red-500/20 disabled:opacity-50"
                    :disabled="evoReviewingId === g.id"
                    @click="handleReview(g.id, 'reject')"
                  >
                    <X class="w-4 h-4" />
                    {{ t('geneMarket.reject') }}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </template>
      </template>

      <!-- 基因/基因组 Tab -->
      <template v-else>

      <!-- Visibility filter -->
      <div v-if="viewMode === 'genes' || viewMode === 'templates'" class="flex gap-2 mb-4">
        <button
          v-for="vis in [
            { value: null, key: 'geneMarket.visAll' },
            { value: 'public', key: 'geneMarket.visPublic' },
            { value: 'org_private', key: 'geneMarket.visOrg' },
          ]"
          :key="String(vis.value)"
          :class="[
            'px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
            selectedVisibility === vis.value
              ? 'bg-primary/10 text-primary'
              : 'bg-muted/50 text-muted-foreground hover:text-foreground hover:bg-muted',
          ]"
          @click="selectedVisibility = vis.value"
        >
          {{ t(vis.key) }}
        </button>
      </div>

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

        <div v-if="viewMode === 'genes'" class="flex flex-wrap gap-2">
          <button
            v-for="t in store.tagStats"
            :key="t.tag"
            :class="[
              'px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
              selectedTag === t.tag
                ? 'bg-primary/10 text-primary'
                : 'bg-muted/50 text-muted-foreground hover:text-foreground hover:bg-muted',
            ]"
            @click="selectedTag = selectedTag === t.tag ? null : t.tag"
          >
            {{ localizeGeneMeta(t.tag) }}
          </button>
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
                class="p-4 rounded-xl border border-border bg-card hover:border-primary/30 transition cursor-pointer"
                @click="goToGene(gene.slug)"
              >
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
              </div>
            </template>
            <template v-else-if="viewMode === 'genomes'">
              <div
                v-for="genome in store.genomes"
                :key="genome.id"
                class="p-4 rounded-xl border border-border bg-card hover:border-primary/30 transition cursor-pointer"
                @click="goToGenome(genome.id)"
              >
              <div class="flex items-start gap-3 mb-2">
                <div class="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
                  <component :is="resolveIcon(genome.icon)" class="w-5 h-5 text-primary" />
                </div>
                <div class="min-w-0 flex-1">
                  <div class="flex items-center gap-2 flex-wrap">
                    <span class="font-medium truncate">{{ genome.name }}</span>
                    <span
                      v-if="genome.native_tool_count"
                      class="shrink-0 inline-flex items-center gap-1 bg-cyan-500/10 text-cyan-400 text-[10px] px-1.5 py-0.5 rounded"
                    >
                      <Wrench class="w-3 h-3" />
                      {{ t('genome.nativeToolCount', { count: genome.native_tool_count }) }}
                    </span>
                    <span
                      v-if="genome.mcp_server_count"
                      class="shrink-0 inline-flex items-center gap-1 bg-violet-500/10 text-violet-400 text-[10px] px-1.5 py-0.5 rounded"
                    >
                      <Server class="w-3 h-3" />
                      {{ t('genome.mcpServerCount', { count: genome.mcp_server_count }) }}
                    </span>
                  </div>
                  <p class="text-xs text-muted-foreground line-clamp-2 mt-1">
                    {{ genome.short_description ?? genome.description ?? '' }}
                  </p>
                </div>
              </div>
              <div class="flex items-center gap-3 mt-3 text-xs text-muted-foreground">
                <span class="flex items-center gap-0.5">
                  <Star class="w-3.5 h-3.5 fill-amber-400 text-amber-400" />
                  {{ (genome.avg_rating ?? 0).toFixed(1) }}
                </span>
                <span class="shrink-0">{{ t('geneMarket.learnCount', { count: genome.install_count ?? 0 }) }}</span>
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
          <!-- 本地上传区域 -->
          <div class="rounded-xl border-2 border-dashed border-blue-300 bg-blue-50 p-8">
            <div class="flex flex-col items-center gap-4">
              <FolderOpen class="w-10 h-10 text-blue-400" />
              <p class="text-sm text-gray-700 text-center font-medium">上传本地 SKILL 文件夹</p>
              <p class="text-xs text-gray-500 text-center max-w-md">
                选择包含 <code class="bg-white px-1 rounded">SKILL.md</code> 的文件夹，系统自动解析并创建本地基因。
                同时支持上传 ZIP 包。
              </p>

              <!-- 文件夹选择 -->
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

            <!-- 已选文件预览 + 确认上传 -->
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

            <!-- ZIP 上传（备用） -->
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
              <Check class="w-4 h-4 text-green-500 shrink-0" />
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
      </template>
      </div>
    </div>
  </div>
</template>
