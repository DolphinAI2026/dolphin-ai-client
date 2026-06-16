import { describe, expect, it } from 'vitest'
import codingPageSource from '../CodingPage.vue?raw'

describe('CodingPage model picker markup', () => {
  it('uses a themed custom listbox instead of a native select', () => {
    expect(codingPageSource).not.toContain('<select')
    expect(codingPageSource).toContain('class="coding-model-picker"')
    expect(codingPageSource).toContain('role="listbox"')
    expect(codingPageSource).toContain('role="option"')
  })
})
