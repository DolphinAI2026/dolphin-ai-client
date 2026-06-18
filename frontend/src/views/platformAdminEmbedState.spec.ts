import { describe, expect, it } from 'vitest'
import { buildPlatformAdminIframeSrc, resolvePlatformAdminPath } from './platformAdminEmbedState'

describe('platform admin embed state', () => {
  it('opens the platform overview by default instead of the MCP-only page', () => {
    expect(resolvePlatformAdminPath(undefined)).toBe('/status')
    expect(resolvePlatformAdminPath('')).toBe('/status')
  })

  it('keeps explicit platform admin child routes', () => {
    expect(resolvePlatformAdminPath('mcp')).toBe('/mcp')
    expect(resolvePlatformAdminPath('llm-configs')).toBe('/llm-configs')
    expect(resolvePlatformAdminPath(['tenants'])).toBe('/tenants')
    expect(resolvePlatformAdminPath(['users', 'detail'])).toBe('/users/detail')
  })

  it('builds the embedded admin-spa URL under the ai-builder base path', () => {
    expect(buildPlatformAdminIframeSrc({
      origin: 'http://localhost:5173',
      baseUrl: '/ai-builder/',
      adminPath: '/status',
      token: 'token-1',
    })).toBe('http://localhost:5173/ai-builder/admin/status?embed=1&handoff_token=token-1')
  })
})
