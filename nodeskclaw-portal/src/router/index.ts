import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { i18n } from '@/i18n'
import { eePortalRoutes, eeOrgSettingsChildren } from '@/router/ee-stub'

const ceRoutes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('@/views/Register.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/force-change-password',
    name: 'ForceChangePassword',
    component: () => import('@/views/ForceChangePassword.vue'),
    meta: { requiresAuth: true, hideNav: true },
  },
  {
    path: '/',
    name: 'WorkspaceList',
    component: () => import('@/views/WorkspaceList.vue'),
    meta: { requireFeature: 'workspace' },
  },
  {
    path: '/workspace/create',
    name: 'CreateWorkspace',
    component: () => import('@/views/CreateWorkspace.vue'),
    meta: { requiredOrgRole: 'operator' },
  },
  {
    path: '/workspace/:id',
    name: 'WorkspaceView',
    component: () => import('@/views/WorkspaceView.vue'),
    meta: { hideNav: true },
  },
  {
    path: '/workspace/:id/settings',
    redirect: (to) => `/workspace/${to.params.id}`,
  },
  {
    path: '/instances',
    name: 'InstanceList',
    component: () => import('@/views/InstanceList.vue'),
    meta: { requireFeature: 'instance' },
  },
  {
    path: '/instances/create',
    name: 'CreateInstance',
    component: () => import('@/views/CreateInstance.vue'),
    meta: { requiredOrgRole: 'operator' },
  },
  {
    path: '/instances/deploy/:deployId',
    name: 'DeployProgress',
    component: () => import('@/views/DeployProgress.vue'),
  },
  {
    path: '/instances/:id/chat',
    name: 'InstanceChat',
    component: () => import('@/views/InstanceChat.vue'),
  },
  {
    path: '/instances/:id',
    component: () => import('@/views/InstanceLayout.vue'),
    children: [
      { path: '', name: 'InstanceDetail', component: () => import('@/views/InstanceDetail.vue') },
      { path: 'runtime', name: 'InstanceRuntime', component: () => import('@/views/InstanceRuntime.vue') },
      { path: 'genes', name: 'InstanceGenes', component: () => import('@/views/InstanceGenes.vue') },
      { path: 'evolution', name: 'EvolutionLog', component: () => import('@/views/EvolutionLog.vue') },

      { path: 'channels', name: 'InstanceChannels', component: () => import('@/views/InstanceChannels.vue') },
      { path: 'settings', name: 'InstanceSettings', component: () => import('@/views/InstanceSettings.vue') },
      { path: 'knowledge-bases', name: 'InstanceKnowledgeBase', component: () => import('@/views/InstanceKnowledgeBase.vue') },
      { path: 'files', name: 'InstanceFiles', component: () => import('@/views/InstanceFiles.vue') },
      { path: 'backups', name: 'InstanceBackups', component: () => import('@/views/InstanceBackups.vue') },
      { path: 'members', name: 'InstanceMembers', component: () => import('@/views/InstanceMembers.vue') },
    ],
  },
  {
    path: '/settings',
    name: 'Settings',
    component: () => import('@/views/Settings.vue'),
  },
  {
    path: '/org-settings',
    component: () => import('@/views/OrgSettings.vue'),
    redirect: { name: 'OrgInfo' },
    children: [
      { path: 'info', name: 'OrgInfo', component: () => import('@/views/OrgInfo.vue') },
      { path: 'clusters', name: 'OrgSettingsClusters', component: () => import('@/views/OrgSettingsClusters.vue'), meta: { requiredOrgRole: 'operator' } },
      { path: 'registry', name: 'OrgSettingsRegistry', component: () => import('@/views/OrgSettingsRegistry.vue'), meta: { requiredOrgRole: 'operator' } },
      { path: 'engine-versions', name: 'OrgSettingsEngineVersions', component: () => import('@/views/OrgSettingsEngineVersions.vue'), meta: { requiredOrgRole: 'operator' } },
      { path: 'specs', name: 'OrgSettingsSpecs', component: () => import('@/views/OrgSettingsSpecs.vue'), meta: { requiredOrgRole: 'operator' } },
      { path: 'genes', name: 'OrgSettingsGenes', component: () => import('@/views/OrgSettingsGenes.vue'), meta: { requiredOrgRole: 'operator' } },
      { path: 'llm-keys', name: 'OrgSettingsLlmKeys', component: () => import('@/views/OrgSettingsLlmKeys.vue'), meta: { requiredOrgRole: 'operator' } },
      { path: 'llm-analytics', name: 'OrgSettingsLlmAnalytics', component: () => import('@/views/OrgSettingsLlmAnalytics.vue'), meta: { requiresAuth: true, requireFeature: 'llm_analytics', requiredOrgRole: 'admin' } },
      { path: 'smtp', name: 'OrgSettingsSmtp', component: () => import('@/views/OrgSettingsSmtp.vue'), meta: { requiredOrgRole: 'operator' } },
      { path: 'network', name: 'OrgSettingsNetwork', component: () => import('@/views/OrgSettingsNetwork.vue'), meta: { requiredOrgRole: 'operator' } },
      { path: 'members', name: 'OrgMembers', component: () => import('@/views/OrgMembers.vue') },
      { path: 'audit', name: 'OrgSettingsAudit', component: () => import('@/views/OrgSettingsAudit.vue'), meta: { requiredOrgRole: 'admin' } },
      ...eeOrgSettingsChildren,
    ],
  },
  {
    path: '/clusters/:id',
    name: 'ClusterDetail',
    component: () => import('@/views/ClusterDetail.vue'),
  },
  {
    path: '/members',
    redirect: '/org-settings',
  },
  {
    path: '/automation',
    name: 'Automation',
    component: () => import('@/views/AutomationView.vue'),
    meta: { requiresAuth: true, requireFeature: 'automation' },
  },
  {
    path: '/gene-market',
    name: 'GeneMarket',
    component: () => import('@/views/GeneMarket.vue'),
    meta: { requireFeature: 'gene_market' },
  },
  {
    path: '/gene-market/gene/:slug',
    name: 'GeneDetail',
    component: () => import('@/views/GeneDetail.vue'),
  },
  {
    path: '/gene-market/genome/:id',
    name: 'GenomeDetail',
    component: () => import('@/views/GenomeDetail.vue'),
  },
  {
    path: '/gene-market/template/:id',
    name: 'TemplateDetail',
    component: () => import('@/views/TemplateDetail.vue'),
  },
  {
    path: '/admin/knowledge-bases',
    name: 'AdminKnowledgeBaseList',
    component: () => import('@/views/skills/admin/KnowledgeBaseListView.vue'),
    meta: { requiresAuth: true, requireFeature: 'knowledge_base' },
  },
  {
    path: '/admin/knowledge-bases/new',
    name: 'AdminKnowledgeBaseNew',
    component: () => import('@/views/skills/admin/KnowledgeBaseFormView.vue'),
    meta: { requiresAuth: true, requiredOrgRole: 'operator' },
  },
  {
    path: '/admin/knowledge-bases/:id/edit',
    name: 'AdminKnowledgeBaseEdit',
    component: () => import('@/views/skills/admin/KnowledgeBaseFormView.vue'),
    meta: { requiresAuth: true, requiredOrgRole: 'operator' },
  },
  // 外部专用 Agent 模块
  {
    path: '/agents',
    name: 'ExternalAgentList',
    component: () => import('@/views/external-agents/ExternalAgentList.vue'),
    meta: { requiresAuth: true, requireFeature: 'external_agent' },
  },
  {
    path: '/agents/:id/chat',
    name: 'ExternalAgentChat',
    component: () => import('@/views/external-agents/ExternalAgentChat.vue'),
    meta: { requiresAuth: true, hideNav: true },
  },
  {
    path: '/org-settings/external-agents/new',
    name: 'ExternalAgentNew',
    component: () => import('@/views/external-agents/ExternalAgentFormView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/org-settings/external-agents/:id/edit',
    name: 'ExternalAgentEdit',
    component: () => import('@/views/external-agents/ExternalAgentFormView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/admin',
    component: () => import('@/views/admin/AdminLayout.vue'),
    meta: { requiresAuth: true, requireSuperAdmin: true },
    children: [
      { path: '', redirect: '/admin/orgs' },
      { path: 'orgs', name: 'AdminOrgList', component: () => import('@/views/admin/AdminOrgList.vue') },
      { path: 'orgs/:id', name: 'AdminOrgDetail', component: () => import('@/views/admin/AdminOrgDetail.vue'), props: true },
      { path: 'users', name: 'AdminUserList', component: () => import('@/views/admin/AdminUserList.vue') },
      { path: 'users/:id', name: 'AdminUserDetail', component: () => import('@/views/admin/AdminUserDetail.vue'), props: true },
      { path: 'features', name: 'AdminFeatureList', component: () => import('@/views/admin/AdminFeatureList.vue') },
      { path: 'audit', name: 'AdminAuditLog', component: () => import('@/views/admin/AdminAuditLog.vue') },
    ],
  },
  {
    path: '/create',
    redirect: '/workspace/create',
  },
  {
    path: '/invite/:token',
    name: 'AcceptInvite',
    component: () => import('@/views/AcceptInvite.vue'),
    meta: { requiresAuth: false },
  },
  {
    // 申请审核中心：先做技能上传/加载审核 Tab，未来扩展账号/功能开放申请
    path: '/approvals',
    name: 'Approvals',
    component: () => import('@/views/Approvals.vue'),
    meta: { requiresAuth: true, requiredOrgRole: 'operator' },
  },
  {
    // 申请加入组织：受 multi_org feature gate 保护，CE 模式访问会被路由守卫拦截到首页
    path: '/join-organization',
    name: 'JoinOrganization',
    component: () => import('@/views/JoinOrganization.vue'),
    meta: { requiresAuth: true, allowNoOrg: true, requireFeature: 'multi_org' },
  },
]

const routes: RouteRecordRaw[] = [...ceRoutes, ...eePortalRoutes]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to, _from, next) => {
  const token = localStorage.getItem('portal_token')
  const isLoginPage = to.path === '/login'
  const isInvitePage = to.path.startsWith('/invite/')
  const isSetupPage = to.path === '/setup-org'

  if (isLoginPage || isInvitePage) {
    return next()
  }

  if (!token && to.meta.requiresAuth !== false) {
    return next('/login')
  }

  if (token) {
    const { useAuthStore } = await import('@/stores/auth')
    const authStore = useAuthStore()
    if (!authStore.systemInfo) {
      await authStore.fetchSystemInfo()
    }
    if (!authStore.user) {
      await authStore.fetchUser()
    }

    if (!authStore.user) {
      return next('/login')
    }

    if (authStore.user.must_change_password && to.path !== '/force-change-password') {
      return next('/force-change-password')
    }

    if (!isSetupPage && !to.meta.allowNoOrg && to.path !== '/force-change-password') {
      if (authStore.user && !authStore.user.current_org_id && router.hasRoute('OrgSetup')) {
        return next('/setup-org')
      }
    }

    const requiredFeature = to.meta.requireFeature as string | undefined
    if (requiredFeature && authStore.systemInfo) {
      const feat = authStore.systemInfo.features.find((f: any) => f.id === requiredFeature)
      if (!feat?.enabled) {
        return next('/')
      }
    }

    // 超管路由守卫
    if (to.meta.requireSuperAdmin && !authStore.user?.is_super_admin) {
      return next('/')
    }

    // 申请审核中心守卫：超管或达到 requiredOrgRole 等级的组织成员可进
    const requiredOrgRole = to.meta.requiredOrgRole as 'member' | 'operator' | 'admin' | undefined
    if (requiredOrgRole && !authStore.user?.is_super_admin) {
      const { hasOrgRoleLevel } = await import('@/utils/orgRole')
      if (!hasOrgRoleLevel(authStore.user?.portal_org_role, requiredOrgRole)) {
        return next('/')
      }
    }
  }

  next()
})

router.afterEach(() => {
  const { t } = i18n.global
  document.title = t('common.appTitle')
})

router.onError((error, to) => {
  if (
    error.message.includes('Failed to fetch dynamically imported module') ||
    error.message.includes('Importing a module script failed') ||
    error.message.includes('error loading dynamically imported module')
  ) {
    window.location.assign(to.fullPath)
  }
})

export default router
