import { describe, expect, it } from 'vitest'
import routerSource from '@/router/index.ts?raw'
import railSource from '@/components/v2/RailSidebar.vue?raw'
import pageSource from './TenantLogsPage.vue?raw'

describe('Tenant low-code log analysis entry', () => {
  it('registers a tenant log analysis route', () => {
    expect(routerSource).toContain("path: '/tenant-logs'")
    expect(routerSource).toContain("name: 'TenantLogs'")
  })

  it('shows tenant log analysis in the left navigation', () => {
    expect(railSource).toContain("key: 'tenantLogs'")
    expect(railSource).toContain('租户日志分析')
    expect(railSource).toContain("path: '/tenant-logs'")
  })

  it('renders the tenant log analysis page against the tenant logs endpoint', () => {
    expect(pageSource).toContain('租户日志分析')
    expect(pageSource).toContain("request.get<any, any>('/tenant-logs'")
    expect(pageSource).toContain('低代码变更洞察')
  })
})
