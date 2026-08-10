import { afterEach, describe, expect, it, vi } from 'vitest'

const authSettingsHarness = vi.hoisted(() => ({
  getPublic: vi.fn(),
}))

vi.mock('@/api/authSettings', () => ({
  authSettingsApi: authSettingsHarness,
}))

import {
  defaultProductHome,
  enabledProductModes,
  loadProductAvailability,
  productForRoute,
  redirectForDisabledProduct,
  resetProductAvailability,
} from './productAvailability'

afterEach(() => {
  authSettingsHarness.getPublic.mockReset()
  resetProductAvailability()
})

describe('product availability', () => {
  it('exposes only Code and the Code home when public settings enable Code only', async () => {
    authSettingsHarness.getPublic.mockResolvedValue({
      products: {
        builder: { enabled: false },
        code: { enabled: true },
      },
    })

    await expect(loadProductAvailability()).resolves.toEqual({ builder: false, code: true })
    expect(enabledProductModes({ builder: false, code: true })).toEqual(['code'])
    expect(defaultProductHome({ builder: false, code: true })).toBe('/code/apps')
  })

  it('exposes only Builder and the Builder home when public settings enable Builder only', async () => {
    authSettingsHarness.getPublic.mockResolvedValue({
      products: {
        builder: { enabled: true },
        code: { enabled: false },
      },
    })

    await expect(loadProductAvailability()).resolves.toEqual({ builder: true, code: false })
    expect(enabledProductModes({ builder: true, code: false })).toEqual(['builder'])
    expect(defaultProductHome({ builder: true, code: false })).toBe('/')
  })

  it('keeps Builder first when both products are enabled', async () => {
    authSettingsHarness.getPublic.mockResolvedValue({
      products: {
        builder: { enabled: true },
        code: { enabled: true },
      },
    })

    await expect(loadProductAvailability()).resolves.toEqual({ builder: true, code: true })
    expect(enabledProductModes({ builder: true, code: true })).toEqual(['builder', 'code'])
    expect(defaultProductHome({ builder: true, code: true })).toBe('/')
  })

  it('falls back to both products when public settings cannot be loaded', async () => {
    authSettingsHarness.getPublic.mockRejectedValue(new Error('unavailable'))

    await expect(loadProductAvailability()).resolves.toEqual({ builder: true, code: true })
  })

  it('reuses the in-flight public settings request', async () => {
    let resolveSettings: (settings: unknown) => void = () => undefined
    authSettingsHarness.getPublic.mockReturnValue(new Promise((resolve) => {
      resolveSettings = resolve
    }))

    const first = loadProductAvailability()
    const second = loadProductAvailability()
    resolveSettings({
      products: {
        builder: { enabled: false },
        code: { enabled: true },
      },
    })

    await expect(Promise.all([first, second])).resolves.toEqual([
      { builder: false, code: true },
      { builder: false, code: true },
    ])
    expect(authSettingsHarness.getPublic).toHaveBeenCalledOnce()
  })

  it('reads a route product only from explicit route metadata', () => {
    expect(productForRoute({ path: '/code/apps', meta: { product: 'code' } })).toBe('code')
    expect(productForRoute({ path: '/code/apps', meta: {} })).toBeUndefined()
  })

  it('redirects a disabled product to the configured default home', () => {
    expect(redirectForDisabledProduct({ builder: false, code: true }, 'builder')).toBe('/code/apps')
    expect(redirectForDisabledProduct({ builder: true, code: false }, 'code')).toBe('/')
    expect(redirectForDisabledProduct({ builder: true, code: true }, 'code')).toBeUndefined()
    expect(redirectForDisabledProduct({ builder: false, code: true }, undefined)).toBeUndefined()
  })
})
