import request from '@/utils/request'

export interface SkillCatalogItem {
  code: string
  name: string
  desc: string
  category: string
  callable_path: string
  is_async: boolean
  is_active: boolean
}
export interface SkillCatalogResponse { skills: SkillCatalogItem[]; total: number }

export const skillCatalogApi = {
  list(): Promise<SkillCatalogResponse> {
    return request({ url: '/skills/catalog', method: 'get' }) as unknown as Promise<SkillCatalogResponse>
  },
}
