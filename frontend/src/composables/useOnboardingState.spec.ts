import { describe, it, expect } from 'vitest'
import { fetchOnboardingState } from './useOnboardingState'

describe('fetchOnboardingState', () => {
  it('configured=false when both empty', async () => {
    const s = await fetchOnboardingState(
      async () => [],
      async () => [],
    )
    expect(s).toEqual({ hasEnv: false, hasLlm: false, configured: false })
  })

  it('configured=true only when both present', async () => {
    const s = await fetchOnboardingState(
      async () => [{ id: 1 } as any],
      async () => [{ id: 1 } as any],
    )
    expect(s.configured).toBe(true)
  })

  it('configured=false when only one present', async () => {
    const s = await fetchOnboardingState(
      async () => [{ id: 1 } as any],
      async () => [],
    )
    expect(s.configured).toBe(false)
  })

  it('treats fetch errors as not-configured (空库新机首启 list 可能 401/空)', async () => {
    const s = await fetchOnboardingState(
      async () => { throw new Error('x') },
      async () => [],
    )
    expect(s.configured).toBe(false)
  })
})
