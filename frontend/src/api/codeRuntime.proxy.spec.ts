import { describe, expect, it } from 'vitest'
import { resolveCodeRuntimeEmbedUrl } from './codeRuntime'
import apiSource from './codeRuntime.ts?raw'

describe('Code runtime browser-authenticated session APIs', () => {
  it('keeps runtime session operations under the session proxy cookie path', () => {
    expect(apiSource).toContain('listAgentSessions(shellSessionId')
    expect(apiSource).toContain('`/code-runtime/${shellSessionId}/shell/agent-sessions`')
    expect(apiSource).not.toContain('`/code/sessions/${shellSessionId}/agent-sessions`')
  })

  it('adds the deployed application base to runtime iframe URLs', () => {
    expect(resolveCodeRuntimeEmbedUrl('/api/code-runtime/2/builder/', '/ai-builder/'))
      .toBe('/ai-builder/api/code-runtime/2/builder/')
    expect(resolveCodeRuntimeEmbedUrl('/api/code-runtime/2/builder/', '/'))
      .toBe('/api/code-runtime/2/builder/')
  })
})
