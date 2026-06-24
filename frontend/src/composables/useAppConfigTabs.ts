export const APP_CONFIG_TOP_TABS_ENABLED = false
export const SECTION_STORAGE_KEY = 'apaas-section-v1'
export const SECTION_TAB_STORAGE_KEY = 'apaas-section-tab-v1'

export const SECTION_DEFAULT_TAB: Record<string, string> = {
  data: 'models',
  ui: 'menus',
  logic: 'processes',
  permission: 'roles',
  extension: 'dev_kit',
}

export const SECTION_TO_TOP_TAB: Record<string, string> = {
  data: 'data',
  ui: 'design',
  logic: 'logic',
  permission: 'perm',
  extension: 'log',
}

export const SPEC_TAB_ENABLED = false

// 注: 顶部 tab 已收敛为「配置/自开发」(2026-06-24), 旧的 TOP_TAB_SUBS / DESIGNER_SUBS /
// AppConfigSubTab / DesignerSubCode 全部移除 — 零引用。下方常量/函数仍被 ChatPage 用于
// section 存储键 + 落 'design' 的 normalizeTopTab。

export function normalizeTopTab(tab: string): string {
  if (!APP_CONFIG_TOP_TABS_ENABLED) return 'design'
  return (!SPEC_TAB_ENABLED && tab === 'spec') ? 'design' : tab
}

export function getInitialSection(): string {
  if (!APP_CONFIG_TOP_TABS_ENABLED) return 'ui'
  try {
    return localStorage.getItem(SECTION_STORAGE_KEY) || 'ui'
  } catch {
    return 'ui'
  }
}

export function getInitialSectionTab(section: string): string {
  if (!APP_CONFIG_TOP_TABS_ENABLED) return 'menus'
  try {
    const saved = localStorage.getItem(SECTION_TAB_STORAGE_KEY)
    if (saved) return saved
  } catch {
    // private mode
  }
  return SECTION_DEFAULT_TAB[section] || 'menus'
}
