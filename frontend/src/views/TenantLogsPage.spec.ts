import { describe, expect, it } from 'vitest'
import routerSource from '@/router/index.ts?raw'
import pageSource from './TenantLogsPage.vue?raw'

describe('Tenant low-code log analysis entry', () => {
  it('registers a tenant log analysis route', () => {
    expect(routerSource).toContain("path: '/tenant-logs'")
    expect(routerSource).toContain("name: 'TenantLogs'")
  })

  it('renders the tenant log analysis page against the tenant logs endpoint', () => {
    expect(pageSource).toContain('租户日志分析')
    expect(pageSource).toContain("request.get<any, any>('/tenant-logs'")
    expect(pageSource).toContain('低代码变更洞察')
  })

  it('renders a risk insight sidebar and action recommendations', () => {
    expect(pageSource).toContain('insight-sidebar')
    expect(pageSource).toContain('recommendation-panel')
    expect(pageSource).toContain('风险看板')
    expect(pageSource).toContain('变更时间线')
    expect(pageSource).toContain('处置建议')
    expect(pageSource).toContain('recommendations')
    expect(pageSource).toContain('recommendation-list')
    expect(pageSource).not.toContain('class="preset-report"')
    expect(pageSource).not.toContain('v-for="question in assistantQuestions"')
    expect(pageSource).not.toContain('selectedQuestion')
  })

  it('falls back to current log items when backend analysis has no timeline', () => {
    expect(pageSource).toContain('items.value.slice(0, 12).map((item)')
    expect(pageSource).toContain("time: item.timestamp")
  })

  it('renders the log detail as an el-table with pagination and a row drawer', () => {
    expect(pageSource).toContain('<el-table')
    expect(pageSource).toContain('el-table-column')
    expect(pageSource).toContain('el-pagination')
    expect(pageSource).toContain('@row-click="openDetail"')
    expect(pageSource).toContain('<el-drawer')
    expect(pageSource).toContain('page_size')
  })

  it('consolidates the analysis metrics into a single KPI strip', () => {
    expect(pageSource).toContain('kpi-strip')
    expect(pageSource).toContain('日志总数')
    expect(pageSource).not.toContain('font-size: 26px;')
  })

  it('keeps a single-screen layout with the table scrolling internally', () => {
    expect(pageSource).toContain('tenant-log-table-scroll')
    expect(pageSource).toContain('height="100%"')
    expect(pageSource).toContain('.tenant-log-page {\n  height: 100%;')
    expect(pageSource).toContain('overflow: hidden;')
    expect(pageSource).not.toContain('flex: 0 0 min(250px, 30vh);')
  })
})
