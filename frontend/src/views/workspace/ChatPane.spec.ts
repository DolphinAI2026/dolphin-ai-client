import { describe, expect, it } from 'vitest'
import src from './ChatPane.vue?raw'

describe('ChatPane', () => {
  it('reuses the existing chat engine + components (does not reimplement SSE)', () => {
    expect(src).toContain('useAiChatSession')
    expect(src).toContain('AgentConversation')
    expect(src).toContain('UnifiedChatComposer')
    expect(src).toContain('BuilderModelPicker')
  })
  it('takes appId from prop (not hardcoded null) to lock the app', () => {
    expect(src).toContain('appId')
    expect(src).not.toMatch(/const appId = ref<number \| null>\(null\)/)   // 不再写死 null
  })
  it('resets session when app binding changes', () => {
    expect(src).toMatch(/watch[\s\S]*newSession/)
  })
  it('surfaces artifacts to the shell via open-artifact (panel lives in PanelHost)', () => {
    expect(src).toContain("emit('open-artifact'")
    expect(src).toContain('@open-artifact')
  })
  it('passes a workspace viewContext into useAiChatSession when bound', () => {
    expect(src).toContain('workspaceId')
    expect(src).toContain('viewContext')
  })
  it('drops shell-owned header buttons (history / new / artifact list)', () => {
    expect(src).not.toContain('openDrawer')
    expect(src).not.toContain('el-drawer')
  })
})
