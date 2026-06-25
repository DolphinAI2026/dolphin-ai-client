import { describe, expect, it } from 'vitest'
import src from './CodeSessionGitBar.vue?raw'

describe('CodeSessionGitBar', () => {
  it('renders 📁 固定工作区标签(不切换)+ ⎇ branch', () => {
    expect(src).toContain('git-chip--static')    // 工作区是固定标签,非可切换下拉
    expect(src).not.toContain('switch-workspace') // 已移除工作区切换器(从「我的开发」进来即锁定)
    expect(src).toContain('gitStatus')           // 拉当前分支
    expect(src).toContain('gitBranches')         // 列分支
    expect(src).toContain('gitCheckout')         // 切/建分支
  })

  it('P2: has gitConnect / gitPush / gitPull + 连接 git button', () => {
    expect(src).toContain('gitConnect')          // 绑定远程仓
    expect(src).toContain('gitPush')             // push 到远程
    expect(src).toContain('gitPull')             // 从远程 pull
    expect(src).toContain('连接 git')            // 未连时显示的按钮文案
  })
})
