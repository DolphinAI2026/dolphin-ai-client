import { defineStore } from 'pinia'

// 桌面三模式(参考设计): 构建/智能体/全代码。各有色标 + 首页路由 + 左栏导航。
export type AppMode = 'builder' | 'agent' | 'code'

export interface ModeNavItem { key: string; label: string; icon: string; path: string }

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
  // SP2b T9: Code 已并入 Builder 统一外壳(/ai-chat)。MODE_META.code 保留供类型 +
  // localStorage 回退安全, 但 home/nav 全指向 /ai-chat(防御:不再有独立 /coding 入口)。
  code: {
    key: 'code', label: 'Code', sub: '全代码开发', colorVar: '--fullcode', home: '/ai-chat',
    nav: [
      { key: 'c-new', label: '新建会话', icon: 'plus', path: '/ai-chat' },
      { key: 'c-catalog', label: '我的开发', icon: 'store', path: '/workspace-catalog' },
    ],
  },
}

// Agent 暂未接入(得小帆功能后续); Code 已并入 Builder(SP2b T9)。
// 切换器只留 Builder 一段。MODE_META.agent / .code 保留供回退安全, 不在 MODE_ORDER 里 = 不渲染入口。
export const MODE_ORDER: AppMode[] = ['builder']

const MODE_KEY = 'apaas-app-mode-v1'

function loadMode(): AppMode {
  try {
    const v = localStorage.getItem(MODE_KEY)
    if (v === 'builder') return v
    if (v === 'code') return 'builder'   // SP2b T9: Code 入口已撤 → 落 builder(避免进缺失 tab)
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
