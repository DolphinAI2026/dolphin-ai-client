import { describe, expect, it } from 'vitest'
import { getCodingMainPaneStyle, shouldShowWorkspacePane } from './codingLayout'

describe('coding workspace layout', () => {
  it('keeps the chat pane fixed-width before expansion', () => {
    expect(getCodingMainPaneStyle(true, false, 420)).toEqual({
      flex: '0 0 420px',
      width: '420px',
    })
  })

  it('lets the chat pane fill available space when expanded', () => {
    expect(getCodingMainPaneStyle(true, true, 420)).toBeNull()
  })

  it('hides the workspace pane while chat is expanded', () => {
    expect(shouldShowWorkspacePane('1_8ae94ab4', null, false)).toBe(true)
    expect(shouldShowWorkspacePane('1_8ae94ab4', null, true)).toBe(false)
  })
})
