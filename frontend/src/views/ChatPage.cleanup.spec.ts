import { describe, expect, it } from 'vitest'
import src from './ChatPage.vue?raw'

describe('ChatPage 收敛: 删自渲染面板与多余 tab', () => {
  const gone = [
    'FormDesignerPanel', 'ListDesignerPanel', 'ProcessDesignerPanel',
    'DataSchemaEditor', 'FormPermPanel', 'BusinessEventPanel',
    'DataModelDetailPanel', 'DictEditorPanel', 'RoleManagePanel',
    'AppDatasourcePanel', 'SpecDesignPanel', 'LogsPanel', 'AppHealthPanel',
    'OpenLowcodeBackendButton',
  ]
  it('不再引用任何自渲染配置面板/深链按钮', () => {
    for (const c of gone) expect(src).not.toContain(c)
  })
  it('保留: 菜单目录 + 内嵌编辑器 + 助手 + 自开发', () => {
    expect(src).toContain('ApaasMenuSidebar')
    expect(src).toContain('InAppBrowser')
    expect(src).toContain('AppAssistantPanel')
    expect(src).toContain('AppDevWorkspacePanel')
    expect(src).toContain('CustomPagePreviewPanel')
  })
  it('助手不再依赖已删的 spec/designer-sub 条件', () => {
    expect(src).not.toContain(':designer-sub')
  })
})
