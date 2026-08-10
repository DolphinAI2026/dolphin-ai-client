import { describe, expect, it } from 'vitest'
import { resolveDesktopWorkspaceRedirect } from './desktopGuard'

describe('desktop workspace scope for legacy coding URLs', () => {
  it('treats a trailing-slash coding URL as a Code route', () => {
    expect(resolveDesktopWorkspaceRedirect('ai_platform', '/coding/')).toBeNull()
    expect(resolveDesktopWorkspaceRedirect('apaas', '/coding/')).toBe('/')
  })
})
