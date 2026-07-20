import { describe, expect, it } from 'vitest'
import src from './PlatformAdminEmbed.vue?raw'

describe('PlatformAdminEmbed authentication URL', () => {
  it('uses the non-throwing committed token getter and returns an empty iframe URL without a session', () => {
    expect(src).toContain('getCommittedAuthToken')
    expect(src).not.toContain('getCommittedAuthTokenOrThrow')
    expect(src).toMatch(/const iframeSrc = computed\(\(\) => \{[\s\S]*if \(!token\) return ''/)
  })
})
