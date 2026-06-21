import { describe, expect, it } from 'vitest'
import {
  getCodingMainPaneStyle,
  shouldShowWorkspacePane,
  isCodingWelcome,
  shouldShowCodingComposer,
} from './codingLayout'

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

describe('coding welcome (new-session, conversation-first)', () => {
  it('is the welcome state for a brand-new non-embedded session (no workspace, no messages)', () => {
    expect(isCodingWelcome({ embedded: false, codeFirst: false, streaming: false, messageCount: 0 })).toBe(true)
  })

  it('is NOT the welcome state once a workspace is open (codeFirst)', () => {
    expect(isCodingWelcome({ embedded: false, codeFirst: true, streaming: false, messageCount: 0 })).toBe(false)
  })

  it('is NOT the welcome state once messages exist or while streaming', () => {
    expect(isCodingWelcome({ embedded: false, codeFirst: false, streaming: false, messageCount: 3 })).toBe(false)
    expect(isCodingWelcome({ embedded: false, codeFirst: false, streaming: true, messageCount: 0 })).toBe(false)
  })

  it('is NOT the welcome state in embedded (app-context) mode', () => {
    expect(isCodingWelcome({ embedded: true, codeFirst: false, streaming: false, messageCount: 0 })).toBe(false)
  })
})

describe('coding composer visibility', () => {
  it('always shows the composer in non-embedded Code mode (incl. a brand-new session — fixes the no-input bug)', () => {
    expect(shouldShowCodingComposer({ embedded: false, codeFirst: false, streaming: false, messageCount: 0 })).toBe(true)
    expect(shouldShowCodingComposer({ embedded: false, codeFirst: true, streaming: false, messageCount: 0 })).toBe(true)
    expect(shouldShowCodingComposer({ embedded: false, codeFirst: false, streaming: false, messageCount: 5 })).toBe(true)
  })

  it('in embedded mode, shows the composer only when there are messages or a workspace (preserves prior behavior)', () => {
    expect(shouldShowCodingComposer({ embedded: true, codeFirst: false, streaming: false, messageCount: 0 })).toBe(false)
    expect(shouldShowCodingComposer({ embedded: true, codeFirst: false, streaming: false, messageCount: 2 })).toBe(true)
    expect(shouldShowCodingComposer({ embedded: true, codeFirst: true, streaming: false, messageCount: 0 })).toBe(true)
  })
})
