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

/** doc_type 区分文档类型，前端据此决定渲染 sections 还是 outline。 */
export type SpecDocType = 'spec' | 'self_dev_package' | 'page_design' | 'general'

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
  /** 'spec' 走 6 章节统计；其他类型走 outline */
  doc_type?: SpecDocType
  /** 非 spec 文档的二级标题大纲，前 8 条 */
  outline?: string[]
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
