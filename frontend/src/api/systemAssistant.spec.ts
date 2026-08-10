import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/utils/request', () => ({
  default: { get: vi.fn() },
}))

import request from '@/utils/request'
import { systemAssistantApi } from './systemAssistant'

describe('systemAssistantApi', () => {
  beforeEach(() => vi.clearAllMocks())

  it('reads the tenant-scoped bootstrap snapshot', async () => {
    const response = {
      baseline_snapshot: { version: 'p0', readonly: true, tenant_id: 1, nodes: [] },
      recommended_action: { id: 'inspect', status: 'partial', title: '盘点基线', reason: '来源不完整' },
      available_actions: ['inspect'],
      source_status: {},
    }
    vi.mocked(request.get).mockResolvedValue(response as never)

    await expect(systemAssistantApi.getBootstrap()).resolves.toBe(response)
    expect(request.get).toHaveBeenCalledWith('/system-assistant/bootstrap')
  })

  it('loads the system-assistant coding model catalog', async () => {
    const response = [{
      id: 7,
      config_name: '企业 Coding 模型',
      provider: 'dolphin',
      model: 'gpt-5.5',
      purpose: 'coding',
      is_default: true,
    }]
    vi.mocked(request.get).mockResolvedValue(response as never)

    await expect(systemAssistantApi.listModels()).resolves.toBe(response)
    expect(request.get).toHaveBeenCalledWith('/system-assistant/models')
  })
})
