import request from '@/utils/request'
import type { WorkspaceInfo } from '@/api/coding'

export interface Project {
  id: number
  name: string
  description?: string
  platform_url?: string
  platform_tenant_id?: string
  platform_username?: string
  platform_app_id?: string
  platform_app_name?: string
  platform_connected: boolean
  created_at: string
  updated_at: string
}

export interface CreateProjectData {
  name: string
  description?: string
}

export interface UpdateProjectData {
  name?: string
  description?: string
  platform_url?: string
  platform_tenant_id?: string
  platform_token?: string
  platform_username?: string
  platform_app_id?: string
  platform_app_name?: string
}

export interface ProjectConnectData {
  username: string
  password: string
  base_url: string
  tenant_id: string
}

export interface PlatformApp {
  app_id: string
  app_name: string
  app_code: string
  status: string
}

export interface ProjectMember {
  id: number
  user_id: number
  username: string
  role: 'owner' | 'admin' | 'member'
  created_at: string
}

export interface AddMemberData {
  username?: string
  user_id?: number
  role?: string
}

export const projectsApi = {
  /** 列出用户所有项目 */
  list() {
    return request.get<any, Project[]>('/projects')
  },

  /** 创建项目 */
  create(data: CreateProjectData) {
    return request.post<any, Project>('/projects', data)
  },

  /** 获取项目详情 */
  get(id: number) {
    return request.get<any, Project>(`/projects/${id}`)
  },

  /** 更新项目 */
  update(id: number, data: UpdateProjectData) {
    return request.put<any, Project>(`/projects/${id}`, data)
  },

  /** 删除项目 */
  delete(id: number) {
    return request.delete<any, void>(`/projects/${id}`)
  },

  /** 连接平台（登录） */
  connect(id: number, data: ProjectConnectData) {
    return request.post<any, Project>(`/projects/${id}/connect`, data)
  },

  /** 获取平台应用列表 */
  listPlatformApps(id: number) {
    return request.get<any, PlatformApp[]>(`/projects/${id}/platform-apps`)
  },

  /** 列出项目下的工作区 */
  listWorkspaces(id: number) {
    return request.get<any, WorkspaceInfo[]>(`/projects/${id}/workspaces`)
  },

  /** 列出项目成员 */
  listMembers(id: number) {
    return request.get<any, ProjectMember[]>(`/projects/${id}/members`)
  },

  /** 添加项目成员 */
  addMember(id: number, data: AddMemberData) {
    return request.post<any, ProjectMember>(`/projects/${id}/members`, data)
  },

  /** 移除项目成员 */
  removeMember(projectId: number, memberId: number) {
    return request.delete<any, void>(`/projects/${projectId}/members/${memberId}`)
  },

  /** 更新成员角色 */
  updateMemberRole(projectId: number, memberId: number, role: string) {
    return request.put<any, any>(`/projects/${projectId}/members/${memberId}`, { role })
  },
}
