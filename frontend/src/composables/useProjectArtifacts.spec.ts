import { describe, it, expect } from 'vitest'
import { buildProjectView } from '@/composables/useProjectArtifacts'

const fakeApi = {
  get: async () => ({ id: 7, name: 'p', platform_connected: false, created_at: '2026-06-20' }),
  listWorkspaces: async () => ([
    { id: 'a', project_type: 'form-list', status: 'ready' },
    { id: 'b', project_type: 'mobile-page', status: 'building' },
  ]),
  listMembers: async () => ([{ id: 1, role: 'owner' }]),
  listDependencies: async () => ([
    { from_ref: 'workspace:a', to_ref: 'workspace:b', expose_label: 'X', consume_label: 'Y', note: 'n' },
  ]),
}

describe('buildProjectView', () => {
  it('并行拉+分组+解析依赖', async () => {
    const r = await buildProjectView(7, fakeApi as any)
    expect(r.project.id).toBe(7)
    expect(r.members.length).toBe(1)
    expect(r.groups.find(g => g.mode === 'lowcode')!.artifacts.length).toBe(2)
    expect(r.dependencies.length).toBe(1)
    expect(r.error).toBeNull()
  })

  it('某请求失败 → 该块降级,不整崩', async () => {
    const partial = {
      ...fakeApi,
      listMembers: async () => { throw new Error('boom') },
      listDependencies: async () => { throw new Error('boom') },
    }
    const r = await buildProjectView(7, partial as any)
    expect(r.members).toEqual([])
    expect(r.dependencies).toEqual([])
    expect(r.groups.length).toBeGreaterThan(0) // 工作区仍在
  })
})
