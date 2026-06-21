import { describe, it, expect } from 'vitest'
import { projectTypeToMode, projectTypeToLabel, normalizeArtifactStatus } from '@/composables/projectVM'

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
