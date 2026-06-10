import { describe, it, expect } from 'vitest'
import { buildFileTree, compactTree } from './fileTree'

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

describe('compactTree', () => {
  it('单子目录链合并成一个节点(VS Code compact folders)', () => {
    const tree = compactTree(buildFileTree(['com/xdap/legacyquery/config/A.java', 'com/xdap/legacyquery/dto/B.java']))
    // com→xdap→legacyquery 是单子链,合并;config/dto 是兄弟,保留
    expect(tree).toHaveLength(1)
    expect(tree[0].name).toBe('com/xdap/legacyquery')
    expect(tree[0].path).toBe('com/xdap/legacyquery')
    expect(tree[0].children!.map(n => n.name)).toEqual(['config', 'dto'])
    expect(tree[0].children![0].children![0].path).toBe('com/xdap/legacyquery/config/A.java')
  })

  it('目录下只有一个文件时不合并(只合并目录链)', () => {
    const tree = compactTree(buildFileTree(['src/only.ts']))
    expect(tree[0].name).toBe('src')
    expect(tree[0].children![0].name).toBe('only.ts')
  })

  it('多子节点目录不受影响,不修改原树', () => {
    const raw = buildFileTree(['a/b/c.ts', 'a/d.ts'])
    const tree = compactTree(raw)
    expect(tree[0].name).toBe('a')
    expect(raw[0].children![0].name).toBe('b') // 原树没被原地改
  })
})
