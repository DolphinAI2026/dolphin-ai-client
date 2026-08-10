import { describe, expect, it } from 'vitest'
import loginSource from './Login.vue?raw'
import tenantSelectSource from './TenantSelect.vue?raw'
import userStoreSource from '@/stores/user.ts?raw'
import {
  resolveLoginTenant,
  safeLoginRedirectPath,
  tenantIdFromRedirect,
} from '@/router/loginRedirect'

const currentUuid = '11111111-1111-4111-8111-111111111111'
const targetUuid = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const tenants = [
  {
    tenant_id: 1,
    tenant_public_id: currentUuid,
    tenant_name: 'Current',
    tenant_code: 'current',
  },
  {
    tenant_id: 2,
    tenant_public_id: targetUuid,
    tenant_name: 'Target',
    tenant_code: 'target',
  },
]

describe('Login page brand layout', () => {
  it('uses the Ruijing whale identity with a right-side auth panel', () => {
    expect(loginSource).toContain('ruijing-whale-mark.svg')
    expect(loginSource).toContain('login-brand-stage')
    expect(loginSource).toContain('login-auth-panel')
    expect(loginSource).not.toContain('brand-features')
    expect(loginSource).not.toContain('需求沉淀为设计文档')
  })
})

// 桌面端和 Web 共用同一认证与租户选择协议。
describe('Login page reuses web auth on desktop', () => {
  it('does not branch to the legacy desktop account login', () => {
    expect(loginSource).not.toContain('desktopLogin')
  })

  it('keeps tenant selection for every client', () => {
    expect(loginSource).toContain('requiresSelection')
    expect(loginSource).toContain('/tenant-select')
  })

  it('honors the Control Plane server entry path after a direct login', () => {
    expect(userStoreSource).toContain('entryPath: safeLoginRedirectPath(res.entry_path)')
    expect(loginSource).toContain('result.entryPath')
  })

  it('uses the Code home when neither login entry source is valid for Code-only', () => {
    expect(loginSource).toContain("from '@/stores/productAvailability'")
    expect(loginSource).toContain('await loadProductAvailability()')
    expect(loginSource).toContain('redirectForDisabledProduct(')
    expect(loginSource).toContain('defaultProductHome(productAvailability)')
  })

  it('collects the configured captcha for every client', () => {
    expect(loginSource).toContain('captcha_code')
    expect(loginSource).toContain('captchaImage')
    expect(loginSource).toContain('refreshCaptcha')
  })
})

describe('tenant-aware login redirects', () => {
  it('auto-selects only the tenant whose public UUID matches the redirect', () => {
    expect(resolveLoginTenant(
      `/code/session?tenantId=${targetUuid}&agent=runtime-1#activity`,
      tenants,
    )).toEqual(tenants[1])
  })

  it('keeps invalid or inaccessible tenant targets on the manual selection path', () => {
    expect(resolveLoginTenant('/code/session?tenantId=2', tenants)).toBeUndefined()
    expect(resolveLoginTenant(
      '/code/session?tenantId=bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
      tenants,
    )).toBeUndefined()
  })

  it('extracts a canonical tenant UUID without trusting an external redirect', () => {
    expect(tenantIdFromRedirect(`/code/session?tenantId=${targetUuid}`)).toBe(targetUuid)
    expect(tenantIdFromRedirect('https://evil.example/code?tenantId=' + targetUuid)).toBeNull()
    expect(safeLoginRedirectPath('/\\evil.example/code')).toBe('')
  })

  it('wires the server-returned tenant list into TenantSelect auto-selection', () => {
    expect(loginSource).toContain('safeLoginRedirectPath')
    expect(tenantSelectSource).toContain('resolveLoginTenant')
    expect(tenantSelectSource).toContain('handleSelect(targetTenant)')
  })

  it('never submits tenant_public_id in TenantSelectRequest', () => {
    expect(userStoreSource).toContain(
      '{ selection_token: selectionToken, tenant_id: tenantId }',
    )
    expect(userStoreSource).not.toContain('tenant_public_id:')
  })
})
