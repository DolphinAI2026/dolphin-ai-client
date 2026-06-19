import { describe, expect, it } from 'vitest'
import src from './ConfigWorkspacePanel.vue?raw'

describe('ConfigWorkspacePanel', () => {
  it('reuses ApaasMenuSidebar + the four designer panels + deeplink (复用不重写)', () => {
    expect(src).toContain('ApaasMenuSidebar')
    expect(src).toContain('FormDesignerPanel')
    expect(src).toContain('DataSchemaEditor')
    expect(src).toContain('ProcessDesignerPanel')
    expect(src).toContain('FormPermPanel')
    expect(src).toContain('OpenLowcodeBackendButton')
  })
  it('derives appId from binding.appId', () => {
    expect(src).toMatch(/binding[\s\S]*appId/)
  })
  it('feeds selected menu (id/form/name) to the designer panels', () => {
    expect(src).toContain('@menu-selected')
    expect(src).toContain(':menu-id')
    expect(src).toContain(':form-id')
  })
  it('perm sub-tab is gated on form_id', () => {
    expect(src).toMatch(/perm[\s\S]*formId|formId[\s\S]*FormPermPanel/)
  })
})
