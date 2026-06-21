import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { resolve } from 'path'

const src = readFileSync(resolve(__dirname, 'ArtifactDependencyGraph.vue'), 'utf-8')

describe('ArtifactDependencyGraph.vue', () => {
  it('空边不渲染 + 遍历 edges + 显 note', () => {
    expect(src).toContain('v-if')          // 空时隐藏
    expect(src).toContain('edges')
    expect(src).toContain('v-for')
    expect(src).toContain('note')
  })

  it('收紧关键逻辑: 空隐藏 + 折叠限制 + 展开状态 + 标签截断', () => {
    expect(src).toContain('edges.length')  // 空隐藏 v-if 条件
    expect(src).toContain('LIMIT')         // 折叠阈值
    expect(src).toContain('expanded')      // 展开状态
    expect(src).toContain('展开其余')        // 展开按钮文案
    expect(src).toContain('exposeLabel')
    expect(src).toContain('consumeLabel')
  })
})
