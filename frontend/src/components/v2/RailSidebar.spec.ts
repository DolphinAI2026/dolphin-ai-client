import { describe, expect, it } from 'vitest'
import railSidebarSource from './RailSidebar.vue?raw'

describe('RailSidebar brand mark', () => {
  it('uses the Ruijing whale mark in the rail logo', () => {
    expect(railSidebarSource).toContain('ruijing-whale-mark.svg')
    expect(railSidebarSource).toContain('rail-logo-mark')
    expect(railSidebarSource).not.toContain('<rect x="3" y="3" width="8" height="8"')
    expect(railSidebarSource).not.toContain('AI · 低代码')
  })
})
