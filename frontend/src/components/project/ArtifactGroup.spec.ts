import { describe, it, expect } from 'vitest'
// @ts-ignore
import src from '@/components/project/ArtifactGroup.vue?raw'

describe('ArtifactGroup.vue', () => {
  it('渲染 label + 遍历 artifacts 用 ArtifactCard + 网格', () => {
    expect(src).toContain('ArtifactCard')
    expect(src).toContain('v-for')
    expect(src).toContain('label')
    expect(src).toContain('minmax(200px')
  })
})
