import { describe, expect, it } from 'vitest'
import { bindingBadge, bindingKindFromId, prefixedId, rawId } from './binding'

describe('binding', () => {
  it('maps each binding kind to a tone + label', () => {
    expect(bindingBadge({ kind: 'none' })).toEqual({ tone: 'chat', label: '对话' })
    expect(bindingBadge({ kind: 'app', appId: 7 })).toEqual({ tone: 'cowork', label: '应用' })
    expect(bindingBadge({ kind: 'workspace', workspaceId: 'ws1' })).toEqual({ tone: 'success', label: '代码' })
  })
  it('uses type-prefixed ids to avoid cross-source collision', () => {
    expect(prefixedId('app', 7)).toBe('app:7')
    expect(prefixedId('workspace', 'ws1')).toBe('workspace:ws1')
    expect(prefixedId('none', 7)).toBe('chat:7')
    expect(bindingKindFromId('app:7')).toBe('app')
    expect(bindingKindFromId('chat:12')).toBe('none')   // chat 前缀 = none 绑定
    expect(rawId('app:7')).toBe('7')
  })
  it('falls back to none for unknown id shapes', () => {
    expect(bindingKindFromId('garbage')).toBe('none')
  })
})
