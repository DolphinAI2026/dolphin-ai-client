import { beforeEach, describe, expect, it, vi } from 'vitest'
import panelSource from './EnterpriseAuthBindingsPanel.vue?raw'
import tenantsSource from '../../views/PlatformTenants.vue?raw'

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

describe('enterprise auth API', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('canonicalizes account pairs and rejects same-provider bindings', async () => {
    const {
      canonicalizeEnterpriseAuthPair,
      isEnterpriseAuthBindingPairAllowed,
    } = await import('@/api/enterpriseAuth')

    expect(canonicalizeEnterpriseAuthPair(9, 3)).toEqual([3, 9])
    expect(canonicalizeEnterpriseAuthPair(3, 9)).toEqual([3, 9])
    expect(isEnterpriseAuthBindingPairAllowed(
      { id: 3, provider: 'apaas' },
      { id: 9, provider: 'control_plane' },
    )).toBe(true)
    expect(isEnterpriseAuthBindingPairAllowed(
      { id: 3, provider: 'apaas' },
      { id: 9, provider: 'apaas' },
    )).toBe(false)
  })

  it('calls status and account CRUD/test endpoints with typed payloads', async () => {
    const { enterpriseAuthApi } = await import('@/api/enterpriseAuth')
    requestMock.get.mockResolvedValue([])
    requestMock.post.mockResolvedValue({})
    requestMock.put.mockResolvedValue({})
    requestMock.delete.mockResolvedValue({})

    await enterpriseAuthApi.getStatus()
    await enterpriseAuthApi.listAccounts()
    await enterpriseAuthApi.createAccount({
      provider: 'apaas',
      base_url: 'https://apaas.example.com',
      tenant_ref: 'tenant-a',
      tenant_name: '租户 A',
      account: 'admin',
      password: 'secret',
      enabled: true,
    })
    await enterpriseAuthApi.updateAccount(7, {
      provider: 'apaas',
      base_url: 'https://apaas.example.com',
      tenant_ref: 'tenant-a',
      tenant_name: '租户 A',
      account: 'admin',
      enabled: true,
    })
    await enterpriseAuthApi.testAccount(7)
    await enterpriseAuthApi.deleteAccount(7)

    expect(requestMock.get).toHaveBeenNthCalledWith(1, '/enterprise-auth/status')
    expect(requestMock.get).toHaveBeenNthCalledWith(2, '/enterprise-auth/accounts')
    expect(requestMock.post).toHaveBeenNthCalledWith(
      1,
      '/enterprise-auth/accounts',
      expect.objectContaining({ account: 'admin', password: 'secret' }),
    )
    expect(requestMock.put).toHaveBeenCalledWith(
      '/enterprise-auth/accounts/7',
      expect.not.objectContaining({ password: expect.anything() }),
    )
    expect(requestMock.post).toHaveBeenNthCalledWith(
      2,
      '/enterprise-auth/accounts/7/test',
    )
    expect(requestMock.delete).toHaveBeenCalledWith('/enterprise-auth/accounts/7')
  })

  it('omits a blank edit password and calls canonical binding CRUD endpoints', async () => {
    const {
      buildEnterpriseAuthAccountUpdatePayload,
      enterpriseAuthApi,
    } = await import('@/api/enterpriseAuth')
    requestMock.get.mockResolvedValue([])
    requestMock.post.mockResolvedValue({})
    requestMock.put.mockResolvedValue({})
    requestMock.delete.mockResolvedValue({})

    const accountPayload = buildEnterpriseAuthAccountUpdatePayload({
      provider: 'control_plane',
      base_url: 'https://cp.example.com',
      tenant_ref: 'tenant-b',
      tenant_name: '',
      account: 'operator',
      password: '   ',
      enabled: true,
    })
    expect(accountPayload).not.toHaveProperty('password')

    await enterpriseAuthApi.listBindings()
    await enterpriseAuthApi.createBinding({
      left_account_id: 12,
      right_account_id: 4,
      priority: 20,
      enabled: true,
    })
    await enterpriseAuthApi.updateBinding(5, {
      left_account_id: 12,
      right_account_id: 4,
      priority: 10,
      enabled: false,
    })
    await enterpriseAuthApi.deleteBinding(5)

    expect(requestMock.get).toHaveBeenCalledWith('/enterprise-auth/bindings')
    expect(requestMock.post).toHaveBeenCalledWith('/enterprise-auth/bindings', {
      left_account_id: 4,
      right_account_id: 12,
      priority: 20,
      enabled: true,
    })
    expect(requestMock.put).toHaveBeenCalledWith('/enterprise-auth/bindings/5', {
      left_account_id: 4,
      right_account_id: 12,
      priority: 10,
      enabled: false,
    })
    expect(requestMock.delete).toHaveBeenCalledWith('/enterprise-auth/bindings/5')
  })

  it('prefers top-level code/message and remains compatible with detail errors', async () => {
    const { enterpriseAuthApi } = await import('@/api/enterpriseAuth')

    requestMock.get.mockRejectedValueOnce({
      response: {
        data: {
          code: 'ENTERPRISE_AUTH_ADMIN_REQUIRED',
          message: '需要平台管理员权限',
          detail: { code: 'LEGACY', message: 'legacy message' },
        },
      },
    })
    await expect(enterpriseAuthApi.listAccounts()).rejects.toMatchObject({
      code: 'ENTERPRISE_AUTH_ADMIN_REQUIRED',
      message: '需要平台管理员权限',
    })

    requestMock.get.mockRejectedValueOnce({
      response: {
        data: {
          detail: {
            code: 'ENTERPRISE_AUTH_ACCOUNT_INVALID',
            message: '绑定两侧必须来自不同认证源',
          },
        },
      },
    })
    await expect(enterpriseAuthApi.listBindings()).rejects.toMatchObject({
      code: 'ENTERPRISE_AUTH_ACCOUNT_INVALID',
      message: '绑定两侧必须来自不同认证源',
    })
  })
})

describe('EnterpriseAuthBindingsPanel source contracts', () => {
  it('never renders password or token values and keeps edit password optional', () => {
    expect(panelSource).not.toMatch(/{{[^}]*(password|access_token|refresh_token|token)[^}]*}}/i)
    expect(panelSource).not.toContain('show-password')
    expect(panelSource).toContain('type="password"')
    expect(panelSource).toContain('autocomplete="new-password"')
    expect(panelSource).toContain('留空则保持原密码')
    expect(panelSource).toContain(':required="!accountEditingId"')
    expect(panelSource).toContain('buildEnterpriseAuthAccountUpdatePayload')
  })

  it('enforces different providers in the binding editor', () => {
    expect(panelSource).toContain('isEnterpriseAuthBindingPairAllowed')
    expect(panelSource).toContain('绑定两侧必须来自不同认证源')
    expect(panelSource).toContain('disabledBindingAccountIds')
  })

  it('integrates a refreshable auth panel as a top-level tenant page tab', () => {
    expect(tenantsSource).toContain('v-model="activeTab"')
    expect(tenantsSource).toContain('name="tenants"')
    expect(tenantsSource).toContain('name="enterprise-auth"')
    expect(tenantsSource).toContain('EnterpriseAuthBindingsPanel')
    expect(tenantsSource).toContain('refreshActiveTab')
    expect(tenantsSource).toContain('enterpriseAuthPanelRef')
  })
})
