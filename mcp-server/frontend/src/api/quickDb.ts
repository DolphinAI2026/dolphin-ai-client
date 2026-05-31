// frontend/src/api/quickDb.ts
// 「DB 问数」wizard 的 API 客户端。和 platformEnv.ts 同样的 request 模式。
//
// 2026-05-19 收敛：删掉自实现 orchestrator 的 start + streamUrl，Step 4
// 现在调一次 build-spec 拿 markdown，前端把它包成 File 走 ChatPage 主线。
import request from '@/utils/request'

// 大小写敏感 — 跟 aPaaS UI 真实 dropdown 对齐
export type DbType = 'MYSQL' | 'PostgreSQL' | 'SQLServer' | 'ORACLE' | 'DAMENG' | 'KingBase'

export interface DbConnReq {
  type: DbType
  host: string
  port: number
  database: string
  username: string
  password: string
  alias?: string
}

export interface TableInfo {
  name: string
  fields: number
}

// table_classifier 给出的单表分类结果。前端 Step 2 渲染 health badge 用。
export type TableHealth = 'green' | 'yellow' | 'red' | 'skip'
export interface TableClassification {
  health: TableHealth
  badge: string
  reason: string
  flags: string[]
}

export interface TestConnResp {
  ok: boolean
  db_type: string
  db_label: string
  tables: TableInfo[]
  classifications?: Record<string, TableClassification>
  error?: string
}

export interface BuildSpecReq {
  // 二选一：新建模式传 db / 已有连接模式传 connection_id
  db?: DbConnReq
  connection_id?: number
  tables: string[]
  hint: string
  style: 'oa' | 'dashboard' | 'mobile'
  app_name?: string
}

export interface BuildSpecResp {
  ok: boolean
  spec_md: string
  app_name: string
  app_code: string
  db_label: string
  error?: string
}

export const quickDbApi = {
  testConnection: (data: DbConnReq) =>
    request.post<any, TestConnResp>('/quick-db/test-connection', data),
  buildSpec: (data: BuildSpecReq) =>
    request.post<any, BuildSpecResp>('/quick-db/build-spec', data),
}
