<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useOrgStore } from '@/stores/org'
import { Settings, Users, Dna, FolderOpen, Mail, Server, Building2, Container, ScrollText, Globe, Cpu, Layers, KeyRound } from 'lucide-vue-next'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const orgStore = useOrgStore()

interface NavItem {
  name: string
  label: () => string
  icon: typeof Settings
  matchPrefix?: string
}

// 组织设置侧边栏导航项；EE/CE 现已共享同一份菜单（集群/Registry/SMTP 等不再 CE 独占）
const allNavItems: NavItem[] = [
  { name: 'OrgInfo', label: () => t('orgSettings.orgInfo'), icon: Building2 },
  { name: 'OrgSettingsClusters', label: () => t('orgSettings.clusters'), icon: Server },
  { name: 'OrgSettingsRegistry', label: () => t('orgSettings.registryTitle'), icon: Container },
  { name: 'OrgSettingsEngineVersions', label: () => t('orgSettings.engineVersionsTab'), icon: Layers },
  { name: 'OrgSettingsSpecs', label: () => t('orgSettings.specsTab'), icon: Cpu },
  { name: 'OrgMembers', label: () => t('orgSettings.humanMembers'), icon: Users },
  { name: 'OrgSettingsLlmKeys', label: () => t('orgSettings.llmKeysTab'), icon: KeyRound },
  { name: 'OrgSettingsGenes', label: () => t('orgSettings.requiredGenesTab'), icon: Dna },
  { name: 'OrgSettingsSmtp', label: () => t('orgSettings.smtpTitle'), icon: Mail },
  { name: 'OrgSettingsNetwork', label: () => t('orgSettings.networkTab'), icon: Globe },
  { name: 'OrgEnterpriseFiles', label: () => t('enterpriseFiles.title'), icon: FolderOpen, matchPrefix: '/org-settings/files' },
  { name: 'OrgSettingsAudit', label: () => t('auditLogs.title'), icon: ScrollText },
]

// 仅根据"路由是否真实存在"做过滤，避免渲染 EE 端未注册的路由（如 OrgEnterpriseFiles）
const navItems = computed(() =>
  allNavItems.filter(item => router.hasRoute(item.name))
)

function isActive(item: NavItem): boolean {
  if (item.matchPrefix) return route.path.startsWith(item.matchPrefix)
  return route.name === item.name
}

onMounted(async () => {
  if (!orgStore.currentOrg) await orgStore.fetchMyOrg()
})
</script>

<template>
  <div class="flex flex-col h-[calc(100vh-3.5rem)] max-w-4xl mx-auto px-6">
    <div class="shrink-0 flex items-center gap-3 pt-8 pb-4">
      <Settings class="w-6 h-6 text-primary" />
      <h1 class="text-xl font-bold">{{ t('orgSettings.title') }}</h1>
    </div>

    <div class="flex gap-6 flex-1 min-h-0 pb-8">
      <nav class="w-40 shrink-0 space-y-1">
        <router-link
          v-for="item in navItems"
          :key="item.name"
          :to="{ name: item.name }"
          class="flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors"
          :class="isActive(item)
            ? 'bg-primary/10 text-primary font-medium'
            : 'text-muted-foreground hover:text-foreground hover:bg-muted/50'"
        >
          <component :is="item.icon" class="w-4 h-4" />
          {{ item.label() }}
        </router-link>
      </nav>

      <div class="flex-1 min-w-0 overflow-y-auto pr-3">
        <div class="pb-4">
          <router-view />
        </div>
      </div>
    </div>
  </div>
</template>
