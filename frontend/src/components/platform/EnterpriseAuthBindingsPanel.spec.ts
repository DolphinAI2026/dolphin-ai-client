import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/utils/request', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}))

import request from '@/utils/request'

const requestMock = request as unknown as {
  get: ReturnType<typeof vi.fn>
  post: ReturnType<typeof vi.fn>
  put: ReturnType<typeof vi.fn>
  delete: ReturnType<typeof vi.fn>
}

describe('enterprise auth pure contracts', () => {
  it('allows bindings only between different providers and accounts', async () => {
    const { isEnterpriseAuthBindingPairAllowed } = await import('@/api/enterpriseAuth')

    expect(isEnterpriseAuthBindingPairAllowed(
      { id: 3, provider: 'apaas' },
      { id: 9, provider: 'control_plane' },
    )).toBe(true)
    expect(isEnterpriseAuthBindingPairAllowed(
      { id: 3, provider: 'apaas' },
      { id: 9, provider: 'apaas' },
    )).toBe(false)
    expect(isEnterpriseAuthBindingPairAllowed(
      { id: 3, provider: 'apaas' },
      { id: 3, provider: 'control_plane' },
    )).toBe(false)
  })

  it('requires a password only when provider, account, or base URL origin changes', async () => {
    const { hasEnterpriseAuthIdentitySourceChanged } = await import('@/api/enterpriseAuth')
    const original = {
      provider: 'apaas' as const,
      base_url: 'https://apaas.example.com/api',
      account: 'admin',
    }

    expect(hasEnterpriseAuthIdentitySourceChanged(original, {
      ...original,
      base_url: 'https://apaas.example.com/other',
    })).toBe(false)
    expect(hasEnterpriseAuthIdentitySourceChanged(original, {
      ...original,
      provider: 'control_plane',
    })).toBe(true)
    expect(hasEnterpriseAuthIdentitySourceChanged(original, {
      ...original,
      account: 'operator',
    })).toBe(true)
    expect(hasEnterpriseAuthIdentitySourceChanged(original, {
      ...original,
      base_url: 'http://apaas.example.com/api',
    })).toBe(true)
    expect(hasEnterpriseAuthIdentitySourceChanged(original, {
      ...original,
      base_url: 'https://apaas.example.com:8443/api',
    })).toBe(true)
  })

  it('omits a blank edit password from the update payload', async () => {
    const { buildEnterpriseAuthAccountUpdatePayload } = await import('@/api/enterpriseAuth')
    const payload = buildEnterpriseAuthAccountUpdatePayload({
      provider: 'control_plane',
      base_url: 'https://cp.example.com',
      tenant_ref: 'tenant-b',
      tenant_name: '',
      account: 'operator',
      password: '   ',
      enabled: true,
    })

    expect(payload).not.toHaveProperty('password')
    expect(payload).toMatchObject({
      tenant_name: null,
      account: 'operator',
    })
  })

  it('redacts credential fragments and truncates account errors', async () => {
    const { sanitizeEnterpriseAuthLastError } = await import('@/api/enterpriseAuth')
    const sanitized = sanitizeEnterpriseAuthLastError(
      'login failed password=secret Bearer abc.def access_token=token-value extra detail',
      56,
    )

    expect(sanitized).not.toContain('secret')
    expect(sanitized).not.toContain('abc.def')
    expect(sanitized).not.toContain('token-value')
    expect(sanitized).toContain('***')
    expect(sanitized.length).toBeLessThanOrEqual(56)
  })
})

describe('enterprise auth API', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    requestMock.get.mockResolvedValue([])
    requestMock.post.mockResolvedValue({})
    requestMock.put.mockResolvedValue({})
    requestMock.delete.mockResolvedValue({})
  })

  it('calls status and account CRUD/test endpoints directly', async () => {
    const { enterpriseAuthApi } = await import('@/api/enterpriseAuth')
    const createPayload = {
      provider: 'apaas' as const,
      base_url: 'https://apaas.example.com',
      tenant_ref: 'tenant-a',
      tenant_name: '租户 A',
      account: 'admin',
      password: 'secret',
      enabled: true,
    }
    const updatePayload = { account: 'admin', enabled: true }

    await enterpriseAuthApi.getStatus()
    await enterpriseAuthApi.listAccounts()
    await enterpriseAuthApi.createAccount(createPayload)
    await enterpriseAuthApi.updateAccount(7, updatePayload)
    await enterpriseAuthApi.testAccount(7)
    await enterpriseAuthApi.deleteAccount(7)

    expect(requestMock.get).toHaveBeenNthCalledWith(1, '/enterprise-auth/status')
    expect(requestMock.get).toHaveBeenNthCalledWith(2, '/enterprise-auth/accounts')
    expect(requestMock.post).toHaveBeenNthCalledWith(1, '/enterprise-auth/accounts', createPayload)
    expect(requestMock.put).toHaveBeenCalledWith('/enterprise-auth/accounts/7', updatePayload)
    expect(requestMock.post).toHaveBeenNthCalledWith(2, '/enterprise-auth/accounts/7/test')
    expect(requestMock.delete).toHaveBeenCalledWith('/enterprise-auth/accounts/7')
  })

  it('preserves binding pair order and lets request errors pass through', async () => {
    const { enterpriseAuthApi } = await import('@/api/enterpriseAuth')
    const createPayload = {
      left_account_id: 12,
      right_account_id: 4,
      priority: 20,
      enabled: true,
    }
    const updatePayload = { ...createPayload, priority: 10, enabled: false }

    await enterpriseAuthApi.listBindings()
    await enterpriseAuthApi.createBinding(createPayload)
    await enterpriseAuthApi.updateBinding(5, updatePayload)
    await enterpriseAuthApi.deleteBinding(5)

    expect(requestMock.get).toHaveBeenCalledWith('/enterprise-auth/bindings')
    expect(requestMock.post).toHaveBeenCalledWith('/enterprise-auth/bindings', createPayload)
    expect(requestMock.put).toHaveBeenCalledWith('/enterprise-auth/bindings/5', updatePayload)
    expect(requestMock.delete).toHaveBeenCalledWith('/enterprise-auth/bindings/5')

    const backendError = {
      response: { data: { message: '需要平台管理员权限' } },
    }
    requestMock.get.mockRejectedValueOnce(backendError)
    await expect(enterpriseAuthApi.listAccounts()).rejects.toBe(backendError)
  })
})
