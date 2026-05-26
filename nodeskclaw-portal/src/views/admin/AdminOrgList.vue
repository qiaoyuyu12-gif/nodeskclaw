<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAdminApi } from '@/services/adminApi'
import { useToast } from '@/composables/useToast'
import { useFeature } from '@/composables/useFeature'
import { resolveApiErrorMessage } from '@/i18n/error'
import { Building2, Plus, Pencil, Trash2, Loader2, Search, X, Check } from 'lucide-vue-next'

const { t } = useI18n()
const toast = useToast()
const { isEnabled: platformAdminEnabled } = useFeature('platform_admin')
const { fetchOrgs, createOrg, updateOrg, deleteOrg } = useAdminApi()

const loading = ref(true)
const orgs = ref<Awaited<ReturnType<typeof fetchOrgs>>>([])
const search = ref('')
const showCreate = ref(false)
const createLoading = ref(false)
const deleteConfirm = ref<string | null>(null)
const deleteLoading = ref(false)

const form = ref({
  name: '',
  slug: '',
  plan: 'free',
  max_instances: 1,
  max_cpu_total: '4',
  max_mem_total: '8Gi',
  max_storage_total: '500Gi',
  max_collaboration_depth: 3,
  cluster_id: null as string | null,
})

const filteredOrgs = computed(() => {
  if (!search.value) return orgs.value
  const q = search.value.toLowerCase()
  return orgs.value.filter(
    o => o.name.toLowerCase().includes(q) || o.slug.toLowerCase().includes(q),
  )
})

function resetForm() {
  form.value = { name: '', slug: '', plan: 'free', max_instances: 1, max_cpu_total: '4', max_mem_total: '8Gi', max_storage_total: '500Gi', max_collaboration_depth: 3, cluster_id: null }
}

function cancelCreate() {
  showCreate.value = false
  resetForm()
}

async function submitCreate() {
  if (!form.value.name.trim() || !form.value.slug.trim()) {
    toast.warning(t('admin.orgs.nameAndSlugRequired'))
    return
  }
  createLoading.value = true
  try {
    const newOrg = await createOrg(form.value)
    orgs.value.push(newOrg)
    toast.success(t('admin.orgs.created'))
    showCreate.value = false
    resetForm()
  } catch (e: unknown) {
    toast.error(resolveApiErrorMessage(e, t('admin.orgs.createFailed')))
  } finally {
    createLoading.value = false
  }
}

async function submitDelete() {
  if (!deleteConfirm.value) return
  deleteLoading.value = true
  try {
    await deleteOrg(deleteConfirm.value)
    orgs.value = orgs.value.filter(o => o.id !== deleteConfirm.value)
    toast.success(t('admin.orgs.deleted'))
    deleteConfirm.value = null
  } catch (e: unknown) {
    toast.error(resolveApiErrorMessage(e, t('admin.orgs.deleteFailed')))
  } finally {
    deleteLoading.value = false
  }
}

function formatDate(iso: string | undefined): string {
  if (!iso) return '-'
  return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

onMounted(async () => {
  try {
    orgs.value = await fetchOrgs()
  } catch (e: unknown) {
    toast.error(resolveApiErrorMessage(e, t('admin.orgs.loadFailed')))
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="space-y-5">
    <div class="flex items-center justify-between">
      <div>
        <h2 class="text-lg font-semibold">{{ t('admin.orgs.title') }}</h2>
        <p class="text-sm text-muted-foreground mt-0.5">{{ t('admin.orgs.subtitle') }}</p>
      </div>
      <button
        class="flex items-center gap-2 h-9 px-4 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors"
        @click="showCreate = true; resetForm()"
      >
        <Plus class="w-4 h-4" />
        {{ t('admin.orgs.create') }}
      </button>
    </div>

    <div class="relative">
      <Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
      <input
        v-model="search"
        type="text"
        :placeholder="t('admin.orgs.searchPlaceholder')"
        class="h-9 w-full pl-9 pr-3 rounded-lg border border-border bg-background text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
      />
      <button v-if="search" class="absolute right-3 top-1/2 -translate-y-1/2" @click="search = ''">
        <X class="w-4 h-4 text-muted-foreground" />
      </button>
    </div>

    <div v-if="loading" class="flex items-center justify-center py-16">
      <Loader2 class="w-5 h-5 animate-spin text-muted-foreground" />
    </div>

    <div v-else class="rounded-xl border border-border overflow-hidden">
      <table class="w-full text-sm">
        <thead>
          <tr class="border-b border-border bg-muted/40">
            <th class="text-left font-medium text-muted-foreground px-4 py-3">{{ t('admin.orgs.colName') }}</th>
            <th class="text-left font-medium text-muted-foreground px-4 py-3 hidden md:table-cell">{{ t('admin.orgs.colSlug') }}</th>
            <th class="text-left font-medium text-muted-foreground px-4 py-3 hidden lg:table-cell">{{ t('admin.orgs.colPlan') }}</th>
            <th class="text-right font-medium text-muted-foreground px-4 py-3">{{ t('admin.orgs.colInstances') }}</th>
            <th class="text-right font-medium text-muted-foreground px-4 py-3 hidden sm:table-cell">{{ t('admin.orgs.colCreated') }}</th>
            <th class="text-right font-medium text-muted-foreground px-4 py-3">{{ t('admin.common.actions') }}</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-border">
          <tr v-for="org in filteredOrgs" :key="org.id" class="hover:bg-muted/20 transition-colors">
            <td class="px-4 py-3">
              <div class="flex items-center gap-2">
                <Building2 class="w-4 h-4 text-muted-foreground shrink-0" />
                <span class="font-medium">{{ org.name }}</span>
                <span v-if="!org.is_active" class="inline-flex items-center px-1.5 py-0.5 rounded text-xs bg-red-500/15 text-red-400">
                  {{ t('admin.orgs.inactive') }}
                </span>
              </div>
            </td>
            <td class="px-4 py-3 hidden md:table-cell">
              <span class="font-mono text-xs text-muted-foreground">{{ org.slug }}</span>
            </td>
            <td class="px-4 py-3 hidden lg:table-cell">
              <span class="px-2 py-0.5 rounded text-xs bg-muted font-medium">{{ org.plan }}</span>
            </td>
            <td class="px-4 py-3 text-right">
              <span class="font-mono">{{ org.instance_count }}</span>
              <span class="text-muted-foreground"> / {{ org.max_instances }}</span>
            </td>
            <td class="px-4 py-3 text-right text-muted-foreground hidden sm:table-cell">
              {{ formatDate(org.created_at) }}
            </td>
            <td class="px-4 py-3 text-right">
              <div class="flex items-center justify-end gap-1">
                <button class="p-1.5 rounded hover:bg-muted/60 text-muted-foreground hover:text-foreground transition-colors" :title="t('admin.common.edit')">
                  <Pencil class="w-3.5 h-3.5" />
                </button>
                <button class="p-1.5 rounded hover:bg-red-500/10 text-muted-foreground hover:text-red-400 transition-colors" :title="t('admin.common.delete')" @click="deleteConfirm = org.id">
                  <Trash2 class="w-3.5 h-3.5" />
                </button>
              </div>
            </td>
          </tr>
          <tr v-if="filteredOrgs.length === 0">
            <td colspan="6" class="px-4 py-12 text-center text-muted-foreground">
              {{ search ? t('admin.orgs.noResults') : t('admin.orgs.empty') }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Create Dialog -->
    <div v-if="showCreate" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div class="w-full max-w-md rounded-xl border border-border bg-card shadow-xl">
        <div class="flex items-center justify-between px-5 py-4 border-b border-border">
          <h3 class="font-semibold">{{ t('admin.orgs.createTitle') }}</h3>
          <button class="p-1 rounded hover:bg-muted/60" @click="cancelCreate">
            <X class="w-4 h-4" />
          </button>
        </div>
        <div class="px-5 py-4 space-y-4">
          <div>
            <label class="block text-sm font-medium mb-1.5">{{ t('admin.orgs.name') }} *</label>
            <input v-model="form.name" type="text" class="h-9 w-full px-3 rounded-lg border border-border bg-background text-sm focus:outline-none focus:ring-1 focus:ring-primary" :placeholder="t('admin.orgs.namePlaceholder')" />
          </div>
          <div>
            <label class="block text-sm font-medium mb-1.5">{{ t('admin.orgs.slug') }} *</label>
            <input v-model="form.slug" type="text" class="h-9 w-full px-3 rounded-lg border border-border bg-background text-sm font-mono focus:outline-none focus:ring-1 focus:ring-primary" :placeholder="t('admin.orgs.slugPlaceholder')" />
          </div>
          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="block text-sm font-medium mb-1.5">{{ t('admin.orgs.plan') }}</label>
              <input v-model="form.plan" type="text" class="h-9 w-full px-3 rounded-lg border border-border bg-background text-sm focus:outline-none focus:ring-1 focus:ring-primary" />
            </div>
            <div>
              <label class="block text-sm font-medium mb-1.5">{{ t('admin.orgs.maxInstances') }}</label>
              <input v-model.number="form.max_instances" type="number" min="1" class="h-9 w-full px-3 rounded-lg border border-border bg-background text-sm focus:outline-none focus:ring-1 focus:ring-primary" />
            </div>
          </div>
        </div>
        <div class="flex items-center justify-end gap-2 px-5 py-4 border-t border-border">
          <button class="h-9 px-4 rounded-lg border border-border text-sm hover:bg-muted/50 transition-colors" @click="cancelCreate">
            {{ t('admin.common.cancel') }}
          </button>
          <button class="h-9 px-4 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors disabled:opacity-50" :disabled="createLoading" @click="submitCreate">
            <Loader2 v-if="createLoading" class="w-4 h-4 animate-spin" />
            <template v-else><Check class="w-4 h-4 inline mr-1" />{{ t('admin.common.create') }}</template>
          </button>
        </div>
      </div>
    </div>

    <!-- Delete Confirm -->
    <div v-if="deleteConfirm" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div class="w-full max-w-sm rounded-xl border border-border bg-card shadow-xl">
        <div class="px-5 py-4 border-b border-border">
          <h3 class="font-semibold">{{ t('admin.orgs.deleteTitle') }}</h3>
        </div>
        <div class="px-5 py-4">
          <p class="text-sm text-muted-foreground">{{ t('admin.orgs.deleteConfirm') }}</p>
        </div>
        <div class="flex items-center justify-end gap-2 px-5 py-4 border-t border-border">
          <button class="h-9 px-4 rounded-lg border border-border text-sm hover:bg-muted/50 transition-colors" @click="deleteConfirm = null">
            {{ t('admin.common.cancel') }}
          </button>
          <button class="h-9 px-4 rounded-lg bg-red-500 text-white text-sm font-medium hover:bg-red-600 transition-colors disabled:opacity-50" :disabled="deleteLoading" @click="submitDelete">
            <Loader2 v-if="deleteLoading" class="w-4 h-4 animate-spin" />
            <template v-else>{{ t('admin.common.delete') }}</template>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>