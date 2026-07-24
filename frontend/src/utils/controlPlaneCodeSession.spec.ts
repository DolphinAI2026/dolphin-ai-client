import { beforeEach, describe, expect, it, vi } from 'vitest'

const auth = vi.hoisted(() => ({ token: null as string | null }))

vi.mock('@/utils/request', () => ({
  getCommittedAuthToken: () => auth.token,
}))

function codeToken(tenantId: string, tenantName: string) {
  const payload = Buffer.from(JSON.stringify({
    cp_tid: tenantId,
    cp_tname: tenantName,
  })).toString('base64url')
  return `header.${payload}.signature`
}

describe('Control Plane Code session', () => {
  beforeEach(() => {
    vi.resetModules()
    auth.token = null
    const storage = new Map<string, string>()
    vi.stubGlobal('sessionStorage', {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
      removeItem: (key: string) => storage.delete(key),
    })
  })

  it('replaces a stale tab Code ticket with the newly committed login ticket', async () => {
    const stale = codeToken('old-org', 'Old organization')
    const fresh = codeToken('current-org', 'Current organization')
    const session = await import('./controlPlaneCodeSession')

    session.setControlPlaneCodeSession(stale)
    auth.token = fresh

    expect(session.getControlPlaneCodeSession()).toMatchObject({
      token: fresh,
      tenantId: 'current-org',
      tenantName: 'Current organization',
    })
  })

  it('clears the tab Code ticket on logout', async () => {
    const session = await import('./controlPlaneCodeSession')
    session.setControlPlaneCodeSession(codeToken('current-org', 'Current organization'))

    session.clearControlPlaneCodeSession()

    expect(session.getControlPlaneCodeSession()).toBeNull()
  })
})
