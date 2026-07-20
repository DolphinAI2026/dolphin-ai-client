import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AxiosHeaders } from 'axios'

import request from './request'
import { authApi } from '@/api/auth'

function runRequestInterceptor(config: { headers?: Record<string, string> | AxiosHeaders }) {
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
  config?: {
    url?: string
    headers?: Record<string, string>
    authFailurePolicy?: 'preserve-source-session'
  }
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
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('preserves an explicit Authorization header over localStorage token', async () => {
    localStorage.setItem('token', 'source-token')

    const config = await runRequestInterceptor({
      headers: { Authorization: 'Bearer candidate-token' },
    })

    expect(config.headers?.Authorization).toBe('Bearer candidate-token')
  })

  it('preserves a lowercase AxiosHeaders authorization value over localStorage token', async () => {
    localStorage.setItem('token', 'source-token')
    const headers = new AxiosHeaders({ authorization: 'Bearer candidate-token' })

    await runRequestInterceptor({ headers })

    expect(headers.get('Authorization')).toBe('Bearer candidate-token')
  })

  it('marks candidate /auth/me requests to preserve the source session on failure', async () => {
    const signal = new AbortController().signal
    const get = vi.spyOn(request, 'get').mockResolvedValue({} as never)

    await authApi.getMeWithToken('candidate-token', signal)

    expect(get).toHaveBeenCalledWith('/auth/me', {
      headers: { Authorization: 'Bearer candidate-token' },
      signal,
      authFailurePolicy: 'preserve-source-session',
    })
  })

  it.each([
    ['401', { status: 401, data: { detail: 'candidate token is invalid' } }],
    ['403', { status: 403, data: { detail: 'forbidden' } }],
    ['5xx', { status: 503, data: { detail: 'temporarily unavailable' } }],
    ['network', undefined],
  ])('keeps source state when a marked candidate request fails with %s', async (_kind, response) => {
    const location = {
      pathname: '/ai-builder/',
      search: '',
      hash: '',
      href: '',
    }
    vi.stubGlobal('window', { location })
    localStorage.setItem('token', 'source-token')
    localStorage.setItem('ai-builder-tabs-v1', 'source-tabs')
    const error = {
      response,
      config: {
        url: '/auth/me',
        headers: { Authorization: 'Bearer source-token' },
        authFailurePolicy: 'preserve-source-session' as const,
      },
    }

    await expect(runResponseErrorInterceptor(error)).rejects.toBe(error)

    expect(localStorage.getItem('token')).toBe('source-token')
    expect(localStorage.getItem('ai-builder-tabs-v1')).toBe('source-tabs')
    expect(location.href).toBe('')
  })
})
