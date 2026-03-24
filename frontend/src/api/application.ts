import request from '@/utils/request'
import type { Application, MergedApplication } from '@/types'

export const applicationApi = {
  list(params?: { include_remote?: boolean; source_filter?: string }) {
    return request.get<any, MergedApplication[]>('/applications', { params })
  },
  get(id: number) {
    return request.get<any, Application>(`/applications/${id}`)
  },
  create(data: { conversation_id?: number; app_name: string; app_code: string; description?: string; config_preview?: any }) {
    return request.post<any, Application>('/applications', data)
  },
  update(id: number, data: { conversation_id?: number; app_name: string; app_code: string; description?: string; config_preview?: any }) {
    return request.put<any, Application>(`/applications/${id}`, data)
  },
  /** 首次生成配置时自动创建应用（不重复创建） */
  autoCreate(data: { app_name: string; config_preview: any; conversation_id?: number }) {
    return request.post<any, { app_id: number; app_name: string; app_code: string; is_new: boolean }>('/applications/auto-create', data)
  },
  /** 更新应用的平台环境配置 */
  updatePlatformConfig(appId: number, data: { platform_url?: string; platform_tenant_id?: string; platform_username?: string; platform_password_enc?: string }) {
    return request.patch<any, { success: boolean }>(`/applications/${appId}/platform-config`, data)
  },
  delete(id: number) {
    return request.delete(`/applications/${id}`)
  },
  uploadDoc(file: File) {
    const formData = new FormData()
    formData.append('file', file)
    return request.post<any, any>('/applications/upload-doc', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300000
    })
  },
  uploadDocWithConversation(file: File) {
    const formData = new FormData()
    formData.append('file', file)
    return request.post<any, { conversation_id: number; summary: string; preview: any }>('/applications/upload-doc-with-conversation', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300000  // 大文档 AI 解析需要较长时间（5分钟）
    })
  },

  // Copilot 分步生成
  getStepStatus(appId: number) {
    return request.get<any, any>(`/applications/${appId}/steps/status`)
  },
  executeStep(appId: number, step: string) {
    return request.post<any, any>(`/applications/${appId}/steps/execute`, { step })
  },
  resetStep(appId: number, step?: string) {
    return request.post<any, any>(`/applications/${appId}/steps/reset`, { step: step || null })
  },

  // 增量文档变更
  /** 上传文档新版本（SSE） */
  uploadDocVersionUrl(appId: number): string {
    const token = localStorage.getItem('token') || ''
    return `/api/applications/${appId}/upload-doc-version?token=${token}`
  },

  /** 获取变更计划 */
  getChangePlan(appId: number, planId: number) {
    return request.get<any, any>(`/applications/${appId}/change-plans/${planId}`)
  },

  /** 更新用户勾选 */
  updateSelections(appId: number, planId: number, selections: Record<string, boolean>) {
    return request.put<any, any>(`/applications/${appId}/change-plans/${planId}/selections`, { selections })
  },

  /** 执行变更计划（SSE） */
  executeChangePlanUrl(appId: number, planId: number): string {
    const token = localStorage.getItem('token') || ''
    return `/api/applications/${appId}/change-plans/${planId}/execute?token=${token}`
  },

  /** 获取文档版本列表（通过 appId） */
  getDocVersions(appId: number) {
    return request.get<any, any>(`/applications/${appId}/doc-versions`)
  },

  /** 获取文档版本列表（通过 conversationId，Application 创建前使用） */
  getDocVersionsByConversation(conversationId: number) {
    return request.get<any, any>(`/applications/doc-versions-by-conversation/${conversationId}`)
  },

  /** 编码冲突修复 */
  resolveConflict(appId: number, data: { step: string; model_name: string; old_code: string; new_code: string }) {
    return request.post<any, any>(`/applications/${appId}/resolve-conflict`, data)
  }
}
