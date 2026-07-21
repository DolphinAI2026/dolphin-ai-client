import { describe, expect, it } from 'vitest'
import {
  CODE_RUNTIME_ACTIVATION_RETRY_DELAYS_MS,
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
})
