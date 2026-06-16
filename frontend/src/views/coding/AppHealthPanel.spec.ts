import { describe, expect, it } from 'vitest'
import src from './AppHealthPanel.vue?raw'

describe('AppHealthPanel', () => {
  it('calls the health endpoint and renders the scorecard', () => {
    expect(src).toContain('/applications/')
    expect(src).toContain('/health')
    expect(src).toContain('total_score')
    expect(src).toContain('has_critical')
    expect(src).toContain('重新体检')
  })

  it('surfaces N/A dimensions and severity-ordered findings', () => {
    expect(src).toContain('数据不可用')
    expect(src).toContain('dim-grid')
    expect(src).toContain('findings')
    expect(src).toContain('severity')
  })

  it('covers loading / error / retry states', () => {
    expect(src).toContain('health-spinner')
    expect(src).toContain('is-error')
    expect(src).toContain('重试')
  })
})
