import { describe, expect, it } from 'vitest'
import source from './DataSchemaEditor.vue?raw'

describe('DataSchemaEditor tabs', () => {
  it('only exposes structure and SQL tabs', () => {
    const tabsSource = source.match(/const SUB_TABS = \[([\s\S]*?)\] as const/)?.[1] || ''

    expect(tabsSource).toContain("{ code: 'schema', label: '结构' }")
    expect(tabsSource).toContain("{ code: 'sql', label: 'SQL' }")
    expect(tabsSource).not.toContain('数据预览')
    expect(tabsSource).not.toContain('relations')
    expect(tabsSource).not.toContain('关系')
  })

  it('does not keep the mock data preview panel', () => {
    expect(source).not.toContain('mock 示例数据')
    expect(source).not.toContain("subTab === 'data'")
    expect(source).not.toContain('mockDataRows')
  })
})
