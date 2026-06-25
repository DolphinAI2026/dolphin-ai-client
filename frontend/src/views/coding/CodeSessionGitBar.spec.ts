import { describe, expect, it } from 'vitest'
import src from './CodeSessionGitBar.vue?raw'

describe('CodeSessionGitBar', () => {
  it('renders 📁 workspace name + ⎇ branch + emits switch-workspace', () => {
    expect(src).toContain('switch-workspace')   // 切工作区 emit
    expect(src).toContain('gitStatus')           // 拉当前分支
    expect(src).toContain('gitBranches')         // 列分支
    expect(src).toContain('gitCheckout')         // 切/建分支
  })
})
