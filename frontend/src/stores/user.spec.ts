import { describe, expect, it } from 'vitest'
import userStoreSource from './user.ts?raw'

describe('user organization switching', () => {
  it('returns to the current build base after switching organizations', () => {
    expect(userStoreSource).toContain('window.location.href = import.meta.env.BASE_URL')
    expect(userStoreSource).not.toContain("window.location.href = '/ai-builder/'")
  })

  it('clears only authentication state when the desktop user logs out', () => {
    expect(userStoreSource).not.toContain('resetOnboardingCache')
  })
})
