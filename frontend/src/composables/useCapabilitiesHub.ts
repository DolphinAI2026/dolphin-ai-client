export type HubTabKey = 'models' | 'skills' | 'knowledge' | 'mcp' | 'gateway'

export interface HubTab {
  key: HubTabKey
  label: string
  access: 'all' | 'tenantAdmin' | 'platformAdmin'
  /** 桌面 build 隐藏(知识库 desktop:hidden / MCP 平台内部工具不进桌面) */
  desktopHidden: boolean
}

// 四个 tab 全部就地渲染主 app 原生组件(技能库/知识库/McpTools/PlatformEnvs(only=llm)),
// 不再内嵌 admin-spa —— 避免"应用套应用"的嵌套, 统一一致。
export const HUB_TABS: HubTab[] = [
  { key: 'models', label: '模型', access: 'all', desktopHidden: false },
  { key: 'skills', label: '技能库', access: 'all', desktopHidden: false },
  { key: 'knowledge', label: '知识库', access: 'all', desktopHidden: false },
  { key: 'mcp', label: 'MCP', access: 'all', desktopHidden: false },
  { key: 'gateway', label: 'AI 网关', access: 'tenantAdmin', desktopHidden: true },
]

export function visibleTabs(opts: { isPlatformAdmin: boolean; isTenantAdmin: boolean; isDesktop: boolean }): HubTab[] {
  return HUB_TABS.filter((t) => {
    if (t.access === 'platformAdmin' && !opts.isPlatformAdmin) return false
    if (t.access === 'tenantAdmin' && !opts.isTenantAdmin) return false
    if (opts.isDesktop && t.desktopHidden) return false
    return true
  })
}

export function resolveActiveTab(requested: string | undefined, visible: HubTab[]): HubTabKey {
  const hit = visible.find((t) => t.key === requested)
  return hit ? hit.key : (visible[0]?.key ?? 'skills')
}

export const LEGACY_PATH_TO_TAB: Record<string, HubTabKey> = {
  '/skills': 'skills',
  '/knowledge': 'knowledge',
}
