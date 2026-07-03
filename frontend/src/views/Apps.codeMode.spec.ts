import { describe, expect, it } from 'vitest'
import appsSource from './Apps.vue?raw'

describe('Apps Code mode entry', () => {
  it('starts a Code session from a d-ai-code application id', () => {
    expect(appsSource).toContain("from '@/stores/mode'")
    expect(appsSource).toContain("from '@/api/codeRuntime'")
    expect(appsSource).toContain("modeStore.mode === 'code'")
    expect(appsSource).toContain('codeRuntimeApi.createSessionFromExternalApp')
    expect(appsSource).toContain('`/code/${created.id}`')
  })

  it('refreshes the outer rail after opening a Code application', () => {
    expect(appsSource).toContain("new CustomEvent('code-rail-refresh')")
    expect(appsSource).toContain('window.dispatchEvent')
  })

  it('loads Code applications from d-ai-code instead of the local application table', () => {
    expect(appsSource).toContain('codeRuntimeApi.listApplications')
    expect(appsSource).toContain('isCodeMode.value ? codeRuntimeApi.listApplications')
    expect(appsSource).toContain("app_type: 'low-code'")
    expect(appsSource).not.toContain("app_type: isCodeMode.value ? 'ai-code' : 'low-code'")
    expect(appsSource).not.toContain("applicationApi.create")
  })

  it('creates a Code application from the Code application list', () => {
    expect(appsSource).toContain('codeRuntimeApi.createApplication')
    expect(appsSource).toContain('startNewCodeApp')
    expect(appsSource).toContain('新建应用')
    expect(appsSource).toContain('创建并打开')
    expect(appsSource).toContain('generateCodeAppCode')
  })
})
