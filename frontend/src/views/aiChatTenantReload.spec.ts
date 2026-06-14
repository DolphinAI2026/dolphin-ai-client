import { describe, expect, it } from 'vitest'
import {
  shouldLoadAiChatAuthenticatedResource,
  shouldReloadAiChatForTenantChange,
} from './aiChatTenantReload'

describe('shouldReloadAiChatForTenantChange', () => {
  it('does not reload sessions during logout', () => {
    expect(shouldReloadAiChatForTenantChange(null, 57, null)).toBe(false)
  })

  it('does not reload sessions during initial tenant hydration', () => {
    expect(shouldReloadAiChatForTenantChange(57, null, 'token')).toBe(false)
  })

  it('does not reload sessions when the tenant is unchanged', () => {
    expect(shouldReloadAiChatForTenantChange(57, 57, 'token')).toBe(false)
  })

  it('reloads sessions for an authenticated tenant switch', () => {
    expect(shouldReloadAiChatForTenantChange(60, 57, 'token')).toBe(true)
  })
})

describe('shouldLoadAiChatAuthenticatedResource', () => {
  it('does not load protected resources after logout clears the token', () => {
    expect(shouldLoadAiChatAuthenticatedResource(null)).toBe(false)
    expect(shouldLoadAiChatAuthenticatedResource('')).toBe(false)
  })

  it('loads protected resources when an auth token exists', () => {
    expect(shouldLoadAiChatAuthenticatedResource('token')).toBe(true)
  })
})
