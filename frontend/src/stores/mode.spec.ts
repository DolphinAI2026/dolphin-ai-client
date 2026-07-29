import { describe, expect, it } from 'vitest'
import {
  desktopModeLabel,
  isCodeRoutePath,
  MODE_META,
  MODE_ORDER,
  modeForRoutePath,
  visibleModeNav,
  visibleModesForDesktopScope,
} from './mode'

describe('mode store metadata', () => {
  it('exposes Builder and Code as first-class shell modes', () => {
    expect(MODE_ORDER).toEqual(['builder', 'code'])
    expect(MODE_META.code.label).toBe('Code')
    expect(MODE_META.code.home).toBe('/code/apps')
    expect(MODE_META.code.nav).toContainEqual(expect.objectContaining({
      label: '新建本地应用',
      path: '/code/apps?create=local',
    }))
    expect(MODE_META.code.nav).toContainEqual(expect.objectContaining({
      label: '我的应用',
      path: '/code/apps',
    }))
    expect(MODE_META.code.nav).not.toContainEqual(expect.objectContaining({ path: '/code/new' }))
  })

  it('derives shell mode from route paths', () => {
    expect(isCodeRoutePath('/code')).toBe(true)
    expect(isCodeRoutePath('/code/apps')).toBe(true)
    expect(isCodeRoutePath('/apps')).toBe(false)
    expect(isCodeRoutePath('/coding')).toBe(false)
    expect(modeForRoutePath('/code/apps')).toBe('code')
    expect(modeForRoutePath('/apps')).toBe('builder')
  })

  it('shows local application creation only in the desktop Code shell', () => {
    expect(visibleModeNav('code', true)).toContainEqual(expect.objectContaining({
      key: 'c-local-new',
    }))
    expect(visibleModeNav('code', false)).not.toContainEqual(expect.objectContaining({
      key: 'c-local-new',
    }))
  })

  it('maps desktop entry scope to visible workspace labels', () => {
    expect(visibleModesForDesktopScope('apaas')).toEqual(['builder'])
    expect(visibleModesForDesktopScope('ai_platform')).toEqual(['code'])
    expect(visibleModesForDesktopScope('both')).toEqual(['builder', 'code'])
    expect(desktopModeLabel('builder')).toBe('aPaaS')
    expect(desktopModeLabel('code')).toBe('AI平台')
  })
})
