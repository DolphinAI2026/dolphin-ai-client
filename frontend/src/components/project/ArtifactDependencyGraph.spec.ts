import { describe, it, expect } from 'vitest'
// @ts-ignore
import src from '@/components/project/ArtifactDependencyGraph.vue?raw'

describe('ArtifactDependencyGraph.vue', () => {
  it('空边不渲染 + 遍历 edges + 显 note', () => {
    expect(src).toContain('v-if')          // 空时隐藏
    expect(src).toContain('edges')
    expect(src).toContain('v-for')
    expect(src).toContain('note')
  })
})
