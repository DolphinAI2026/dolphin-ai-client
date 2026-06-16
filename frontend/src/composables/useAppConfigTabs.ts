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

export type AppConfigSubTab = {
  code: string
  label: string
}

export const TOP_TAB_SUBS: Record<string, AppConfigSubTab[]> = {
  design: [
    { code: 'menus', label: '菜单' },
    { code: 'forms', label: '表单' },
    { code: 'lists', label: '列表' },
  ],
  data: [
    { code: 'models', label: '数据模型' },
    { code: 'dicts', label: '字典' },
  ],
  logic: [
    { code: 'processes', label: '流程' },
    { code: 'events', label: '业务事件' },
  ],
  perm: [
    { code: 'roles', label: '角色' },
    { code: 'field_perm', label: '字段权限' },
    { code: 'menu_vis', label: '菜单可见性' },
  ],
  log: [
    { code: 'op_log', label: '操作日志' },
    { code: 'deploy_history', label: '部署历史' },
  ],
}

export const DESIGNER_SUBS = [
  { code: 'form', label: '表单设计' },
  { code: 'list', label: '列表设计' },
  { code: 'process', label: '流程设计' },
  { code: 'data', label: '数据模型' },
  { code: 'perm', label: '权限' },
  { code: 'dev', label: '自开发' },
  { code: 'health', label: '体检' },
] as const

export type DesignerSubCode = typeof DESIGNER_SUBS[number]['code'] | 'event'

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
