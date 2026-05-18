import request from '@/utils/request'

/**
 * /api/specs-v2 — synthetic SPEC list per application (v2 SpecsPage).
 *
 * Backend: backend/app/routes/specs_v2.py. Each Application maps to one
 * synthetic v1 SPEC for now; real multi-version comes later.
 */
export interface SpecVersionItem {
  v: number
  status: 'draft' | 'test' | 'prod' | 'archived'
  note: string
  author: string
  date: string
}

export interface SpecSection {
  name: string
  count: number
}

export interface SpecListItem {
  id: string
  app_id: number
  app_name: string
  latest: number
  diff_add: number
  diff_mod: number
  origin: string
  versions: SpecVersionItem[]
  sections: SpecSection[]
  excerpt: string
}

export interface SpecListResponse {
  specs: SpecListItem[]
  total: number
}

export const specsV2Api = {
  list(): Promise<SpecListResponse> {
    return request({ url: '/specs-v2', method: 'get' }) as unknown as Promise<SpecListResponse>
  },
}
