import { describe, expect, it } from 'vitest'
import { visibleTabs, resolveActiveTab, HUB_TABS, LEGACY_PATH_TO_TAB } from './useCapabilitiesHub'

describe('useCapabilitiesHub', () => {
  it('普通用户(非租户/平台管理员)只看到技能库', () => {
    expect(visibleTabs({ isPlatformAdmin: false, isTenantAdmin: false, isDesktop: false }).map((t) => t.key))
      .toEqual(['skills'])
  })
  it('租户管理员看到 技能库 + AI网关(模型配置)', () => {
    expect(visibleTabs({ isPlatformAdmin: false, isTenantAdmin: true, isDesktop: false }).map((t) => t.key))
      .toEqual(['skills', 'gateway'])
  })
  it('平台管理员看到全部 4 个', () => {
    expect(visibleTabs({ isPlatformAdmin: true, isTenantAdmin: true, isDesktop: false }).map((t) => t.key))
      .toEqual(['skills', 'knowledge', 'mcp', 'gateway'])
  })
  it('桌面端(管理员)只看到 技能库 + AI网关(知识库/MCP 桌面隐藏)', () => {
    expect(visibleTabs({ isPlatformAdmin: true, isTenantAdmin: true, isDesktop: true }).map((t) => t.key))
      .toEqual(['skills', 'gateway'])
  })
  it('请求不可见 tab → 回落到第一个可见(技能库)', () => {
    const vis = visibleTabs({ isPlatformAdmin: false, isTenantAdmin: false, isDesktop: false })
    expect(resolveActiveTab('knowledge', vis)).toBe('skills')
  })
  it('请求可见 tab → 命中', () => {
    const vis = visibleTabs({ isPlatformAdmin: true, isTenantAdmin: true, isDesktop: false })
    expect(resolveActiveTab('mcp', vis)).toBe('mcp')
  })
  it('无请求 → 第一个可见', () => {
    const vis = visibleTabs({ isPlatformAdmin: true, isTenantAdmin: true, isDesktop: false })
    expect(resolveActiveTab(undefined, vis)).toBe('skills')
  })
  it('tab 访问层级正确', () => {
    const get = (k: string) => HUB_TABS.find((t) => t.key === k)!
    expect(get('skills').access).toBe('all')
    expect(get('gateway').access).toBe('tenantAdmin')
    expect(get('knowledge').access).toBe('platformAdmin')
    expect(get('mcp').access).toBe('platformAdmin')
  })
  it('老路径映射', () => {
    expect(LEGACY_PATH_TO_TAB['/skills']).toBe('skills')
    expect(LEGACY_PATH_TO_TAB['/knowledge']).toBe('knowledge')
  })
})
