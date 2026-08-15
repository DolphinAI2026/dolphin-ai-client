import { describe, expect, it } from 'vitest'
import componentSource from './AuditLogExplorer.vue?raw'
import tenantPageSource from '@/views/TenantAuditLogsPage.vue?raw'
import appPageSource from '@/views/ApplicationAuditLogsPage.vue?raw'
import routerSource from '@/router/index.ts?raw'
import apiSource from '@/api/auditLogs.ts?raw'
import appsSource from '@/views/Apps.vue?raw'
import workbenchShellSource from '@/components/WorkbenchShell.vue?raw'


describe('standard management audit log entries', () => {
  it('reuses one list and detail component for tenant and application entries', () => {
    expect(tenantPageSource).toContain('<AuditLogExplorer')
    expect(appPageSource).toContain('<AuditLogExplorer')
    expect(appPageSource).toContain(':application-id="applicationId"')
  })

  it('registers tenant-admin and application-scoped routes', () => {
    expect(routerSource).toContain("path: '/audit-logs'")
    expect(routerSource).toContain('requiresTenantAdmin: true')
    expect(routerSource).toContain("path: '/applications/:id/audit-logs'")
    expect(appsSource).toContain('openAuditLogs(app)')
    expect(appsSource.match(/v-if="canViewAuditLogs\(app\)"/g)).toHaveLength(2)
    expect(appsSource).toContain('Boolean(app.permissions?.can_manage_members)')
  })

  it('supports frozen filters, cursor pagination, and a read-only detail drawer', () => {
    expect(apiSource).toContain("'/audit-logs'")
    expect(apiSource).toContain('`/applications/${applicationId}/audit-logs`')
    expect(componentSource).toContain('application_id: props.applicationId')
    expect(componentSource).toContain('occurred_from')
    expect(componentSource).toContain('actor_id')
    expect(componentSource).toContain('event_type')
    expect(componentSource).toContain('result')
    expect(componentSource).toContain('next_cursor')
    expect(componentSource).toContain('cursorHistory')
    expect(componentSource).toContain('上一页')
    expect(componentSource).toContain('<el-drawer')
    expect(componentSource).toContain('detailError')
    expect(componentSource).toContain('读取审计详情失败')
    expect(componentSource).toContain('formatAuditTime')
    expect(componentSource).toContain('eventTypeLabel')
    expect(componentSource).toContain('resultLabel')
    expect(componentSource).toContain('当前条件下暂无审计日志')
    expect(componentSource).toContain('重试')
    expect(componentSource).toContain('auditLogsApi.getApplication')
    expect(componentSource).not.toContain('导出')
    expect(componentSource).not.toContain('删除')
    expect(componentSource).not.toContain('编辑')
  })

  it('keeps the audit explorer usable on narrow screens', () => {
    expect(workbenchShellSource).toContain(':collapsed="narrowViewport"')
    expect(workbenchShellSource).toContain('matchMedia')
    expect(workbenchShellSource).toContain(':deep(.rail.rail-collapsed)')
    expect(componentSource).toContain('class="mobile-list"')
    expect(componentSource).toContain('class="mobile-item"')
    expect(componentSource).toContain('@media (max-width: 640px)')
    expect(componentSource).toContain('.desktop-table')
  })
})
