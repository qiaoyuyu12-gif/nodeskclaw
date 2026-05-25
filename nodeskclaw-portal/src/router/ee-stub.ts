import type { RouteRecordRaw } from 'vue-router'
import { useEdition } from '@/composables/useFeature'

// EE 超管后台路由（仅 EE 版本可见）
const eeAdminRoutes: RouteRecordRaw[] = [
  {
    path: '/admin/orgs',
    name: 'AdminOrgs',
    component: () => import('@/views/admin/AdminOrgList.vue'),
    meta: { requiresAuth: true, requireSuperAdmin: true },
  },
]

export const eePortalRoutes: RouteRecordRaw[] = eeAdminRoutes
export const eeOrgSettingsChildren: RouteRecordRaw[] = []