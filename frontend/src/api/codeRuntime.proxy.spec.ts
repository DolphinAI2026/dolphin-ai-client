import { describe, expect, it } from 'vitest'
import apiSource from './codeRuntime.ts?raw'

describe('Code runtime browser-authenticated session APIs', () => {
  it('keeps runtime session operations under the session proxy cookie path', () => {
    expect(apiSource).toContain('listAgentSessions(shellSessionId')
    expect(apiSource).toContain('`/code-runtime/${shellSessionId}/shell/agent-sessions`')
    expect(apiSource).not.toContain('`/code/sessions/${shellSessionId}/agent-sessions`')
  })
})
