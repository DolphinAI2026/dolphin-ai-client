import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import request from './request'

function runRequestInterceptor(config: { headers?: Record<string, string> }) {
  const handler = (
    request.interceptors.request as unknown as {
      handlers: Array<{ fulfilled?: (value: typeof config) => typeof config }>
    }
  ).handlers.find((candidate) => candidate.fulfilled)?.fulfilled

  if (!handler) {
    throw new Error('request interceptor is not registered')
  }

  return handler(config)
}

function runResponseErrorInterceptor(error: {
  response?: { status?: number; data?: { detail?: string } }
  config?: { url?: string; headers?: Record<string, string> }
}) {
  const handler = (
    request.interceptors.response as unknown as {
      handlers: Array<{ rejected?: (reason: typeof error) => Promise<never> }>
    }
  ).handlers.find((candidate) => candidate.rejected)?.rejected

  if (!handler) {
    throw new Error('response interceptor is not registered')
  }

  return handler(error)
}

describe('request explicit Authorization', () => {
  beforeEach(() => {
    const storage = new Map<string, string>()
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
      removeItem: (key: string) => storage.delete(key),
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('preserves an explicit Authorization header over localStorage token', async () => {
    localStorage.setItem('token', 'source-token')

    const config = await runRequestInterceptor({
      headers: { Authorization: 'Bearer candidate-token' },
    })

    expect(config.headers?.Authorization).toBe('Bearer candidate-token')
  })

  it('keeps the source session when explicit candidate authorization fails', async () => {
    const location = {
      pathname: '/ai-builder/',
      search: '',
      hash: '',
      href: '',
    }
    vi.stubGlobal('window', { location })
    localStorage.setItem('token', 'source-token')
    const error = {
      response: { status: 401, data: { detail: 'candidate token is invalid' } },
      config: {
        url: '/auth/me',
        headers: { Authorization: 'Bearer candidate-token' },
      },
    }

    await expect(runResponseErrorInterceptor(error)).rejects.toBe(error)

    expect(localStorage.getItem('token')).toBe('source-token')
    expect(location.href).toBe('')
  })
})
