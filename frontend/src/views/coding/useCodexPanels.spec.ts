import { describe, it, expect } from 'vitest'
import {
  CODEX_COMMANDS,
  CODEX_PANEL_COMMANDS,
  matchPalette,
  matchPanelHotkey,
  isEditableTarget,
  type CodexCommand,
} from './useCodexPanels'

// 项目 vitest 走 node 环境(无 DOM)。匹配函数只读 key/修饰键,用普通对象代替 KeyboardEvent。
function key(k: string, mods: Partial<Record<'metaKey' | 'ctrlKey' | 'shiftKey' | 'altKey', boolean>> = {}): KeyboardEvent {
  return { key: k, metaKey: false, ctrlKey: false, shiftKey: false, altKey: false, ...mods } as KeyboardEvent
}

describe('CODEX_COMMANDS', () => {
  it('lists the 5 Codex commands in order with correct ids/hotkeys', () => {
    expect(CODEX_COMMANDS.map((c: CodexCommand) => c.id)).toEqual([
      'review', 'terminal', 'browser', 'files', 'sidechat',
    ])
    const byId = Object.fromEntries(CODEX_COMMANDS.map((c: CodexCommand) => [c.id, c]))
    expect(byId.review.hotkeyLabel).toBe('⌃⇧G')
    expect(byId.browser.hotkeyLabel).toBe('⌘T')
    expect(byId.files.hotkeyLabel).toBe('⌘P')
    expect(byId.terminal.hotkeyLabel).toBeUndefined()
    expect(byId.sidechat.panel).toBeUndefined()
  })

  it('panelCommands excludes sidechat (no panel)', () => {
    expect(CODEX_PANEL_COMMANDS.map((c: CodexCommand) => c.id)).toEqual([
      'review', 'terminal', 'browser', 'files',
    ])
  })

  it('every command has a non-empty icon name', () => {
    for (const c of CODEX_COMMANDS) expect((c.icon || '').length).toBeGreaterThan(0)
  })
})

describe('matchPalette (⌘K / Ctrl K)', () => {
  it('matches meta+k and ctrl+k, case-insensitive', () => {
    expect(matchPalette(key('k', { metaKey: true }))).toBe(true)
    expect(matchPalette(key('k', { ctrlKey: true }))).toBe(true)
    expect(matchPalette(key('K', { metaKey: true }))).toBe(true)
  })
  it('does not match bare k or with shift/alt', () => {
    expect(matchPalette(key('k'))).toBe(false)
    expect(matchPalette(key('k', { metaKey: true, shiftKey: true }))).toBe(false)
    expect(matchPalette(key('k', { metaKey: true, altKey: true }))).toBe(false)
  })
})

describe('matchPanelHotkey', () => {
  it('⌃⇧G → review', () => {
    expect(matchPanelHotkey(key('g', { ctrlKey: true, shiftKey: true }))).toBe('review')
    expect(matchPanelHotkey(key('G', { ctrlKey: true, shiftKey: true }))).toBe('review')
  })
  it('⌘P / Ctrl P → files', () => {
    expect(matchPanelHotkey(key('p', { metaKey: true }))).toBe('files')
    expect(matchPanelHotkey(key('p', { ctrlKey: true }))).toBe('files')
  })
  it('⌘T → browser', () => {
    expect(matchPanelHotkey(key('t', { metaKey: true }))).toBe('browser')
  })
  it('null for unrelated / modified keys', () => {
    expect(matchPanelHotkey(key('p'))).toBeNull()
    expect(matchPanelHotkey(key('a', { metaKey: true }))).toBeNull()
    expect(matchPanelHotkey(key('p', { metaKey: true, shiftKey: true }))).toBeNull()
  })
})

describe('isEditableTarget', () => {
  it('true for textarea/input/contenteditable', () => {
    expect(isEditableTarget({ tagName: 'TEXTAREA' } as unknown as EventTarget)).toBe(true)
    expect(isEditableTarget({ tagName: 'input' } as unknown as EventTarget)).toBe(true)
    expect(isEditableTarget({ isContentEditable: true } as unknown as EventTarget)).toBe(true)
  })
  it('false for div / null', () => {
    expect(isEditableTarget({ tagName: 'DIV' } as unknown as EventTarget)).toBe(false)
    expect(isEditableTarget(null)).toBe(false)
  })
})
