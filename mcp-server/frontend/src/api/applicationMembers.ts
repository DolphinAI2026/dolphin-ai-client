import request from '@/utils/request'
import type { ApplicationMember, ProjectRole } from '@/types/collaboration'

export interface InviteAppMemberRequest {
  username?: string
  user_id?: number
  role: ProjectRole
}

export interface InviteAppMemberResponse {
  id: number
  user_id: number
  username: string
  role: ProjectRole
  source: 'direct'
  created_at: string | null
}

export const applicationMembersApi = {
  list(applicationId: number): Promise<ApplicationMember[]> {
    return request.get<any, ApplicationMember[]>(`/applications/${applicationId}/members`)
  },
  invite(applicationId: number, body: InviteAppMemberRequest): Promise<InviteAppMemberResponse> {
    return request.post<any, InviteAppMemberResponse>(`/applications/${applicationId}/members`, body)
  },
  updateRole(applicationId: number, userId: number, role: ProjectRole) {
    return request.patch<any, { id: number; user_id: number; role: ProjectRole }>(
      `/applications/${applicationId}/members/${userId}`,
      { role },
    )
  },
  remove(applicationId: number, userId: number) {
    return request.delete<any, { status: string }>(`/applications/${applicationId}/members/${userId}`)
  },
}
