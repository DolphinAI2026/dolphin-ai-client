import request from '@/utils/request'

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

export interface GenerateResult {
  files: GeneratedFile[]
  explanation: string
  scene_type: string
  validation_errors: string[]
}

export interface CodingConversation {
  id: number
  title: string
  created_at: string
  updated_at: string
}

export interface CodingMessage {
  id: number
  role: 'user' | 'assistant' | 'system'
  content: string
  created_at: string
}

export interface WorkspaceInfo {
  id: string
  project_type: string
  project_name: string
  user_id: number
  status: string
  files?: string[]
}

export const codingApi = {
  /** 获取所有开发场景 */
  getScenes(category?: string) {
    return request.get<any, CodingScene[]>('/coding/scenes', { params: { category } })
  },

  /** 自动识别场景 */
  detectScene(requirement: string) {
    return request.post<any, { scene_type: string; scene_name: string; scene_description: string; conventions: string[] }>('/coding/detect-scene', { requirement })
  },

  /** 生成项目模板 */
  getTemplate(scene_type: string, module_name: string) {
    return request.post<any, { files: GeneratedFile[] }>('/coding/template', { scene_type, module_name })
  },

  /** 非流式代码生成 */
  generate(data: {
    scene_type?: string
    requirement: string
    conversation_id?: number
    app_id?: string
    module_name?: string
  }) {
    return request.post<any, GenerateResult>('/coding/generate', data)
  },

  /** 获取Coding对话列表 */
  getConversations() {
    return request.get<any, CodingConversation[]>('/coding/conversations')
  },

  /** 获取对话消息 */
  getMessages(conversationId: number) {
    return request.get<any, CodingMessage[]>(`/coding/conversations/${conversationId}/messages`)
  },

  // ========== Workspace API ==========

  /** 创建工作区 */
  createWorkspace(project_type: string, project_name: string) {
    return request.post<any, WorkspaceInfo>('/coding/workspace/create', { project_type, project_name })
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
    const resp = await fetch(`/api/coding/workspace/${wsId}/download?type=${type}`, {
      headers: { 'Authorization': `Bearer ${token}` }
    })
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: '下载失败' }))
      throw new Error(err.detail || '下载失败')
    }
    const blob = await resp.blob()
    const disposition = resp.headers.get('Content-Disposition') || ''
    const match = disposition.match(/filename="?(.+?)"?$/)
    const filename = match ? match[1] : `${wsId}.zip`
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
    return request.get<any, { conversation_id: number | null; messages: CodingMessage[] }>(`/coding/workspace/${wsId}/conversation`)
  },

  /** 删除工作区 */
  deleteWorkspace(wsId: string) {
    return request.delete<any, { status: string }>(`/coding/workspace/${wsId}`)
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
    return `/api/coding/auto-pipeline?${query.toString()}`
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

  /** 打包发布（返回 zip blob） */
  async publish(wsId: string): Promise<Blob> {
    const token = localStorage.getItem('token') || ''
    const resp = await fetch(`/api/coding/workspace/${wsId}/publish`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}` }
    })
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: '发布失败' }))
      throw new Error(err.detail || '发布失败')
    }
    return resp.blob()
  },
}
