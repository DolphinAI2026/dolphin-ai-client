import { describe, expect, it } from 'vitest'
import dialogSource from './LocalCodeApplicationDialog.vue?raw'
import {
  createLocalApplicationCode,
  joinLocalProjectPath,
  localApplicationProjectPath,
  shouldApplyDefaultWorkspace,
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
    expect(localApplicationProjectPath('existing_directory', '/home/dev/projects/sales-app', 'ignored'))
      .toBe('/home/dev/projects/sales-app')
    expect(validateLocalApplicationCode('sales-app')).toBe('')
    expect(validateLocalApplicationCode('销售助手')).not.toBe('')
  })

  it('uses one dialog with mutually exclusive new and existing directory modes', () => {
    expect(dialogSource).toContain('data-testid="local-app-name"')
    expect(dialogSource).toContain('data-testid="local-app-code"')
    expect(dialogSource.match(/@keydown\.enter\.prevent/g)).toHaveLength(2)
    expect(dialogSource).toContain('data-testid="local-app-project-path"')
    expect(dialogSource).toContain('新建项目')
    expect(dialogSource).toContain('打开已有项目')
    expect(dialogSource).toContain("pickDirectory(directoryMode.value === 'existing_directory'")
    expect(dialogSource).toContain('local_application: true')
    expect(dialogSource).toContain('directory_mode: directoryMode.value')
    expect(dialogSource).toContain('initialize_project: initializeProject.value')
    expect(dialogSource).toContain('local_workspace_path: selectedProjectPath.value')
    expect(dialogSource).toContain('创建并打开项目')
    expect(dialogSource).not.toContain('ElMessageBox.prompt')
  })

  it('accepts an initial directory mode from the shared add menu', () => {
    expect(dialogSource).toContain('initialDirectoryMode?: LocalApplicationDirectoryMode')
    expect(dialogSource).toContain("props.initialDirectoryMode || 'new_directory'")
  })

  it('does not apply a late new-directory default after existing-directory selection', async () => {
    let latestRequest = 1
    const requestId = latestRequest
    let resolveDefault!: (value: string) => void
    const lateDefault = new Promise<string>(resolve => { resolveDefault = resolve })
    let selectedDirectory = '/projects/existing-crm'

    latestRequest += 1
    lateDefault.then(path => {
      if (shouldApplyDefaultWorkspace(requestId, latestRequest, 'existing_directory')) {
        selectedDirectory = path
      }
    })
    resolveDefault('/projects/default-parent')
    await lateDefault

    expect(selectedDirectory).toBe('/projects/existing-crm')
  })
})
