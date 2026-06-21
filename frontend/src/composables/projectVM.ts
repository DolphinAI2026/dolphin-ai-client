// 项目 → 产物视图 view-model(纯函数,可单测;不依赖 DOM/组件)。
export type Mode = 'build' | 'lowcode' | 'fullcode' | 'agent'

export interface ArtifactVM {
  id: string
  name: string
  mode: Mode
  summary: string
  status: { label: string; tone: string }
  target: { path: string; query: Record<string, string> }
}

const FULLCODE = new Set(['backend-api', 'backend-feign', 'backend-scheduled'])
const LOWCODE = new Set(['form-component-dual', 'form-page', 'menu-page', 'mobile-page', 'form-list', 'layout', 'plugin', 'web-login'])

export function projectTypeToMode(pt: string): Mode {
  const s = String(pt || '')
  if (FULLCODE.has(s)) return 'fullcode'
  if (LOWCODE.has(s)) return 'lowcode'
  return 'lowcode'
}

const LABELS: Record<string, string> = {
  'form-list': '表单列表页', 'mobile-page': '移动端页面', 'form-page': '菜单页面',
  'menu-page': '菜单页面', 'form-component-dual': '自开发组件', 'layout': '自定义布局',
  'plugin': '插件', 'web-login': '登录页', 'backend-api': '后端接口',
  'backend-feign': '外部调用', 'backend-scheduled': '定时任务',
}
export function projectTypeToLabel(pt: string): string {
  return LABELS[String(pt || '')] || String(pt || '')
}

export function normalizeArtifactStatus(raw: string): { label: string; tone: string } {
  switch (String(raw || '')) {
    case 'creating':
    case 'installing': return { label: 'AI 在写', tone: 'building' }
    case 'building': return { label: '构建中', tone: 'building' }
    case 'ready': return { label: '已完成', tone: 'done' }
    case 'deployed': return { label: '已部署', tone: 'live' }
    case 'draft': return { label: '草稿', tone: 'draft' }
    case 'error': return { label: '失败', tone: 'error' }
    default: return { label: String(raw || '草稿'), tone: 'draft' }
  }
}
