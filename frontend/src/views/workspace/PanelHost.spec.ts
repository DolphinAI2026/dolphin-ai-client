import { describe, expect, it } from 'vitest'
import src from './PanelHost.vue?raw'

describe('PanelHost', () => {
  it('renders the active panel component from the registry', () => {
    expect(src).toContain('getPanel')
    expect(src).toContain(':is=')                 // 动态组件
  })
  it('has an empty state and an error fallback (never crashes the shell)', () => {
    expect(src).toContain('panel-empty')
    expect(src).toContain('onErrorCaptured')      // 捕获 panel 渲染/加载错
    expect(src).toContain('panel-error')
  })
})
