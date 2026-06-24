import { describe, expect, it } from 'vitest'
import src from './ConfigWorkspacePanel.vue?raw'

describe('ConfigWorkspacePanel 内嵌编辑器', () => {
  it('用 ApaasMenuSidebar + InAppBrowser 内嵌, 不再引用自渲染面板', () => {
    expect(src).toContain('ApaasMenuSidebar')
    expect(src).toContain('InAppBrowser')
    expect(src).toContain('getEditorUrl')
    for (const c of ['FormDesignerPanel','DataSchemaEditor','ProcessDesignerPanel','FormPermPanel','OpenLowcodeBackendButton']) {
      expect(src).not.toContain(c)
    }
  })
})
