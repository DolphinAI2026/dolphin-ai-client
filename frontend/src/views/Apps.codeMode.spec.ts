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

  it('separates desktop local and remote applications without exposing local UI on web', () => {
    expect(appsSource).toContain('LocalCodeApplicationDialog')
    expect(appsSource).toContain("type CodeApplicationSource")
    expect(appsSource).toContain("isDesktop ? loadStoredCodeApplicationSource('local') : 'remote'")
    expect(appsSource).toContain("source: codeApplicationSource.value")
    expect(appsSource).toContain('本地应用')
    expect(appsSource).toContain('远程应用')
    expect(appsSource).toContain('新建本地应用')
    expect(appsSource).toContain('新建远程应用')
    expect(appsSource).toContain('storeCodeApplicationSource(source)')
    expect(appsSource).not.toContain('ElMessageBox.prompt')
  })

  it('keeps source tabs visible while moving application status into a dropdown filter', () => {
    expect(appsSource).toContain('class="apps-source-switch"')
    expect(appsSource).toContain('class="apps-status-filter"')
    expect(appsSource).toContain('<el-select')
    expect(appsSource).toContain('v-model="activeTab"')
    expect(appsSource).not.toContain('class="apps-tabs"')
  })
})
