import request from '@/utils/request'

export interface RuntimeSandbox {
  id: string
  name: string
  workspace: string
  flavor: '睿鲸' | 'Vibe'
  user: string
  cpu: number
  cpu_max: number
  mem: number
  mem_max: number
  disk: number
  idle: string
  status: 'active' | 'idle' | 'recycling'
  ttl: string
  created: string
  image: string
}

export interface RuntimeSandboxListResponse {
  sandboxes: RuntimeSandbox[]
  total: number
  active: number
  idle_count: number
}

export const runtimeSandboxApi = {
  list(): Promise<RuntimeSandboxListResponse> {
    return request({ url: '/online-coding/sandboxes/v2/runtime', method: 'get' }).then(r => r.data)
  },
}
