import { describe, expect, it } from 'vitest'
import componentSource from './CodeWorkspaceOpening.vue?raw'

describe('CodeWorkspaceOpening', () => {
  it('shows the three local workspace phases and elapsed time', () => {
    expect(componentSource).toContain('检查本地项目')
    expect(componentSource).toContain('启动本地环境')
    expect(componentSource).toContain('打开 Code 工作台')
    expect(componentSource).toContain('elapsedSeconds')
    expect(componentSource).toContain('startedAt')
    expect(componentSource).toContain('<details')
  })

  it('keeps recovery actions in the current page', () => {
    expect(componentSource).toContain("'retry'")
    expect(componentSource).toContain("'back'")
    expect(componentSource).toContain("'restart'")
    expect(componentSource).toContain("'rebind'")
    expect(componentSource).toContain('重新绑定目录')
    expect(componentSource).toContain('重启本地环境')
  })
})
