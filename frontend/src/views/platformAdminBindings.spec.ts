import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const source = readFileSync(
  resolve(process.cwd(), '../admin-spa/src/views/PlatformTenants.vue'),
  'utf8',
)

describe('aPaaS platform admin bindings', () => {
  it('supports account create, update, delete and login', () => {
    expect(source).toContain("apiPost<AdminRow>('/mcp-platform/apaas-admins'")
    expect(source).toContain('apiPut(`/mcp-platform/apaas-admins/${editingAdminId.value}`')
    expect(source).toContain('apiDel(`/mcp-platform/apaas-admins/${row.id}`')
    expect(source).toContain('apiPost(`/mcp-platform/apaas-admins/${row.id}/login`)')
  })

  it('labels the platform account login action as a test login', () => {
    expect(source).toContain('@click="loginAdmin(row)">测试登录</el-button>')
  })

  it('does not allow tenant refresh without an admin account', () => {
    expect(source).toContain(':disabled="!selectedAdminId"')
  })

  it('supports one default environment binding per tenant', () => {
    expect(source).toContain('环境绑定')
    expect(source).toContain('绑定环境')
    expect(source).toContain('aPaaS 地址')
    expect(source).toContain('aPaaS 租户 ID')
    expect(source).toContain(
      'apiPut(`/mcp-platform/apaas-tenants/${bindingTarget.value.localTenantId}/binding`',
    )
  })
})
