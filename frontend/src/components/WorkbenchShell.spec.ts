import { describe, it, expect } from 'vitest'
import src from './WorkbenchShell.vue?raw'

// 2026-06-21: 修「Code 模式点会话左栏放大一下又缩小」抖动。
// 根因: codingFocus 把左栏宽度绑在 route.query.workspace_id 上(有=176px, 无=224px),
// 导航换会话时中途路由没 workspace_id → 左栏 224→176 闪一下。
// 修法: 去掉这套随 workspace_id 变宽的逻辑, 左栏恒定宽度, 不再抖动。
describe('WorkbenchShell rail width is stable (no coding-focus flicker)', () => {
  it('does not tie rail width to workspace_id (no codingFocus / coding-focus shrink)', () => {
    expect(src).not.toContain('codingFocus')
    expect(src).not.toContain('workbench-coding-focus')
  })
})
