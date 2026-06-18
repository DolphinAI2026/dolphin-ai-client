import { describe, expect, it } from 'vitest'
import src from './ChatPane.vue?raw'

describe('ChatPane', () => {
  it('reuses the existing chat engine + components (does not reimplement SSE)', () => {
    expect(src).toContain('useAiChatSession')
    expect(src).toContain('AgentConversation')
    expect(src).toContain('UnifiedChatComposer')
    expect(src).toContain('BuilderModelPicker')
  })
  it('runs as a general (unbound) chat — appId is null', () => {
    expect(src).toMatch(/appId:\s*ref\(null\)|appId:\s*computed/)
  })
  it('surfaces artifacts to the shell via open-artifact (panel lives in PanelHost)', () => {
    expect(src).toContain("emit('open-artifact'")
    expect(src).toContain('@open-artifact')
  })
})
