// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest'

const authMocks = vi.hoisted(() => ({
  createWebConsoleSession: vi.fn(),
}))

vi.mock('@/api/auth', () => ({
  authApi: {
    createWebConsoleSession: authMocks.createWebConsoleSession,
  },
}))

import { recoverWebConsoleRedirect } from './webConsoleSession'

describe('standalone Web Console session recovery', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('recreates the missing Web Console session from an authenticated Builder session', async () => {
    authMocks.createWebConsoleSession.mockResolvedValue({
      access_token: 'web-console-token',
      tenant_id: '840289793437859841',
    })

    const target = await recoverWebConsoleRedirect(
      '/web-console/',
      true,
      '/builder-standalone/',
    )

    expect(target).toBe('/builder-standalone/web-console/')
    expect(localStorage.getItem('access_token')).toBe('web-console-token')
    expect(localStorage.getItem('tenant_id')).toBe('840289793437859841')
  })

  it('does not create a management session before Builder authentication succeeds', async () => {
    const target = await recoverWebConsoleRedirect(
      '/web-console/',
      false,
      '/builder-standalone/',
    )

    expect(target).toBeNull()
    expect(authMocks.createWebConsoleSession).not.toHaveBeenCalled()
    expect(localStorage.getItem('access_token')).toBeNull()
  })
})
