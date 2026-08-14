import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { codeRuntimeApi, type CodeApplicationListResponse } from '@/api/codeRuntime'
import { useCodeApplicationsStore } from './codeApplications'

function page(tenant: string, source: 'd-ai-code' | 'desktop-local' = 'd-ai-code'): CodeApplicationListResponse {
  return {
    items: [{
      id: `${tenant}-app`,
      external_application_id: `${tenant}-app`,
      app_name: `${tenant} App`,
      app_code: `${tenant}_app`,
      source,
      app_type: 'ai-code',
      status: 'ready',
      models: 0,
      forms: 0,
      roles: 0,
      dicts: 0,
    }],
    page: 1,
    pageSize: 100,
    total: 1,
    source,
  }
}

describe('code applications store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  it('joins concurrent requests for the same tenant and params', async () => {
    let resolveRequest!: (value: CodeApplicationListResponse) => void
    const upstream = new Promise<CodeApplicationListResponse>((resolve) => {
      resolveRequest = resolve
    })
    const list = vi.spyOn(codeRuntimeApi, 'listApplications').mockReturnValue(upstream)
    const store = useCodeApplicationsStore()
    const scope = { tenantId: 3 }

    const first = store.load(scope, { pageSize: 100 })
    const second = store.load(scope, { pageSize: 100 })
    expect(list).toHaveBeenCalledTimes(1)

    resolveRequest(page('tenant-3'))
    await expect(first).resolves.toEqual(page('tenant-3'))
    await expect(second).resolves.toEqual(page('tenant-3'))
  })

  it('never shares cached pages across tenants', async () => {
    const list = vi.spyOn(codeRuntimeApi, 'listApplications')
      .mockResolvedValueOnce(page('tenant-2'))
      .mockResolvedValueOnce(page('tenant-3'))
    const store = useCodeApplicationsStore()

    await expect(store.load({ tenantId: 2 }, { pageSize: 100 }))
      .resolves.toEqual(page('tenant-2'))
    await expect(store.load({ tenantId: 3 }, { pageSize: 100 }))
      .resolves.toEqual(page('tenant-3'))
    expect(list).toHaveBeenCalledTimes(2)
  })

  it('never shares cached pages across local and remote sources', async () => {
    const list = vi.spyOn(codeRuntimeApi, 'listApplications')
      .mockResolvedValueOnce(page('local', 'desktop-local'))
      .mockResolvedValueOnce(page('remote'))
    const store = useCodeApplicationsStore()
    const scope = { tenantId: 3 }

    await expect(store.load(scope, { source: 'local', pageSize: 100 }))
      .resolves.toEqual(page('local', 'desktop-local'))
    await expect(store.load(scope, { source: 'remote', pageSize: 100 }))
      .resolves.toEqual(page('remote'))
    expect(list).toHaveBeenNthCalledWith(1, expect.objectContaining({ source: 'local' }))
    expect(list).toHaveBeenNthCalledWith(2, expect.objectContaining({ source: 'remote' }))
  })

  it('loads local and remote in parallel and reports failures independently', async () => {
    let resolveLocal!: (value: CodeApplicationListResponse) => void
    let rejectRemote!: (reason: Error) => void
    const local = new Promise<CodeApplicationListResponse>(resolve => { resolveLocal = resolve })
    const remote = new Promise<CodeApplicationListResponse>((_resolve, reject) => { rejectRemote = reject })
    const list = vi.spyOn(codeRuntimeApi, 'listApplications')
      .mockReturnValueOnce(local)
      .mockReturnValueOnce(remote)
    const store = useCodeApplicationsStore()

    const pending = store.loadLocations(
      { tenantId: 3 },
      ['local', 'remote'],
      { pageSize: 100 },
    )
    expect(list).toHaveBeenCalledTimes(2)

    resolveLocal(page('local', 'desktop-local'))
    rejectRemote(new Error('remote unavailable'))

    await expect(pending).resolves.toMatchObject({
      local: { status: 'fulfilled', value: page('local', 'desktop-local') },
      remote: { status: 'rejected' },
    })
  })

  it('uses the fresh TTL cache and supports an explicit refresh', async () => {
    const list = vi.spyOn(codeRuntimeApi, 'listApplications')
      .mockResolvedValueOnce(page('first'))
      .mockResolvedValueOnce(page('refreshed'))
    const store = useCodeApplicationsStore()
    const scope = { tenantId: 3, tenantEpoch: 0 }

    await store.load(scope, { pageSize: 100 })
    await expect(store.load(scope, { pageSize: 100 })).resolves.toEqual(page('first'))
    await expect(store.load(scope, { pageSize: 100 }, { force: true }))
      .resolves.toEqual(page('refreshed'))
    expect(list).toHaveBeenCalledTimes(2)
  })

  it('joins concurrent force refreshes when no request is active', async () => {
    let resolveRequest!: (value: CodeApplicationListResponse) => void
    const upstream = new Promise<CodeApplicationListResponse>((resolve) => {
      resolveRequest = resolve
    })
    const list = vi.spyOn(codeRuntimeApi, 'listApplications').mockReturnValue(upstream)
    const store = useCodeApplicationsStore()
    const scope = { tenantId: 3 }

    const first = store.load(scope, { pageSize: 100 }, { force: true })
    const second = store.load(scope, { pageSize: 100 }, { force: true })
    expect(list).toHaveBeenCalledTimes(1)

    resolveRequest(page('forced'))
    await expect(first).resolves.toEqual(page('forced'))
    await expect(second).resolves.toEqual(page('forced'))
    expect(list).toHaveBeenCalledTimes(1)
  })

  it('queues one shared force refresh behind an existing request', async () => {
    let resolveFirst!: (value: CodeApplicationListResponse) => void
    let resolveRefresh!: (value: CodeApplicationListResponse) => void
    const firstUpstream = new Promise<CodeApplicationListResponse>((resolve) => {
      resolveFirst = resolve
    })
    const refreshUpstream = new Promise<CodeApplicationListResponse>((resolve) => {
      resolveRefresh = resolve
    })
    const list = vi.spyOn(codeRuntimeApi, 'listApplications')
      .mockReturnValueOnce(firstUpstream)
      .mockReturnValueOnce(refreshUpstream)
    const store = useCodeApplicationsStore()
    const scope = { tenantId: 3 }

    const first = store.load(scope, { pageSize: 100 })
    const forced = store.load(scope, { pageSize: 100 }, { force: true })
    const joinedForce = store.load(scope, { pageSize: 100 }, { force: true })
    expect(list).toHaveBeenCalledTimes(1)

    resolveFirst(page('stale'))
    await expect(first).resolves.toEqual(page('stale'))
    expect(list).toHaveBeenCalledTimes(2)

    resolveRefresh(page('fresh'))
    await expect(forced).resolves.toEqual(page('fresh'))
    await expect(joinedForce).resolves.toEqual(page('fresh'))
    expect(list).toHaveBeenCalledTimes(2)
  })

  it('runs a queued force refresh after the existing request fails', async () => {
    let rejectFirst!: (reason: Error) => void
    let resolveRefresh!: (value: CodeApplicationListResponse) => void
    const firstUpstream = new Promise<CodeApplicationListResponse>((_resolve, reject) => {
      rejectFirst = reject
    })
    const refreshUpstream = new Promise<CodeApplicationListResponse>((resolve) => {
      resolveRefresh = resolve
    })
    const list = vi.spyOn(codeRuntimeApi, 'listApplications')
      .mockReturnValueOnce(firstUpstream)
      .mockReturnValueOnce(refreshUpstream)
    const store = useCodeApplicationsStore()
    const scope = { tenantId: 3 }

    const first = store.load(scope, { pageSize: 100 })
    const forced = store.load(scope, { pageSize: 100 }, { force: true })
    const firstResult = expect(first).rejects.toThrow('upstream failed')
    expect(list).toHaveBeenCalledTimes(1)

    rejectFirst(new Error('upstream failed'))
    await firstResult
    expect(list).toHaveBeenCalledTimes(2)

    resolveRefresh(page('recovered'))
    await expect(forced).resolves.toEqual(page('recovered'))
  })

  it('keeps singleflight across clear and drops stale cache writes', async () => {
    let resolveRequest!: (value: CodeApplicationListResponse) => void
    const upstream = new Promise<CodeApplicationListResponse>((resolve) => {
      resolveRequest = resolve
    })
    const list = vi.spyOn(codeRuntimeApi, 'listApplications').mockReturnValue(upstream)
    const store = useCodeApplicationsStore()
    const scope = { tenantId: 3 }

    const first = store.load(scope, { pageSize: 100 })
    store.clear()
    const second = store.load(scope, { pageSize: 100 })
    expect(list).toHaveBeenCalledTimes(1)

    resolveRequest(page('stale'))
    await expect(first).resolves.toEqual(page('stale'))
    await expect(second).resolves.toEqual(page('stale'))

    list.mockResolvedValueOnce(page('fresh'))
    await expect(store.load(scope, { pageSize: 100 })).resolves.toEqual(page('fresh'))
    expect(list).toHaveBeenCalledTimes(2)
  })
})
