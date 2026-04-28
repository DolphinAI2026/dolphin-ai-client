import request from '@/utils/request'

export interface UserPreference {
  user_id: number
  default_mode: 'simple' | 'pro'
}

export const preferencesApi = {
  get(): Promise<UserPreference> {
    return request.get<any, UserPreference>('/me/preferences')
  },
  update(default_mode: 'simple' | 'pro'): Promise<UserPreference> {
    return request.put<any, UserPreference>('/me/preferences', { default_mode })
  },
  getAppDefaultMode(applicationId: number) {
    return request.get<any, { application_id: number; default_mode: string | null }>(
      `/applications/${applicationId}/default-mode`,
    )
  },
  patchAppDefaultMode(applicationId: number, default_mode: 'simple' | 'pro' | null) {
    return request.patch<any, { application_id: number; default_mode: string | null }>(
      `/applications/${applicationId}/default-mode`,
      { default_mode },
    )
  },
}
