import request from '@/utils/request'

export interface McpServer {
  id: string
  name: string
  code: string
  status: 'connected' | 'error' | 'disabled'
  transport: 'sse' | 'http' | 'stdio'
  endpoint: string
  tools: number
  last_used?: string | null
  usage: number
  version: string
  tags: string[]
  desc: string
  official: boolean
  error?: string | null
}

export interface McpServerListResponse {
  servers: McpServer[]
  total: number
  connected: number
  errors: number
}

export const mcpApi = {
  listServers(): Promise<McpServerListResponse> {
    return request({ url: '/mcp-hub/servers', method: 'get' }) as unknown as Promise<McpServerListResponse>
  },
}
