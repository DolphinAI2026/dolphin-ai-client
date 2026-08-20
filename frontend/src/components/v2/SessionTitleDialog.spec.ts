import { describe, expect, it } from 'vitest'
import dialogSource from './SessionTitleDialog.vue?raw'
import railSidebarSource from './RailSidebar.vue?raw'

describe('SessionTitleDialog', () => {
  it('keeps AI generation inside the title dialog and requires an explicit save', () => {
    expect(dialogSource).toContain('修改会话标题')
    expect(dialogSource).toContain('v-if="canGenerate"')
    expect(dialogSource).toContain('AI 生成')
    expect(dialogSource).toContain("emit('generate')")
    expect(dialogSource).toContain("emit('save')")
    expect(railSidebarSource).toContain("sessionTitleDraft.value = result.title")
    expect(railSidebarSource).toContain("ElMessage.success('标题已生成，保存后生效')")
    expect(railSidebarSource).toContain('false,')
  })

  it('hides AI generation when no coding model is available', () => {
    expect(railSidebarSource).toContain("llmConfigApi.listOptions('coding')")
    expect(railSidebarSource).toContain('codeTitleModelAvailable.value = false')
    expect(railSidebarSource).toContain(":can-generate=\"sessionTitleTarget?.kind === 'code' && codeTitleModelAvailable\"")
  })
})
