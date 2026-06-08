/**
 * 组织加入申请的前端 API 封装。
 *
 * 后端路由组前缀：/org-join-requests（用户侧）+ /admin/org-join-requests（审核侧）。
 * 整组路由受 multi_org feature gate 保护，CE 模式访问会返回 403。
 */

import api from '@/services/api'

// 申请状态枚举：与后端 OrgJoinRequestStatus 严格对齐
export type JoinRequestStatus = 'pending' | 'approved' | 'rejected' | 'cancelled'

// 审核动作
export type JoinRequestAction = 'approve' | 'reject'

// 加入申请列表/详情数据结构（与后端 JoinRequestInfo 字段一一对应）
export interface JoinRequestInfo {
  id: string
  user_id: string
  org_id: string
  reason: string | null
  status: JoinRequestStatus
  reviewed_by: string | null
  reviewed_at: string | null
  review_note: string | null
  created_at: string
  // 后端批量注入的"人话身份"字段
  requester_name: string | null
  requester_email: string | null
  org_name: string | null
  org_slug: string | null
}

// 组织目录条目：供申请加入时选择用，仅含最小公开字段
export interface OrgDirectoryItem {
  id: string
  name: string
  slug: string
}

// 提交申请：用 org_slug 而不是 org_id，避免暴露组织 UUID
export async function submitJoinRequest(orgSlug: string, reason?: string): Promise<JoinRequestInfo> {
  const res = await api.post('/org-join-requests', { org_slug: orgSlug, reason })
  return res.data.data
}

// 查看自己提交的全部申请历史
export async function listMyJoinRequests(): Promise<JoinRequestInfo[]> {
  const res = await api.get('/org-join-requests/my')
  return res.data.data ?? []
}

// 撤回自己提交的 pending 申请
export async function cancelMyJoinRequest(requestId: string): Promise<void> {
  await api.delete(`/org-join-requests/${requestId}`)
}

// 获取所有组织的公开目录（id/name/slug），供用户申请加入时下拉选择
export async function listOrgDirectory(): Promise<OrgDirectoryItem[]> {
  const res = await api.get('/orgs/directory')
  return res.data.data ?? []
}

// 审核中心待审列表：超管全部 / 组织 admin 本组织 / 普通用户空
export async function listPendingJoinRequests(): Promise<JoinRequestInfo[]> {
  const res = await api.get('/admin/org-join-requests/pending')
  return res.data.data ?? []
}

// 审核单条申请（approve / reject）
export async function reviewJoinRequest(
  requestId: string,
  action: JoinRequestAction,
  note?: string,
): Promise<JoinRequestInfo> {
  const res = await api.put(`/admin/org-join-requests/${requestId}/review`, { action, note })
  return res.data.data
}
