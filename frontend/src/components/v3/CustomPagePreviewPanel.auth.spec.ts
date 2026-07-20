import { describe, expect, it } from 'vitest'
import src from './CustomPagePreviewPanel.vue?raw'

describe('CustomPagePreviewPanel authentication URL', () => {
  it('uses the non-throwing committed token getter and returns empty URLs without a session', () => {
    expect(src).toContain('getCommittedAuthToken')
    expect(src).not.toContain('getCommittedAuthTokenOrThrow')
    expect(src).toMatch(/const hostUrl = computed\(\(\) => \{[\s\S]*if \(!tok\) return ''/)
    expect(src).toMatch(/const previewSrc = computed\(\(\) => \{[\s\S]*if \(!hostUrl\.value\) return ''/)
  })
})
