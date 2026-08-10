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
  let storage: Map<string, string>

  beforeEach(() => {
    vi.resetModules()
    auth.token = null
    storage = new Map<string, string>()
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

  it('keeps an explicit organization ticket across reload until the committed login changes', async () => {
    const source = codeToken('admin-org', 'Admin organization')
    const target = codeToken('target-org', 'Target organization')
    const fresh = codeToken('fresh-org', 'Fresh organization')
    auth.token = source
    const session = await import('./controlPlaneCodeSession')

    expect(session.setExplicitControlPlaneCodeSession(target, source, 'target-org')).toMatchObject({
      token: target,
      tenantId: 'target-org',
    })
    expect(storage.size).toBe(1)
    vi.resetModules()
    const reloadedSession = await import('./controlPlaneCodeSession')
    expect(reloadedSession.getControlPlaneCodeSession()).toMatchObject({
      token: target,
      tenantId: 'target-org',
    })

    auth.token = fresh
    expect(reloadedSession.getControlPlaneCodeSession()).toMatchObject({
      token: fresh,
      tenantId: 'fresh-org',
    })
    expect(storage.size).toBe(1)
  })

  it('replaces the explicit organization record when login mirrors a committed token', async () => {
    const source = codeToken('admin-org', 'Admin organization')
    const target = codeToken('target-org', 'Target organization')
    auth.token = source
    const session = await import('./controlPlaneCodeSession')

    session.setExplicitControlPlaneCodeSession(target, source, 'target-org')
    expect(session.setControlPlaneCodeSession(source)).toMatchObject({ tenantId: 'admin-org' })
    expect(session.getControlPlaneCodeSession()).toMatchObject({
      token: source,
      tenantId: 'admin-org',
    })
  })

  it('preserves the previous explicit organization when the atomic replacement fails', async () => {
    const source = codeToken('admin-org', 'Admin organization')
    const first = codeToken('first-org', 'First organization')
    const second = codeToken('second-org', 'Second organization')
    auth.token = source
    const session = await import('./controlPlaneCodeSession')
    session.setExplicitControlPlaneCodeSession(first, source, 'first-org')
    vi.stubGlobal('sessionStorage', {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: () => { throw new Error('quota exceeded') },
      removeItem: (key: string) => storage.delete(key),
    })

    expect(
      session.setExplicitControlPlaneCodeSession(second, source, 'second-org'),
    ).toBeNull()
    expect(session.getControlPlaneCodeSession()).toMatchObject({
      token: first,
      tenantId: 'first-org',
    })
  })

  it('uses an ordinary stored Code ticket while the committed token is temporarily unavailable', async () => {
    const stored = codeToken('stored-org', 'Stored organization')
    const session = await import('./controlPlaneCodeSession')

    session.setControlPlaneCodeSession(stored)

    expect(session.getControlPlaneCodeSession()).toMatchObject({
      token: stored,
      tenantId: 'stored-org',
    })
  })

  it('clears the tab Code ticket on logout', async () => {
    const session = await import('./controlPlaneCodeSession')
    session.setControlPlaneCodeSession(codeToken('current-org', 'Current organization'))

    session.clearControlPlaneCodeSession()

    expect(session.getControlPlaneCodeSession()).toBeNull()
  })
})
