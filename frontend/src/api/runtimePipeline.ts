import request from '@/utils/request'

/**
 * /runtime pipelines tab — backed by /api/runtime/pipelines.
 * See `backend/app/routes/runtime_v2.py` for the source shape.
 */
export interface PipelineStage {
  name: string
  status: string
  duration_s: number
  error?: string | null
}

export interface PipelineRun {
  id: string
  name: string
  source: string
  trigger: string
  user: string
  time: string
  duration_s: number
  status: string
  branch?: string | null
  commit?: string | null
  env?: string | null
  stages: PipelineStage[]
}

export interface PipelineListResponse {
  pipelines: PipelineRun[]
  total: number
}

export const runtimePipelineApi = {
  list(): Promise<PipelineListResponse> {
    return request({ url: '/runtime/pipelines', method: 'get' }) as unknown as Promise<PipelineListResponse>
  },
}
