import { describe, it, expect } from 'vitest'
import { buildFileTree } from './fileTree'

describe('buildFileTree', () => {
  it('把扁平路径建成嵌套树,目录在前、同级按名排序', () => {
    const tree = buildFileTree(['src/index.vue', 'src/api.ts', 'package.json'])
    expect(tree.map(n => n.name)).toEqual(['src', 'package.json'])
    const src = tree[0]
    expect(src.isDir).toBe(true)
    expect(src.path).toBe('src')
    expect(src.children!.map(n => n.name)).toEqual(['api.ts', 'index.vue'])
    expect(src.children!.every(n => !n.isDir)).toBe(true)
    expect(src.children![0].path).toBe('src/api.ts')
  })

  it('支持多级嵌套目录', () => {
    const tree = buildFileTree(['a/b/c.ts', 'a/d.ts'])
    const a = tree[0]
    expect(a.children!.map(n => n.name)).toEqual(['b', 'd.ts'])
    expect(a.children![0].children![0].path).toBe('a/b/c.ts')
  })

  it('空数组返回空树', () => {
    expect(buildFileTree([])).toEqual([])
  })
})
