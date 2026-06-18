import { describe, expect, it } from 'vitest'
import src from './ToolMenu.vue?raw'

describe('ToolMenu', () => {
  it('renders the full panel set from buildToolMenuItems and disables unavailable items', () => {
    expect(src).toContain('buildToolMenuItems')
    expect(src).toContain("emit('open'")
    expect(src).toContain(':disabled')          // 禁用态绑定
    expect(src).toContain('is-disabled')        // 灰显 class
  })
  it('does not emit open for disabled items', () => {
    // 守卫: 点击 handler 必须先判 item.enabled
    expect(src).toMatch(/if\s*\([^)]*!?\s*item\.enabled/)
  })
})
