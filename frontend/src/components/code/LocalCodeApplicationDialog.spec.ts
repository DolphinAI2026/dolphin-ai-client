import { describe, expect, it } from 'vitest'
import dialogSource from './LocalCodeApplicationDialog.vue?raw'
import {
  createLocalApplicationCode,
  joinLocalProjectPath,
  validateLocalApplicationCode,
} from './localApplicationForm'

describe('LocalCodeApplicationDialog', () => {
  it('generates one editable code and joins the selected parent directory', () => {
    expect(createLocalApplicationCode('Sales Assistant', 'abc123')).toBe('sales-assistant-abc123')
    expect(createLocalApplicationCode('销售助手', 'abc123')).toBe('code-app-abc123')
    expect(joinLocalProjectPath('C:\\Users\\dev\\Dolphin', 'sales-app'))
      .toBe('C:\\Users\\dev\\Dolphin\\sales-app')
    expect(joinLocalProjectPath('/home/dev/projects/', 'sales-app'))
      .toBe('/home/dev/projects/sales-app')
    expect(validateLocalApplicationCode('sales-app')).toBe('')
    expect(validateLocalApplicationCode('销售助手')).not.toBe('')
  })

  it('uses one dialog with a system parent-directory picker', () => {
    expect(dialogSource).toContain('data-testid="local-app-name"')
    expect(dialogSource).toContain('data-testid="local-app-code"')
    expect(dialogSource).toContain('data-testid="local-app-project-path"')
    expect(dialogSource).toContain("pickDirectory('选择本地应用保存位置')")
    expect(dialogSource).toContain('local_application: true')
    expect(dialogSource).toContain('local_workspace_path: projectPath.value')
    expect(dialogSource).toContain('创建并打开')
    expect(dialogSource).not.toContain('ElMessageBox.prompt')
  })
})
