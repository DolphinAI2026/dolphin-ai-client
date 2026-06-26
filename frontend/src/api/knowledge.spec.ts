import { describe, it, expect, vi, beforeEach } from 'vitest'
vi.mock('@/utils/request', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))
import request from '@/utils/request'
import { listKnowledgeDocs, createKnowledgeDoc } from './knowledge'

describe('knowledge api', () => {
  beforeEach(() => vi.clearAllMocks())
  it('listKnowledgeDocs unwraps docs', async () => {
    ;(request.get as any).mockResolvedValue({ docs: [{ slug: 'a' }] })
    expect(await listKnowledgeDocs()).toEqual([{ slug: 'a' }])
    expect(request.get).toHaveBeenCalledWith('/knowledge/docs', { params: undefined })
  })
  it('createKnowledgeDoc posts body', async () => {
    ;(request.post as any).mockResolvedValue({ slug: 'a' })
    await createKnowledgeDoc({ slug: 'a', title: 'T', body_md: 'x' })
    expect(request.post).toHaveBeenCalledWith('/knowledge/docs', { slug: 'a', title: 'T', body_md: 'x' })
  })
})
