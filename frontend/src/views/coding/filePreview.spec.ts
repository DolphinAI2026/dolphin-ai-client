import { describe, expect, it } from 'vitest'
import { getWorkspaceFilePreviewKind } from './filePreview'

describe('getWorkspaceFilePreviewKind', () => {
  it('previews browser-displayable image files', () => {
    expect(getWorkspaceFilePreviewKind('img/factory-twin-bg.c4656550.jpeg')).toBe('image')
    expect(getWorkspaceFilePreviewKind('assets/diagram.svg')).toBe('image')
  })

  it('keeps archive files download-only', () => {
    expect(getWorkspaceFilePreviewKind('dist/form-page.zip')).toBe('download')
  })

  it('keeps source files in text mode', () => {
    expect(getWorkspaceFilePreviewKind('src/App.vue')).toBe('text')
  })
})
