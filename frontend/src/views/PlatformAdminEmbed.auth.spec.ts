import { describe, expect, it } from 'vitest'
import src from './PlatformAdminEmbed.vue?raw'

describe('PlatformAdminEmbed authentication URL', () => {
  it('uses a reactive store token only to invalidate the committed-token iframe URL after session reset', () => {
    expect(src).toContain('getCommittedAuthToken')
    expect(src).not.toContain('getCommittedAuthTokenOrThrow')
    expect(src).toMatch(/const iframeSrc = computed\(\(\) => \{[\s\S]*const sessionToken = userStore\.token[\s\S]*const token = getCommittedAuthToken\(\)[\s\S]*if \(!sessionToken \|\| !token\) return ''/)
    expect(src).not.toContain('token: sessionToken')
    expect(src).toMatch(/<iframe\s+v-if="iframeSrc"/)
  })
})
