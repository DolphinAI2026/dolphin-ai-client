import request from '@/utils/request'
import { API_PREFIX } from '@/utils/request'

export interface MarketplaceComponent {
  id: number
  name: string
  code: string
  description?: string
  category: string
  version: string
  author_id: number
  author_name?: string
  tenant_id: number
  download_count: number
  tags?: string[]
  readme?: string
  source_workspace_id?: string
  published_at: string
  updated_at: string
}

export interface PublishData {
  workspace_id: string
  name: string
  code: string
  description?: string
  category?: string
  version?: string
  tags?: string[]
  readme?: string
}

export const marketplaceApi = {
  /** 列出/搜索市场组件 */
  list(params?: { keyword?: string; category?: string; sort?: string }) {
    return request.get<any, MarketplaceComponent[]>('/marketplace', { params })
  },

  /** 获取组件详情 */
  get(id: number) {
    return request.get<any, MarketplaceComponent>(`/marketplace/${id}`)
  },

  /** 发布组件到市场 */
  publish(data: PublishData) {
    return request.post<any, MarketplaceComponent>('/marketplace/publish', data)
  },

  /** 下载组件 zip */
  async download(id: number) {
    const token = localStorage.getItem('token') || ''
    const resp = await fetch(`${API_PREFIX}/marketplace/${id}/download`, {
      headers: { 'Authorization': `Bearer ${token}` }
    })
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: '下载失败' }))
      throw new Error(err.detail || '下载失败')
    }
    const blob = await resp.blob()
    const disposition = resp.headers.get('Content-Disposition') || ''
    const match = disposition.match(/filename="?(.+?)"?$/)
    const filename = match?.[1] || `component-${id}.zip`
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  },

  /** 下架组件 */
  unpublish(id: number) {
    return request.delete<any, { status: string }>(`/marketplace/${id}`)
  },

  /** 列出我发布的组件 */
  listMine() {
    return request.get<any, MarketplaceComponent[]>('/marketplace/my')
  },
}
