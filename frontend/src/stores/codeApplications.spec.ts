import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { codeRuntimeApi, type CodeApplicationListResponse } from '@/api/codeRuntime'
import { useCodeApplicationsStore } from './codeApplications'

function page(tenant: string): CodeApplicationListResponse {
  return {
    items: [{
      id: `${tenant}-app`,
      external_application_id: `${tenant}-app`,
      app_name: `${tenant} App`,
      app_code: `${tenant}_app`,
      source: 'd-ai-code',
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
    source: 'd-ai-code',
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
})
