/**
 * 组织退出申请的前端 API 封装。
 *
 * 与 orgJoinApi.ts 对称，后端路由组也受 multi_org feature gate 保护。
 */

import api from '@/services/api'

export type LeaveRequestStatus = 'pending' | 'approved' | 'rejected' | 'cancelled'

export type LeaveRequestAction = 'approve' | 'reject'

// 与后端 LeaveRequestInfo 字段一一对应
export interface LeaveRequestInfo {
  id: string
  user_id: string
  org_id: string
  reason: string | null
  status: LeaveRequestStatus
  reviewed_by: string | null
  reviewed_at: string | null
  review_note: string | null
  created_at: string
  // 后端注入的人话身份字段
  requester_name: string | null
  requester_email: string | null
  // 申请者在该组织的当前角色（admin/operator/member）；前端用来标识"申请退出者本是 admin"
  requester_role: string | null
  org_name: string | null
  org_slug: string | null
}

// 提交退出申请：必须指定 org_id（避免依赖前端 current_org 隐式上下文）
export async function submitLeaveRequest(orgId: string, reason?: string): Promise<LeaveRequestInfo> {
  const res = await api.post('/org-leave-requests', { org_id: orgId, reason })
  return res.data.data
}

// 查看自己提交的全部退出申请
export async function listMyLeaveRequests(): Promise<LeaveRequestInfo[]> {
  const res = await api.get('/org-leave-requests/my')
  return res.data.data ?? []
}

// 撤回 pending 退出申请
export async function cancelMyLeaveRequest(requestId: string): Promise<void> {
  await api.delete(`/org-leave-requests/${requestId}`)
}

// 审核中心待审退出申请列表
export async function listPendingLeaveRequests(): Promise<LeaveRequestInfo[]> {
  const res = await api.get('/admin/org-leave-requests/pending')
  return res.data.data ?? []
}

// 审核单条退出申请
export async function reviewLeaveRequest(
  requestId: string,
  action: LeaveRequestAction,
  note?: string,
): Promise<LeaveRequestInfo> {
  const res = await api.put(`/admin/org-leave-requests/${requestId}/review`, { action, note })
  return res.data.data
}
