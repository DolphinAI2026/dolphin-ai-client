import { describe, expect, it } from 'vitest'
import routerSrc from '@/router/index.ts?raw'
import appsSrc from '@/views/Apps.vue?raw'

// 2026-06-19 三场景重新分开: 撤掉统一工作区入口改道。
// 应用资产库点应用(低代码配置) → 应用工作室 /chat，不再进 /workspace。
describe('apps → /chat (低代码配置场景分开)', () => {
  it('keeps /chat route + ChatPage intact', () => {
    expect(routerSrc).toContain("'@/views/ChatPage.vue'")
  })

  it('Apps.openApp opens the application studio (/chat), not the unified workspace', () => {
    expect(appsSrc).toMatch(/openApp[\s\S]*path:\s*'\/chat'/)
    expect(appsSrc).not.toMatch(/openApp[\s\S]*path:\s*'\/workspace'/)
  })
})
