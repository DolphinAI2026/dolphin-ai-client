import { describe, expect, it, vi, beforeEach } from 'vitest'
import { ref } from 'vue'

const api = vi.hoisted(() => ({
  listWorkspaceFiles: vi.fn(),
  getWorkspaceChanges: vi.fn(),
}))
vi.mock('@/api/coding', () => ({
  listWorkspaceFiles: api.listWorkspaceFiles,
  getWorkspaceChanges: api.getWorkspaceChanges,
}))
vi.mock('@/views/coding/fileTree', () => ({
  buildFileTree: (files: string[]) => files.map(f => ({ name: f, path: f, type: 'file' })),
}))

beforeEach(() => vi.clearAllMocks())

describe('useWorkspaceFiles', () => {
  it('loads tree + changes for a wsId and exposes changed paths', async () => {
    api.listWorkspaceFiles.mockResolvedValue(['a.ts', 'b.ts'])
    api.getWorkspaceChanges.mockResolvedValue({ enabled: true, files: [{ path: 'a.ts', status: 'M' }] })
    const { useWorkspaceFiles } = await import('./useWorkspaceFiles')
    const wsId = ref<string | null>('1_abc')
    const wf = useWorkspaceFiles(wsId)
    await wf.load()
    expect(api.listWorkspaceFiles).toHaveBeenCalledWith('1_abc')
    expect(wf.tree.value).toHaveLength(2)
    expect(wf.changed.value.has('a.ts')).toBe(true)
  })
  it('clears when wsId is null and never calls the api', async () => {
    const { useWorkspaceFiles } = await import('./useWorkspaceFiles')
    const wf = useWorkspaceFiles(ref<string | null>(null))
    await wf.load()
    expect(api.listWorkspaceFiles).not.toHaveBeenCalled()
    expect(wf.tree.value).toEqual([])
  })
  it('select(path) updates selected', async () => {
    const { useWorkspaceFiles } = await import('./useWorkspaceFiles')
    const wf = useWorkspaceFiles(ref<string | null>('1_abc'))
    wf.select('a.ts')
    expect(wf.selected.value).toBe('a.ts')
  })
})
