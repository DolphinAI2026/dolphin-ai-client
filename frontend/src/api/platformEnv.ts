import request from '@/utils/request'

export interface PlatformEnv {
  id: number
  env_name: string
  base_url: string
  platform_tenant_id: string
  username?: string
  is_default: boolean
  status: string  // "connected" | "disconnected"
  created_at?: string
}

export const platformEnvApi = {
  list: () => request.get<any, PlatformEnv[]>('/platform-envs'),
  create: (data: { env_name: string; base_url: string; platform_tenant_id: string; username?: string; password?: string; token?: string }) => request.post<any, { id: number }>('/platform-envs', data),
  update: (id: number, data: any) => request.put(`/platform-envs/${id}`, data),
  delete: (id: number) => request.delete(`/platform-envs/${id}`),
  test: (id: number) => request.post<any, { ok: boolean; status: string; error?: string }>(`/platform-envs/${id}/test`),
  login: (id: number) => request.post<any, { ok: boolean; status: string }>(`/platform-envs/${id}/login`),
  setDefault: (id: number) => request.post(`/platform-envs/${id}/set-default`),
}
