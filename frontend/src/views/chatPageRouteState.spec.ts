import { describe, expect, it } from 'vitest'
import { resolveInitialAppId, shouldUseRequirementsSpecMode } from './chatPageRouteState'

describe('chat page route state', () => {
  it('uses app_id from the initial route before mounted hooks run', () => {
    expect(resolveInitialAppId('10')).toBe(10)
    expect(shouldUseRequirementsSpecMode('requirements', 10)).toBe(false)
  })

  it('keeps requirements spec mode for a new chat without app_id', () => {
    expect(resolveInitialAppId(undefined)).toBeNull()
    expect(shouldUseRequirementsSpecMode('requirements', null)).toBe(true)
  })

  it('ignores invalid app_id values', () => {
    expect(resolveInitialAppId('0')).toBeNull()
    expect(resolveInitialAppId('abc')).toBeNull()
    expect(resolveInitialAppId(['12', '13'])).toBe(12)
  })
})
