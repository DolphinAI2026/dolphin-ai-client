import request from '@/utils/request'

export type AuditLogItem = Record<string, any> & { id: number; occurred_at: string }
export type AuditLogPage = { items: AuditLogItem[]; next_cursor?: string | null; total: number }

export const auditLogsApi = {
  list(params: Record<string, any>) {
    return request.get<any, AuditLogPage>('/audit-logs', { params })
  },
  listApplication(applicationId: number, params: Record<string, any>) {
    return request.get<any, AuditLogPage>(`/applications/${applicationId}/audit-logs`, { params })
  },
  get(id: number) { return request.get<any, AuditLogItem>(`/audit-logs/${id}`) },
  getApplication(applicationId: number, id: number) { return request.get<any, AuditLogItem>(`/applications/${applicationId}/audit-logs/${id}`) },
}
