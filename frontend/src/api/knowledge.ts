import request from '@/utils/request'

// baseURL 已是 /api;request 响应拦截器已 unwrap response.data。
export interface KnowledgeDoc {
  id: number
  slug: string
  title: string
  summary: string
  category: string
  tags: string | null
  body_md: string
  status: 'draft' | 'published'
  updated_at: string
}

export async function listKnowledgeDocs(params?: { category?: string; status?: string }): Promise<KnowledgeDoc[]> {
  const data = await request.get<any, { docs?: KnowledgeDoc[] }>('/knowledge/docs', { params })
  return data?.docs || []
}
export async function getKnowledgeDoc(slug: string): Promise<KnowledgeDoc> {
  return request.get<any, KnowledgeDoc>(`/knowledge/docs/${encodeURIComponent(slug)}`)
}
export async function createKnowledgeDoc(body: Partial<KnowledgeDoc>): Promise<KnowledgeDoc> {
  return request.post<any, KnowledgeDoc>('/knowledge/docs', body)
}
export async function updateKnowledgeDoc(slug: string, body: Partial<KnowledgeDoc>): Promise<KnowledgeDoc> {
  return request.put<any, KnowledgeDoc>(`/knowledge/docs/${encodeURIComponent(slug)}`, body)
}
export async function deleteKnowledgeDoc(slug: string): Promise<void> {
  await request.delete<any, { ok: boolean }>(`/knowledge/docs/${encodeURIComponent(slug)}`)
}
