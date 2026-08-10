import { describe, it, expect } from 'vitest'
import { projectTypeToMode, projectTypeToLabel, normalizeArtifactStatus, buildArtifacts, resolveDependencies } from '@/composables/projectVM'

describe('projectTypeToMode', () => {
  it('backend-* → fullcode', () => {
    for (const t of ['backend-api', 'backend-feign', 'backend-scheduled'])
      expect(projectTypeToMode(t)).toBe('fullcode')
  })
  it('前端自开发类 → lowcode', () => {
    for (const t of ['form-component-dual', 'form-page', 'menu-page', 'mobile-page', 'form-list', 'layout', 'plugin', 'web-login'])
      expect(projectTypeToMode(t)).toBe('lowcode')
  })
  it('未知 → lowcode 兜底', () => {
    expect(projectTypeToMode('???')).toBe('lowcode')
  })
})

describe('projectTypeToLabel', () => {
  it('已知值给中文标签', () => {
    expect(projectTypeToLabel('form-list')).toBe('表单列表页')
    expect(projectTypeToLabel('backend-api')).toBe('后端接口')
  })
  it('未知值回原文', () => {
    expect(projectTypeToLabel('xyz')).toBe('xyz')
  })
})

describe('normalizeArtifactStatus', () => {
  it('按词表映射', () => {
    expect(normalizeArtifactStatus('building')).toEqual({ label: '构建中', tone: 'building' })
    expect(normalizeArtifactStatus('ready')).toEqual({ label: '已完成', tone: 'done' })
    expect(normalizeArtifactStatus('creating')).toEqual({ label: 'AI 在写', tone: 'building' })
    expect(normalizeArtifactStatus('deployed')).toEqual({ label: '已部署', tone: 'live' })
    expect(normalizeArtifactStatus('draft')).toEqual({ label: '草稿', tone: 'draft' })
    expect(normalizeArtifactStatus('error')).toEqual({ label: '失败', tone: 'error' })
  })
  it('未知 → draft tone + 原文', () => {
    expect(normalizeArtifactStatus('weird')).toEqual({ label: 'weird', tone: 'draft' })
  })
})

describe('buildArtifacts', () => {
  it('连平台时含应用本体 + 工作区,各带跳转目标', () => {
    const project: any = { id: 7, platform_connected: true, platform_app_id: 'APP1', platform_app_name: '工单配置端', name: 'p' }
    const ws: any = [{ id: 'ws1', project_type: 'mobile-page', display_name: '移动端报修', status: 'building' }]
    const arts = buildArtifacts(project, ws)
    const app = arts.find(a => a.mode === 'build')!
    expect(app.target).toEqual({ path: '/chat', query: { project_id: '7' } })
    const w = arts.find(a => a.id === 'workspace:ws1')!
    expect(w.mode).toBe('lowcode')
    expect(w.summary).toBe('移动端页面')
    expect(w.status).toEqual({ label: '构建中', tone: 'building' })
    expect(w.target).toEqual({ path: '/code/apps', query: {} })
  })
  it('未连平台 → 无应用本体', () => {
    const arts = buildArtifacts({ id: 1, platform_connected: false } as any, [])
    expect(arts.length).toBe(0)
  })
})

describe('resolveDependencies', () => {
  it('按 ref 匹配产物,悬空跳过', () => {
    const arts = buildArtifacts({ id: 1, platform_connected: false } as any,
      [{ id: 'a', project_type: 'form-list', status: 'ready' } as any,
       { id: 'b', project_type: 'mobile-page', status: 'ready' } as any])
    const edges = [
      { from_ref: 'workspace:a', to_ref: 'workspace:b', expose_label: 'X', consume_label: 'Y', note: 'n' },
      { from_ref: 'workspace:a', to_ref: 'workspace:gone', expose_label: 'X', consume_label: 'Y', note: '' },
    ]
    const out = resolveDependencies(edges, arts)
    expect(out.length).toBe(1)
    expect(out[0].from.id).toBe('workspace:a')
    expect(out[0].to.id).toBe('workspace:b')
    expect(out[0].exposeLabel).toBe('X')
  })
})
