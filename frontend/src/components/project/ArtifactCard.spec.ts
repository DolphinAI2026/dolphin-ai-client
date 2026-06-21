import { describe, it, expect } from 'vitest'
// @ts-ignore
import src from '@/components/project/ArtifactCard.vue?raw'

describe('ArtifactCard.vue', () => {
  it('用 artifact prop + 触发 open + 状态点带 aria-label', () => {
    expect(src).toContain('defineProps')
    expect(src).toContain('artifact')
    expect(src).toContain("emit('open'")
    expect(src).toContain('aria-label')
  })
  it('模式色用 css 变量 + 名称 line-clamp', () => {
    expect(src).toMatch(/var\(--\$\{|var\(--' \+|--build|mode/)  // 模式驱动的色
    expect(src).toContain('line-clamp')
  })
})
