import { describe, expect, it } from 'vitest'
import appsSource from './Apps.vue?raw'

describe('Apps Code mode entry', () => {
  it('starts a Code session from a d-ai-code application id', () => {
    expect(appsSource).toContain("from '@/stores/mode'")
    expect(appsSource).toContain("from '@/api/codeRuntime'")
    expect(appsSource).toContain('isCodeRoutePath(route.path)')
    expect(appsSource).toContain('codeRuntimeApi.createSessionFromExternalApp')
    expect(appsSource).toContain('`/code/${created.public_id}`')
  })

  it('refreshes the outer rail after opening a Code application', () => {
    expect(appsSource).toContain("new CustomEvent('code-rail-refresh')")
    expect(appsSource).toContain('window.dispatchEvent')
  })

  it('loads Code applications through the shared tenant-scoped store', () => {
    expect(appsSource).toContain("from '@/stores/codeApplications'")
    expect(appsSource).toContain('codeApplications.load')
    expect(appsSource).toContain('tenantId: user.tenantId')
    expect(appsSource).not.toContain('codeMode ? codeRuntimeApi.listApplications')
  })

  it('creates a Code application from the Code application list', () => {
    expect(appsSource).toContain('codeRuntimeApi.createApplication')
    expect(appsSource).toContain('startNewCodeApp')
    expect(appsSource).toContain('新建应用')
    expect(appsSource).toContain('创建并打开')
    expect(appsSource).toContain('generateCodeAppCode')
  })
})
