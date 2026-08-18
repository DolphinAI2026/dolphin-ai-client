import { describe, expect, it } from 'vitest'
import {
  CODE_RUNTIME_ACTIVATION_RETRY_DELAYS_MS,
  CODE_RUNTIME_LOCAL_WORKSPACE_OPEN_TIMEOUT_MS,
  CODE_RUNTIME_WORKSPACE_OPEN_TIMEOUT_MS,
  resolveCodeRuntimeEmbedUrl,
} from './codeRuntime'
import apiSource from './codeRuntime.ts?raw'

describe('Code runtime browser-authenticated session APIs', () => {
  it('keeps iframe reads on the proxy cookie path and outer mutations on Builder auth', () => {
    expect(apiSource).toContain('listAgentSessions(shellSessionId')
    expect(apiSource).toContain('`/code-runtime/${shellSessionId}/shell/agent-sessions`')
    expect(apiSource).toContain('`/code/sessions/${encodedShellSessionId}/agent-sessions`')
    expect(apiSource).toContain(
      '`/code/sessions/${encodedShellSessionId}/agent-sessions/${encodeURIComponent(runtimeSessionId)}/activate`',
    )
    expect(apiSource).toContain(
      '`/code/sessions/${encodedShellSessionId}/agent-sessions/${encodeURIComponent(runtimeSessionId)}`',
    )
  })

  it('keeps the outer session rail compatible with backends that predate source=all', () => {
    expect(apiSource).toContain("listRailHistory(source: CodeRailHistorySource = 'all'")
    expect(apiSource).toContain("Number(error?.response?.status) === 422")
    expect(apiSource).toContain("return load('remote')")
  })

  it('adds the deployed application base to runtime iframe URLs', () => {
    expect(resolveCodeRuntimeEmbedUrl('/api/code-runtime/2/builder/', '/ai-builder/'))
      .toBe('/ai-builder/api/code-runtime/2/builder/')
    expect(resolveCodeRuntimeEmbedUrl('/api/code-runtime/2/builder/', '/'))
      .toBe('/api/code-runtime/2/builder/')
  })

  it('declares the complete automatic activation retry schedule', () => {
    expect(CODE_RUNTIME_ACTIVATION_RETRY_DELAYS_MS).toEqual([])
    expect(apiSource).toContain('CODE_RUNTIME_ACTIVATION_RETRY_DELAYS_MS = [] as const')
  })

  it('keeps the browser open request alive beyond the Control Plane cold-start budget', () => {
    expect(CODE_RUNTIME_WORKSPACE_OPEN_TIMEOUT_MS).toBe(690_000)
    expect(CODE_RUNTIME_LOCAL_WORKSPACE_OPEN_TIMEOUT_MS).toBe(150_000)
    expect(apiSource).toContain('options?.local')
    expect(apiSource).toContain('CODE_RUNTIME_LOCAL_WORKSPACE_OPEN_TIMEOUT_MS')
  })
})
