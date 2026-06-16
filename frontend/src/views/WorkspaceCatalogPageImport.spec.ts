import { describe, expect, it } from 'vitest'
import workspaceCatalogSource from './WorkspaceCatalogPage.vue?raw'

describe('WorkspaceCatalogPage source import', () => {
  it('offers a zip source import entry from the asset catalog', () => {
    expect(workspaceCatalogSource).toContain('导入源码')
    expect(workspaceCatalogSource).toContain('openImportDialog')
    expect(workspaceCatalogSource).toContain('accept=".zip"')
  })

  it('creates an imported workspace with the selected app association', () => {
    expect(workspaceCatalogSource).toContain('codingApi.importZipToWorkspace')
    expect(workspaceCatalogSource).toContain('project_id: importAppId.value || undefined')
    expect(workspaceCatalogSource).toContain('workspaces.value = [imported, ...workspaces.value.filter')
  })
})
