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

  /** 安装依赖 */
  installDeps(wsId: string) {
    return request.post<any, { status: string; message: string }>(`/coding/workspace/${wsId}/install`)
  },

  /** 构建项目 */
  buildProject(wsId: string) {
    return request.post<any, { status: string; message: string }>(`/coding/workspace/${wsId}/build`)
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
}
