import { defineStore } from 'pinia'
import type { DesktopWorkspaceEntryScope } from '@/utils/desktop'

// 桌面三模式(参考设计): 构建/智能体/全代码。各有色标 + 首页路由 + 左栏导航。
export type AppMode = 'builder' | 'agent' | 'code'

export interface ModeNavItem {
  key: string
  label: string
  icon: string
  path: string
  desktopOnly?: boolean
}

export interface ModeMeta {
  key: AppMode
  label: string
  sub: string
  /** 模式色 CSS 变量名(design-v3-tokens.css) */
  colorVar: string
  /** 切到该模式落的首页 */
  home: string
  /** 该模式左栏导航(映射现有路由;缺的先指现有/占位) */
  nav: ModeNavItem[]
}

export const MODE_META: Record<AppMode, ModeMeta> = {
  builder: {
    key: 'builder', label: 'Builder', sub: '低代码配置 + 二开', colorVar: '--build', home: '/',
    nav: [
      { key: 'b-new', label: '新建应用', icon: 'plus', path: '/ai-chat' },
      { key: 'b-apps', label: '我的应用', icon: 'apps', path: '/apps' },
      { key: 'b-catalog', label: '我的开发', icon: 'store', path: '/workspace-catalog' },
    ],
  },
  agent: {
    key: 'agent', label: 'Agent', sub: '得小帆智能体', colorVar: '--agent', home: '/',
    nav: [
      { key: 'a-new', label: '新建对话', icon: 'chat', path: '/ai-chat' },
      { key: 'a-skills', label: '技能', icon: 'sparkles', path: '/skills' },
      { key: 'a-prompts', label: '智能体', icon: 'spark', path: '/admin/agent-prompts' },
    ],
  },
  code: {
    key: 'code', label: 'Code', sub: '全代码开发', colorVar: '--fullcode', home: '/code/apps',
    nav: [
      { key: 'c-apps', label: '我的应用', icon: 'apps', path: '/code/apps' },
      { key: 'c-system-assistant', label: '系统助手', icon: 'sparkles', path: '/code/system-assistant' },
    ],
  },
}

// Agent 暂未接入(得小帆功能后续); Builder / Code 作为一等壳层模式。
export const MODE_ORDER: AppMode[] = ['builder', 'code']

export function visibleModesForDesktopScope(scope: DesktopWorkspaceEntryScope): AppMode[] {
  if (scope === 'apaas') return ['builder']
  if (scope === 'ai_platform') return ['code']
  return ['builder', 'code']
}

export function desktopModeLabel(mode: AppMode): 'Builder' | 'Code' {
  return mode === 'code' ? 'Code' : 'Builder'
}

export function visibleModeNav(mode: AppMode, desktop: boolean): ModeNavItem[] {
  return MODE_META[mode].nav.filter(item => desktop || !item.desktopOnly)
}

export function isCodeRoutePath(path: string): boolean {
  return path === '/code' || path.startsWith('/code/')
}

export function modeForRoutePath(path: string): AppMode {
  return isCodeRoutePath(path) ? 'code' : 'builder'
}

const MODE_KEY = 'apaas-app-mode-v1'

function loadMode(): AppMode {
  try {
    const v = localStorage.getItem(MODE_KEY)
    if (v === 'builder') return v
    if (v === 'code') return v
    if (v === 'agent') return 'builder'  // 旧持久化的 agent → 落 builder(入口已撤)
  } catch { /* private mode */ }
  return 'builder'
}

export const useModeStore = defineStore('appMode', {
  state: () => ({ mode: loadMode() as AppMode }),
  getters: {
    meta: (s): ModeMeta => MODE_META[s.mode],
  },
  actions: {
    setMode(m: AppMode) {
      this.mode = m
      try { localStorage.setItem(MODE_KEY, m) } catch { /* private mode */ }
    },
  },
})
