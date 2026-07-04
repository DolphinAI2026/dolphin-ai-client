import { describe, expect, it } from 'vitest'
import { isCodeRoutePath, MODE_META, MODE_ORDER, modeForRoutePath } from './mode'

describe('mode store metadata', () => {
  it('exposes Builder and Code as first-class shell modes', () => {
    expect(MODE_ORDER).toEqual(['builder', 'code'])
    expect(MODE_META.code.label).toBe('Code')
    expect(MODE_META.code.home).toBe('/code/apps')
    expect(MODE_META.code.nav).toContainEqual(expect.objectContaining({
      label: '新建应用',
      path: '/code/new',
    }))
    expect(MODE_META.code.nav).toContainEqual(expect.objectContaining({
      label: '我的应用',
      path: '/code/apps',
    }))
  })

  it('derives shell mode from route paths', () => {
    expect(isCodeRoutePath('/code')).toBe(true)
    expect(isCodeRoutePath('/code/apps')).toBe(true)
    expect(isCodeRoutePath('/apps')).toBe(false)
    expect(isCodeRoutePath('/coding')).toBe(false)
    expect(modeForRoutePath('/code/apps')).toBe('code')
    expect(modeForRoutePath('/apps')).toBe('builder')
  })
})
