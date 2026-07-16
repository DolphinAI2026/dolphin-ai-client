import { describe, expect, it } from 'vitest'
import pageSource from './CodeConversationPage.vue?raw'

describe('CodeConversationPage', () => {
  it('opens a Dolphin Code session and renders the d-ai-code iframe', () => {
    expect(pageSource).toContain("from '@/api/codeRuntime'")
    expect(pageSource).toContain('codeRuntimeApi.openSession')
    expect(pageSource).toContain('<iframe')
    expect(pageSource).toContain(':src="frame.url"')
    expect(pageSource).toContain('message')
    expect(pageSource).toContain('agent.sessionStateChanged')
  })

  it('does not own WorkbenchShell; the /code parent route keeps the rail mounted', () => {
    expect(pageSource).not.toContain("import WorkbenchShell")
    expect(pageSource).not.toContain('<WorkbenchShell>')
  })

  it('refreshes the outer rail after opening the runtime session', () => {
    expect(pageSource).toContain("new CustomEvent('code-rail-refresh')")
    expect(pageSource).toContain('window.dispatchEvent')
  })

  it('refreshes the outer rail when the embedded runtime reports session state changes', () => {
    const handlerSource = pageSource.slice(pageSource.indexOf('function onShellMessage'))

    expect(handlerSource).toContain("data.type === 'agent.sessionStateChanged'")
    expect(handlerSource).toContain('refreshOuterCodeRail()')
  })

  it('keeps the old Code iframe visible while the next iframe loads', () => {
    expect(pageSource).toContain('v-for="frame in frames"')
    expect(pageSource).toContain('code-frame-pending')
    expect(pageSource).toContain('promotePendingFrame(frame.key)')
    expect(pageSource).toContain('frameSwitching')
    expect(pageSource).not.toContain('v-if="loading" class="code-status"')
  })

  it('opens the sandbox before activating the route agent so restore is not overwritten', () => {
    expect(pageSource).toContain('function currentRuntimeAgentId()')
    expect(pageSource).toContain('function currentSessionRef(): string')
    expect(pageSource).toContain('codeRuntimeApi.openSession(sessionRef)')
    expect(pageSource).toContain('codeRuntimeApi.activateAgentSession(opened.session_id, runtimeAgentId)')
    expect(pageSource).toContain('runtimeAgentId && opened.runtime_session_id !== runtimeAgentId')
    expect(pageSource.indexOf('codeRuntimeApi.openSession(sessionRef)'))
      .toBeLessThan(pageSource.indexOf('codeRuntimeApi.activateAgentSession(opened.session_id, runtimeAgentId)'))
    expect(pageSource.indexOf('codeRuntimeApi.activateAgentSession(opened.session_id, runtimeAgentId)'))
      .toBeLessThan(pageSource.indexOf('queuePendingFrame(opened.embed_url)'))
  })

  it('drops stale route agent query when the runtime session no longer exists', () => {
    expect(pageSource).toContain('function isUnavailableRuntimeSessionError')
    expect(pageSource).toContain('function clearRouteAgentQueryIfCurrent')
    expect(pageSource).toContain('delete query.agent')
    expect(pageSource).toContain('isUnavailableRuntimeSessionError(activationError, runtimeAgentId)')
  })

  it('supports a new-application conversation before switching into the sandbox', () => {
    expect(pageSource).toContain('isCreateApplicationRoute')
    expect(pageSource).toContain("route.path.endsWith('/code/new')")
    expect(pageSource).toContain("rawId === 'new'")
    expect(pageSource).toContain('新建 Code 应用')
    expect(pageSource).toContain('确认创建')
    expect(pageSource).toContain('codeRuntimeApi.createApplication')
    expect(pageSource).toContain('codeRuntimeApi.createSessionFromExternalApp')
    expect(pageSource).toContain('`/code/${created.public_id}`')
    expect(pageSource).toContain('opened.session_id !== sessionRef')
    expect(pageSource).toContain('router.replace')
  })

  it('uses a Builder-style empty page for the Code new-application conversation', () => {
    expect(pageSource).toContain('code-new-empty')
    expect(pageSource).toContain('全代码应用工作台')
    expect(pageSource).toContain('描述你要开发的系统、页面和关键能力')
    expect(pageSource).toContain('创建后会进入独立沙箱')
    expect(pageSource).toContain('code-new-suggestions')
    expect(pageSource).toContain('generateCodeAppFromSuggestion')
    expect(pageSource).toContain('销售线索评分与跟进助手')
  })
})
