import { describe, it, expect } from 'vitest'
// @ts-ignore
import src from '@/views/ProjectOverview.vue?raw'

describe('ProjectOverview.vue 重写', () => {
  it('用 useProjectArtifacts + ArtifactGroup + 依赖图', () => {
    expect(src).toContain('useProjectArtifacts')
    expect(src).toContain('ArtifactGroup')
    expect(src).toContain('ArtifactDependencyGraph')
  })
  it('点产物用 artifact.target 跳转', () => {
    expect(src).toContain('.target')
    expect(src).toContain('router.push')
  })
  it('置灰动作 tooltip 文案 + loading 骨架 + 空态', () => {
    expect(src).toContain('即将支持')
    expect(src).toMatch(/skeleton|loading/)
    expect(src).toContain('还没有产物')
  })
})
