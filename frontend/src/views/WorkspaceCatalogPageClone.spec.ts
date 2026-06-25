import { describe, expect, it } from 'vitest'
import workspaceCatalogSource from './WorkspaceCatalogPage.vue?raw'
import codingApiSource from '../api/coding.ts?raw'

describe('P3 clone 入口契约', () => {
  it('catalog 有「从 git 仓打开」按钮 + clone 弹窗 + confirmClone', () => {
    expect(workspaceCatalogSource).toContain('从 git 仓打开')
    expect(workspaceCatalogSource).toContain('openCloneDialog')
    expect(workspaceCatalogSource).toContain('cloneDialogOpen')
    expect(workspaceCatalogSource).toContain('confirmClone')
    expect(workspaceCatalogSource).toContain('gitCloneWorkspace')
    // clone 成功导航到统一外壳 code 会话
    expect(workspaceCatalogSource).toContain("mode: 'code'")
  })

  it('codingApi 暴露 gitCloneWorkspace 打到 /coding/workspaces/git/clone', () => {
    expect(codingApiSource).toContain('gitCloneWorkspace')
    expect(codingApiSource).toContain('/coding/workspaces/git/clone')
  })
})
