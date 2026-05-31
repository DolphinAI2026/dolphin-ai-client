import request from '@/utils/request'

/**
 * /runtime deployments tab — backed by /api/runtime/deployments.
 * See `backend/app/routes/runtime_v2.py` for the source shape.
 */
export interface Deployment {
  id: string
  app: string
  app_code: string
  env: string
  version: string
  user: string
  time: string
  status: string
  changes: string
  duration: string
  error?: string | null
}

export interface DeploymentListResponse {
  deployments: Deployment[]
  total: number
}

export const runtimeDeploymentApi = {
  list(): Promise<DeploymentListResponse> {
    return request({ url: '/runtime/deployments', method: 'get' }) as unknown as Promise<DeploymentListResponse>
  },
}
