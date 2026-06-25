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

export function buildArtifacts(
  project: Record<string, any>,
  workspaces: Array<Record<string, any>>,
): ArtifactVM[] {
  const out: ArtifactVM[] = []
  if (project?.platform_connected && project?.platform_app_id) {
    out.push({
      id: `app:${project.platform_app_id}`,
      name: project.platform_app_name || project.name || '低代码应用',
      mode: 'build',
      summary: '低代码应用',
      status: normalizeArtifactStatus(project.platform_connected ? 'deployed' : 'draft'),
      target: { path: '/chat', query: { project_id: String(project.id) } },
    })
  }
  for (const w of workspaces || []) {
    out.push({
      id: `workspace:${w.id}`,
      name: w.display_name || w.project_name || String(w.id),
      mode: projectTypeToMode(w.project_type),
      summary: projectTypeToLabel(w.project_type),
      status: normalizeArtifactStatus(w.status),
      // SP2b T9: 落统一外壳 /ai-chat 的 code 会话(不再走独立 /coding)。
      target: { path: '/ai-chat', query: { workspace_id: String(w.id), mode: 'code' } },
    })
  }
  return out
}

export interface ResolvedEdge {
  from: ArtifactVM; to: ArtifactVM
  exposeLabel: string; consumeLabel: string; note: string
}
export function resolveDependencies(
  edges: Array<Record<string, any>>,
  artifacts: ArtifactVM[],
): ResolvedEdge[] {
  const byId = new Map(artifacts.map(a => [a.id, a]))
  const out: ResolvedEdge[] = []
  for (const e of edges || []) {
    const from = byId.get(e.from_ref), to = byId.get(e.to_ref)
    if (!from || !to) continue
    out.push({ from, to, exposeLabel: e.expose_label || '', consumeLabel: e.consume_label || '', note: e.note || '' })
  }
  return out
}
