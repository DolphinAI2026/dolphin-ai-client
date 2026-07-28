import { describe, expect, it } from 'vitest'
import apiSource from './codeRuntime.ts?raw'

describe('codeRuntime local recovery API', () => {
  it('uses local session status and recovery routes without Control Plane headers', () => {
    expect(apiSource).toContain('`/code/sessions/${encodedSessionRef}/open-status`')
    expect(apiSource).toContain('`/code/sessions/${encodedSessionRef}/local-runtime/restart`')
    expect(apiSource).toContain('`/code/sessions/${encodedSessionRef}/local-workspace`')
    expect(apiSource).toContain('local_workspace_path: localWorkspacePath')
  })
})
