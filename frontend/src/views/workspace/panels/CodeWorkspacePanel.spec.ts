import { describe, expect, it } from 'vitest'
import src from './CodeWorkspacePanel.vue?raw'

describe('CodeWorkspacePanel', () => {
  it('composes FileTree + CodeViewer (复用, 不重写)', () => {
    expect(src).toContain('FileTree')
    expect(src).toContain('CodeViewer')
    expect(src).toContain('useWorkspaceFiles')
  })
  it('derives wsId from binding.workspaceId', () => {
    expect(src).toMatch(/binding[\s\S]*workspaceId/)
  })
  it('wires FileTree select → CodeViewer 当前文件', () => {
    expect(src).toContain('@select')
    expect(src).toContain(':file-path')
  })
})
