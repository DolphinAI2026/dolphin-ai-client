import request from '@/utils/request'
import type { Application, MergedApplication } from '@/types'
import { API_PREFIX } from '@/utils/request'

// ── 业务事件 (对应后端 BusinessEventsResponse / BusinessEventItem) ──────────────
export interface BusinessEventItem {
  event_id: string
  event_name: string
  event_code?: string | null
  event_type: string
  status: string
  trigger?: {
    form_id?: string | null
    boc_code?: string | null
    field_code?: string | null
  } | null
  target?: string | null
  last_update?: string | null
  extra?: Record<string, any>
}

export interface BusinessEventsResponse {
  ok: boolean
  app_id: number
  env_id?: number | null
  apaas_app_id?: string | null
  items: BusinessEventItem[]
  total: number
  source: string
  error_code?: string | null
  message?: string | null
}

export const applicationApi = {
  list(params?: { include_remote?: boolean; source_filter?: string; include_config?: boolean }) {
    return request.get<any, MergedApplication[]>('/applications', { params })
  },
  /** 按 app_name 模糊匹配本租户内当前用户可见的应用。AI-Chat → Builder 选目标弹框使用。 */
  matchByName(appNameLike: string, limit = 5) {
    return request.get<any, Array<{ id: number; app_name: string; app_code: string; status: string; apaas_app_id?: string | null; updated_at?: string | null }>>(
      '/applications/match-by-name',
      { params: { app_name_like: appNameLike, limit } }
    )
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
  // 一键到底：服务端后台触发真 apaas 生成（创建模型/表单/角色），立即返回，进度走 getStepStatus 轮询
  generateRun(appId: number) {
    return request.post<any, { started: boolean; already_running?: boolean; already_done?: boolean; app_id: number; status?: string; apaas_app_id?: string }>(`/applications/${appId}/generate-run`)
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
  draftDocUpdate(appId: number, data: { instruction: string; conversation_id?: number | null; selected_llm_config_id?: number | null; current_doc?: string }) {
    return request.post<any, {
      type?: string
      actionable_update?: boolean
      message?: string
      markdown?: string
      filename?: string
      summary: string
      doc_result?: any
      app_config?: any
      direct_config_update?: boolean
      change_plan?: any
      parsed_config?: any
      rendered_doc?: string
      actions?: any[]
      change_plan_id?: number
    }>(`/applications/${appId}/draft-doc-update`, data, { timeout: 300000 })
  },

  /** 获取变更计划 */
  getChangePlan(appId: number, planId: number) {
    return request.get<any, any>(`/applications/${appId}/change-plans/${planId}`)
  },

  /** 获取/创建 application 绑定的 ai_chat session（首次调用会自动注入应用最新 md 作为 artifact） */
  ensureChatSession(appId: number) {
    return request.post<any, { session_id: number; title: string; is_new: boolean; artifact_filename?: string | null }>(
      `/applications/${appId}/chat-session/ensure`,
    )
  },

  /** 从绑定 chat session 拉最新 md artifact 内容（前端拿到再调 upload-doc-version 上传） */
  syncMdFromChat(appId: number) {
    return request.post<any, { ok: boolean; artifact_filename: string; artifact_version: number; content: string }>(
      `/applications/${appId}/sync-from-chat-md`,
    )
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
  },

  // ============================================================
  // Plan C (2026-05-19): 从 ai_chat artifact 触发部署
  // AIChatPage 用户点 🚀 → DeployConfirmModal → 调本方法 → 后端
  // 解析 md + 建 Application 占位行 + 返回 task_id 让前端轮询
  // ============================================================

  /** 从 artifact (md 设计文档) 触发应用部署 — 返回 task_id 让前端轮询 */
  deployFromArtifact(data: {
    artifact_id: number
    env: 'dev' | 'test' | 'prod'
    app_code?: string
    platform_env_id?: number
  }) {
    return request.post<any, { task_id: string; app_id: number; sse_url: string }>(
      '/applications/deploy-from-artifact', data
    )
  },

  /** 轮询部署状态（粗粒度 — 真细节进度走 SSE sse_url） */
  getDeployStatus(taskId: string) {
    return request.get<any, {
      done: boolean
      phase: string  // draft / generating / completed / failed
      progress: number
      error: string | null
      app_id: number | null
    }>(`/applications/deploy-status/${taskId}`)
  },

  // ── 部署历史 & 回滚 (2026-05-24 Agent C) ─────────────────────────────────────────────────
  /** 列出应用的部署历史（分页） */
  listDeployRecords(appId: number, params?: { page?: number; page_size?: number }) {
    return request.get<any, {
      total: number
      page: number
      page_size: number
      items: Array<{
        id: number
        app_id: number
        user_id: number
        version_label: string | null
        status: 'in_progress' | 'success' | 'failed' | 'rolled_back'
        deploy_type: 'deploy' | 'publish' | 'rollback'
        snapshot_artifact_id: number | null
        snapshot_version: number | null
        snapshot_summary: string | null
        snapshot_size: number | null
        apaas_app_id_before: string | null
        apaas_app_id_after: string | null
        error_message: string | null
        created_at: string | null
        completed_at: string | null
      }>
    }>(`/applications/${appId}/deploy-records`, { params })
  },

  /** 单条部署记录详情（含 SPEC snapshot content + event log） */
  getDeployRecord(appId: number, recordId: number) {
    return request.get<any, {
      id: number
      app_id: number
      user_id: number
      version_label: string | null
      status: string
      deploy_type: string
      snapshot_artifact_id: number | null
      snapshot_version: number | null
      snapshot_summary: string | null
      snapshot_size: number | null
      snapshot_content: string | null
      apaas_app_id_before: string | null
      apaas_app_id_after: string | null
      error_message: string | null
      event_log: any[] | null
      created_at: string | null
      completed_at: string | null
    }>(`/applications/${appId}/deploy-records/${recordId}`)
  },

  /** 回滚到指定部署记录的 SPEC 快照 */
  rollbackApplication(appId: number, toRecordId: number) {
    return request.post<any, {
      ok: boolean
      record_id: number
      snapshot_version: number
      message: string
      next_action: string
    }>(`/applications/${appId}/rollback`, { to_record_id: toRecordId })
  },

  /** 拉应用业务事件 (只读). 应用未部署 → ok=false + error_code=APP_NOT_DEPLOYED + items=[]. */
  getBusinessEvents(appId: number) {
    return request.get<any, BusinessEventsResponse>(`/applications/${appId}/business-events`)
  },
}
