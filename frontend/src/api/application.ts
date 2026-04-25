import request from '@/utils/request'
import type { Application, MergedApplication } from '@/types'
import { API_PREFIX } from '@/utils/request'

export const applicationApi = {
  list(params?: { include_remote?: boolean; source_filter?: string }) {
    return request.get<any, MergedApplication[]>('/applications', { params })
  },
  get(id: number) {
    return request.get<any, Application>(`/applications/${id}`)
  },
  create(data: { conversation_id?: number; project_id?: number; app_name: string; app_code: string; description?: string; config_preview?: any; platform_env_id?: number | null }) {
    return request.post<any, Application>('/applications', data)
  },
  update(id: number, data: { conversation_id?: number; project_id?: number; app_name: string; app_code: string; description?: string; config_preview?: any; platform_env_id?: number | null }) {
    return request.put<any, Application>(`/applications/${id}`, data)
  },
  /** 首次生成配置时自动创建应用（不重复创建） */
  autoCreate(data: { app_name: string; config_preview: any; conversation_id?: number; project_id?: number }) {
    return request.post<any, { app_id: number; app_name: string; app_code: string; is_new: boolean }>('/applications/auto-create', data)
  },
  /** 从平台导入已有应用 */
  importFromPlatform(envId: number, apaasAppId: string) {
    return request.post<any, Application>('/applications/import-from-platform', {
      env_id: envId,
      apaas_app_id: apaasAppId,
    })
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
  publish(appId: number) {
    return request.post<any, { ok: boolean; version?: string; remote_status?: string }>(`/applications/${appId}/publish`)
  },

  // 增量文档变更
  /** 上传文档新版本（SSE） */
  uploadDocVersionUrl(appId: number): string {
    const token = localStorage.getItem('token') || ''
    return `${API_PREFIX}/applications/${appId}/upload-doc-version?token=${token}`
  },

  /** 根据对话更新诉求生成新版 SPEC 草稿 */
  draftDocUpdate(appId: number, data: { instruction: string; conversation_id?: number | null; current_doc?: string }) {
    return request.post<any, {
      markdown: string
      filename: string
      summary: string
      doc_result?: any
      app_config?: any
    }>(`/applications/${appId}/draft-doc-update`, data, { timeout: 300000 })
  },

  /** 获取变更计划 */
  getChangePlan(appId: number, planId: number) {
    return request.get<any, any>(`/applications/${appId}/change-plans/${planId}`)
  },

  /** 更新用户勾选 */
  updateSelections(appId: number, planId: number, selections: Record<string, boolean>) {
    return request.put<any, any>(`/applications/${appId}/change-plans/${planId}/selections`, { selections })
  },

  /** 取消变更计划：应用状态回到 completed，回滚到 from_version */
  cancelChangePlan(appId: number, planId: number) {
    return request.post<any, any>(`/applications/${appId}/change-plans/${planId}/cancel`)
  },

  /** 执行变更计划（SSE） */
  executeChangePlanUrl(appId: number, planId: number): string {
    const token = localStorage.getItem('token') || ''
    return `${API_PREFIX}/applications/${appId}/change-plans/${planId}/execute?token=${token}`
  },

  /** 获取文档版本列表（通过 appId） */
  getDocVersions(appId: number) {
    return request.get<any, any>(`/applications/${appId}/doc-versions`)
  },
  deleteDocVersion(appId: number, versionId: number) {
    return request.delete<any, any>(`/applications/${appId}/doc-versions/${versionId}`)
  },

  /** 获取文档版本列表（通过 conversationId，Application 创建前使用） */
  getDocVersionsByConversation(conversationId: number) {
    return request.get<any, any>(`/applications/doc-versions-by-conversation/${conversationId}`)
  },

  /** 首次部署前的模型 code 冲突预检（租户级扫描） */
  preflightConflicts(appId: number) {
    return request.post<any, {
      has_conflicts: boolean
      skipped?: string | null
      scanned_remote_count: number
      conflicts: Array<{
        resource_type: string
        name: string
        original_code: string
        suggested_code: string
      }>
    }>(`/applications/${appId}/preflight-conflicts`)
  },

  /** 应用用户确认的 {old_code: new_code} 到 config_preview（只改模型 code 及引用） */
  applyCodeRename(appId: number, renames: Record<string, string>) {
    return request.post<any, {
      ok: boolean
      changed_count: number
      applied_renames: Record<string, string>
    }>(`/applications/${appId}/apply-code-rename`, { renames })
  },

  /** 编码冲突修复 */
  resolveConflict(appId: number, data: { step: string; model_name: string; old_code: string; new_code: string }) {
    return request.post<any, any>(`/applications/${appId}/resolve-conflict`, data)
  }
}
