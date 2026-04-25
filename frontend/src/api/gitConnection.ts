import request from '@/utils/request'

export interface GitConnection {
  id: number
  project_id: number
  provider: 'gitlab' | 'github'
  host: string
  group_id_or_org: string
  status: string
}

export interface ConnectGitPATRequest {
  provider: 'gitlab' | 'github'
  host: string
  access_token: string
  group_id_or_org: string
}

export interface InitRepoResponse {
  git_repo_url: string
  full_path: string
}

export const gitConnectionApi = {
  get(projectId: number): Promise<GitConnection | null> {
    return request.get<any, GitConnection | null>(`/projects/${projectId}/git-connection`)
  },
  connectPAT(projectId: number, body: ConnectGitPATRequest): Promise<GitConnection> {
    return request.post<any, GitConnection>(`/projects/${projectId}/git-connection`, body)
  },
  disconnect(projectId: number) {
    return request.delete<any, { status: string }>(`/projects/${projectId}/git-connection`)
  },
  initRepo(applicationId: number): Promise<InitRepoResponse> {
    return request.post<any, InitRepoResponse>(`/applications/${applicationId}/git-init`, {})
  },
}
