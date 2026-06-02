import request from '@/utils/request'
import { API_PREFIX } from '@/utils/request'

export interface CodingScene {
  type: string
  name: string
  description: string
  category: string
  platform: string
}

export interface GeneratedFile {
  path: string
  content: string
  language: string
}

export interface CodingConversation {
  id: number
  title: string
  workspace_id?: string | null
  selected_llm_config_id?: number | null
  created_at: string
  updated_at: string
}

export interface CodingMessage {
  id: number
  role: 'user' | 'assistant' | 'system'
  content: string
  created_at: string
}

export interface ReplayStreamMessage {
  type: 'user' | 'thinking' | 'tool' | 'file_write' | 'file_edit' | 'command' | 'status' | 'error'
  content: string
  fileName?: string
  fileContent?: string
  collapsed?: boolean
  stepKey?: string
  stepDone?: boolean
  hidden?: boolean
  timestamp?: number
}

export interface WorkspaceConversation {
  conversation_id: number | null
  selected_llm_config_id: number | null
  messages: CodingMessage[]
  stream_messages?: ReplayStreamMessage[]
}

export interface WorkspaceInfo {
  id: string
  project_id?: number
  project_type: string
  project_name: string
  display_name?: string
  user_id: number
  status: string
  files?: string[]
  access_role?: 'owner' | 'admin' | 'member'
  permissions?: {
    edit?: boolean
    delete?: boolean
    publish?: boolean
    upload_to_platform?: boolean
  }
}

export interface UploadResult {
  filename: string
  content_type: string
  content?: string
  file_path: string
}

export function isIdeUnavailableError(error: any): boolean {
  const status = error?.response?.status
  const detail = String(
    error?.response?.data?.detail ||
    error?.response?.data?.message ||
    error?.message ||
    ''
  )
  return (status === 501 || status === 503) && detail.includes('Web IDE')
}

export const codingApi = {
  /** 获取所有开发场景 */
  getScenes(category?: string) {
    return request.get<any, CodingScene[]>('/coding/scenes', { params: { category } })
  },

  /** 获取Coding对话列表 */
  getConversations() {
    return request.get<any, CodingConversation[]>('/coding/conversations')
  },

  /** 创建 Coding 会话（和 AI Builder 的新建会话行为对齐） */
  createConversation(selected_llm_config_id?: number | null) {
    return request.post<any, CodingConversation>('/conversations', {
      agent_type: 'coding',
      selected_llm_config_id: selected_llm_config_id ?? null,
    })
  },

  /** 获取 Coding v2 对话关联的工作区 */
  getConversationWorkspace(conversationId: number) {
    return request.get<any, { conversation_id: number; workspace_id: string | null }>(`/coding/v2/conversations/${conversationId}/workspace`)
  },

  /** 获取对话消息 */
  getMessages(conversationId: number) {
    return request.get<any, CodingMessage[]>(`/coding/conversations/${conversationId}/messages`)
  },

  // ========== Workspace API ==========

  /** 创建工作区 */
  createWorkspace(project_type: string, project_name: string, project_id?: number, display_name?: string) {
    return request.post<any, WorkspaceInfo>('/coding/workspace/create', { project_type, project_name, project_id, display_name })
  },

  /** 上传已有 zip → 解压成 workspace 供 AI 二次调整 */
  async importZipToWorkspace(file: File, opts?: { project_type?: string; project_id?: number; display_name?: string }) {
    const fd = new FormData()
    fd.append('file', file)
    const params = new URLSearchParams()
    if (opts?.project_type) params.append('project_type', opts.project_type)
    if (opts?.project_id) params.append('project_id', String(opts.project_id))
    if (opts?.display_name) params.append('display_name', opts.display_name)
    const qs = params.toString() ? `?${params.toString()}` : ''
    return request.post<any, WorkspaceInfo>(`/coding/workspace/import-zip${qs}`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    })
  },

  /** 安装依赖（npm install 可能较慢，5分钟超时） */
  installDeps(wsId: string) {
    return request.post<any, { status: string; message: string }>(`/coding/workspace/${wsId}/install`, {}, { timeout: 300000 })
  },

  /** 构建项目（构建可能较慢，5分钟超时） */
  buildProject(wsId: string) {
    return request.post<any, { status: string; message: string }>(`/coding/workspace/${wsId}/build`, {}, { timeout: 300000 })
  },

  /** 下载构建包或源码 zip */
  async downloadZip(wsId: string, type: 'dist' | 'src' = 'dist') {
    const token = localStorage.getItem('token') || ''
    const resp = await fetch(`${API_PREFIX}/coding/workspace/${wsId}/download?type=${type}`, {
      headers: { 'Authorization': `Bearer ${token}` }
    })
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: '下载失败' }))
      throw new Error(err.detail || '下载失败')
    }
    const blob = await resp.blob()
    const disposition = resp.headers.get('Content-Disposition') || ''
    const match = disposition.match(/filename="?(.+?)"?$/)
    const filename = match?.[1] || `${wsId}.zip`
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  },

  /** 获取工作区信息 */
  getWorkspace(wsId: string) {
    return request.get<any, WorkspaceInfo>(`/coding/workspace/${wsId}`)
  },

  /** 获取工作区 Web IDE URL */
  getIdeUrl(wsId: string, conversationId?: number | null, theme?: 'light' | 'dark') {
    const params: Record<string, string | number> = {}
    if (conversationId) params.conversation_id = conversationId
    if (theme) params.theme = theme
    return request.get<any, { ide_url: string }>(`/coding/workspace/${wsId}/ide-url`, {
      params: Object.keys(params).length ? params : undefined,
    })
  },

  /** 列出工作区文件 */
  listFiles(wsId: string) {
    return request.get<any, string[]>(`/coding/workspace/${wsId}/files`)
  },

  /** 读取文件 */
  readFile(wsId: string, filePath: string) {
    return request.get<any, { path: string; content: string }>(`/coding/workspace/${wsId}/file`, { params: { file_path: filePath } })
  },

  /** 写入文件 */
  writeFile(wsId: string, filePath: string, content: string) {
    return request.post<any, { status: string; path: string }>(`/coding/workspace/${wsId}/file`, { file_path: filePath, content })
  },

  /** 列出用户所有工作区 */
  listWorkspaces() {
    return request.get<any, WorkspaceInfo[]>('/coding/workspaces')
  },

  /** 获取工作区关联的对话 */
  getWorkspaceConversation(wsId: string) {
    return request.get<any, WorkspaceConversation>(`/coding/workspace/${wsId}/conversation`)
  },

  /** 删除工作区 */
  deleteWorkspace(wsId: string) {
    return request.delete<any, { status: string }>(`/coding/workspace/${wsId}`)
  },

  /** 删除会话(含消息);有关联工作区则后端 best-effort 一并清理(孤儿会话也能删) */
  deleteConversation(conversationId: number) {
    return request.delete<any, { status: string }>(`/coding/conversations/${conversationId}`)
  },

  // ========== Auto Pipeline API ==========

  /** 自动流水线 SSE URL（detect-scene → create-workspace → generate → install → serve） */
  autoPipelineUrl(params: { message: string; workspace_id?: string; conversation_id?: number; app_id?: string }): string {
    const query = new URLSearchParams()
    query.set('message', params.message)
    if (params.workspace_id) query.set('workspace_id', params.workspace_id)
    if (params.conversation_id) query.set('conversation_id', String(params.conversation_id))
    if (params.app_id) query.set('app_id', params.app_id)
    const token = localStorage.getItem('token') || ''
    query.set('token', token)
    return `${API_PREFIX}/coding/auto-pipeline?${query.toString()}`
  },

  /** 启动开发服务器 */
  startServe(wsId: string) {
    return request.post<any, { status: string; url?: string; message?: string }>(`/coding/workspace/${wsId}/serve`, {}, { params: { action: 'start' }, timeout: 120000 })
  },

  /** 停止开发服务器 */
  stopServe(wsId: string) {
    return request.post<any, { status: string; message?: string }>(`/coding/workspace/${wsId}/serve`, {}, { params: { action: 'stop' } })
  },

  /** 获取开发服务器状态 */
  getServeStatus(wsId: string) {
    return request.get<any, { running: boolean; url?: string }>(`/coding/workspace/${wsId}/serve-status`)
  },

  /** 构建 + 上传到平台环境 */
  uploadToPlatform(wsId: string, envId: number): Promise<{ status: string; message: string }> {
    return request.post(`/coding/workspace/${wsId}/upload-to-platform`, { env_id: envId }, { timeout: 300000 })
  },

  /** 装回应用 / 发布到资产库:bound 传 localAppId(上传→attach→页面建菜单→重发);lib 不传(只上传到组件库) */
  deployToApp(wsId: string, localAppId?: number): Promise<{
    status: 'installed' | 'uploaded_only'
    app?: { local_app_id: number; name: string }
    menu?: string | null
    version?: string
    kits?: string[]
    hint?: string
  }> {
    return request.post(`/coding/workspace/${wsId}/deploy-to-app`,
      { local_app_id: localAppId ?? null }, { timeout: 300000 })
  },

  /** 打包发布（返回 zip blob） */
  async publish(wsId: string): Promise<Blob> {
    const token = localStorage.getItem('token') || ''
    const resp = await fetch(`${API_PREFIX}/coding/workspace/${wsId}/publish`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}` }
    })
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: '发布失败' }))
      throw new Error(err.detail || '发布失败')
    }
    return resp.blob()
  },

  /** 上传文件（图片/文档附件） */
  async uploadFile(file: File, workspaceId?: string): Promise<UploadResult> {
    const token = localStorage.getItem('token') || ''
    const formData = new FormData()
    formData.append('file', file)
    const params = new URLSearchParams()
    if (workspaceId) params.set('workspace_id', workspaceId)
    const query = params.toString() ? `?${params.toString()}` : ''
    const resp = await fetch(`${API_PREFIX}/coding/upload${query}`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}` },
      body: formData,
    })
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: '上传失败' }))
      throw new Error(err.detail || '上传失败')
    }
    return resp.json()
  },
}
