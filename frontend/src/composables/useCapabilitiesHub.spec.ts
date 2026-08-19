import { describe, expect, it } from 'vitest'
import { visibleTabs, resolveActiveTab, HUB_TABS, LEGACY_PATH_TO_TAB } from './useCapabilitiesHub'

describe('useCapabilitiesHub', () => {
  it('普通用户可管理模型、技能、知识库和 MCP', () => {
    expect(visibleTabs({ isPlatformAdmin: false, isTenantAdmin: false, isDesktop: false }).map((t) => t.key))
      .toEqual(['models', 'skills', 'knowledge', 'mcp'])
  })
  it('租户管理员额外看到 AI 网关', () => {
    expect(visibleTabs({ isPlatformAdmin: false, isTenantAdmin: true, isDesktop: false }).map((t) => t.key))
      .toEqual(['models', 'skills', 'knowledge', 'mcp', 'gateway'])
  })
  it('平台管理员看到全部能力入口', () => {
    expect(visibleTabs({ isPlatformAdmin: true, isTenantAdmin: true, isDesktop: false }).map((t) => t.key))
      .toEqual(['models', 'skills', 'knowledge', 'mcp', 'gateway'])
  })
  it('桌面端隐藏仅适用于 AI 网关', () => {
    expect(visibleTabs({ isPlatformAdmin: true, isTenantAdmin: true, isDesktop: true }).map((t) => t.key))
      .toEqual(['models', 'skills', 'knowledge', 'mcp'])
  })
  it('请求不可见 tab → 回落到第一个可见(模型)', () => {
    const vis = visibleTabs({ isPlatformAdmin: false, isTenantAdmin: false, isDesktop: false })
    expect(resolveActiveTab('gateway', vis)).toBe('models')
  })
  it('请求可见 tab → 命中', () => {
    const vis = visibleTabs({ isPlatformAdmin: true, isTenantAdmin: true, isDesktop: false })
    expect(resolveActiveTab('mcp', vis)).toBe('mcp')
  })
  it('无请求 → 第一个可见', () => {
    const vis = visibleTabs({ isPlatformAdmin: true, isTenantAdmin: true, isDesktop: false })
    expect(resolveActiveTab(undefined, vis)).toBe('models')
  })
  it('tab 访问层级正确', () => {
    const get = (k: string) => HUB_TABS.find((t) => t.key === k)!
    expect(get('models').access).toBe('all')
    expect(get('skills').access).toBe('all')
    expect(get('gateway').access).toBe('tenantAdmin')
    expect(get('knowledge').access).toBe('all')
    expect(get('mcp').access).toBe('all')
  })
  it('老路径映射', () => {
    expect(LEGACY_PATH_TO_TAB['/skills']).toBe('skills')
    expect(LEGACY_PATH_TO_TAB['/knowledge']).toBe('knowledge')
  })
})
