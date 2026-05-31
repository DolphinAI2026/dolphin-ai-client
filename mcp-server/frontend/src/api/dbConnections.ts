import request from '@/utils/request'

export type DbType = 'MYSQL' | 'PostgreSQL' | 'SQLServer' | 'ORACLE' | 'DAMENG' | 'KingBase'

export interface DbConnection {
  id: number
  name: string
  db_type: DbType
  host: string
  port: number
  database: string
  username: string
  description?: string
  status: 'active' | 'disconnected'
  last_tested_at?: string
  table_count: number
  created_at: string
}

export interface DbConnectionCreate {
  name: string
  db_type: DbType
  host: string
  port: number
  database: string
  username: string
  password: string
  description?: string
}

export interface DbConnectionUpdate {
  name?: string
  db_type?: DbType
  host?: string
  port?: number
  database?: string
  username?: string
  password?: string // 省略则保留原密码
  description?: string
}

export interface TestResp {
  ok: boolean
  table_count: number
  error?: string
}

export interface DbTableSummary {
  name: string
  fields: number
}

export interface DbTablesResp {
  tables: DbTableSummary[]
  classifications: Record<string, any>
}

export const dbConnectionApi = {
  list: () => request.get<any, DbConnection[]>('/db-connections'),
  get: (id: number) => request.get<any, DbConnection>(`/db-connections/${id}`),
  create: (data: DbConnectionCreate) => request.post<any, DbConnection>('/db-connections', data),
  update: (id: number, data: DbConnectionUpdate) => request.put<any, DbConnection>(`/db-connections/${id}`, data),
  delete: (id: number) => request.delete(`/db-connections/${id}`),
  test: (id: number) => request.post<any, TestResp>(`/db-connections/${id}/test`),
  tables: (id: number) => request.get<any, DbTablesResp>(`/db-connections/${id}/tables`),
}
