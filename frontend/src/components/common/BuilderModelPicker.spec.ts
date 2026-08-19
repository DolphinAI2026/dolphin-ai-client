import { describe, expect, it } from 'vitest'
import pickerSource from './BuilderModelPicker.vue?raw'
import aiChatPageSource from '@/views/AIChatPage.vue?raw'
import assistantPanelSource from '@/components/v2/AppAssistantPanel.vue?raw'

describe('Builder model picker usage', () => {
  it('does not use native select in AIChatPage composer', () => {
    expect(aiChatPageSource).not.toContain('class="model-select-inline"')
    expect(aiChatPageSource).toContain('<BuilderModelPicker')
  })

  it('renders default and configured model options in the shared picker', () => {
    expect(pickerSource).toContain('默认模型')
    expect(pickerSource).toContain('function optionLabel(option: BuilderModelOption): string')
    expect(pickerSource).toContain('option.is_default && !props.showDefaultConfigName')
    expect(pickerSource).toContain("option.is_default ? '当前默认配置'")
    expect(pickerSource).toContain('v-for="option in options"')
    expect(pickerSource).toContain('role="listbox"')
    expect(pickerSource).toContain('role="option"')
  })

  it('keeps assistant composer overflow visible so the menu is not clipped', () => {
    expect(assistantPanelSource).toContain('.aa-input-area :deep(.ucc-box)')
    expect(assistantPanelSource).toContain('overflow: visible')
    expect(assistantPanelSource).toContain('<BuilderModelPicker')
  })
})
