import { describe, expect, it } from 'vitest'
import src from './CustomPagePreviewPanel.vue?raw'

describe('CustomPagePreviewPanel authentication URL', () => {
  it('uses a reactive store token only to invalidate the committed-token URL after session reset', () => {
    expect(src).toContain('getCommittedAuthToken')
    expect(src).not.toContain('getCommittedAuthTokenOrThrow')
    expect(src).toContain('useUserStore')
    expect(src).toMatch(/const hostUrl = computed\(\(\) => \{[\s\S]*const sessionToken = userStore\.token[\s\S]*const tok = getCommittedAuthToken\(\)[\s\S]*if \(!sessionToken \|\| !tok\) return ''/)
    expect(src).toMatch(/const previewSrc = computed\(\(\) => \{[\s\S]*if \(!hostUrl\.value\) return ''/)
    expect(src).not.toContain('encodeURIComponent(sessionToken)')
    expect(src).toMatch(/<div v-if="previewSrc" class="cpp-frame-wrap">/)
  })
})
