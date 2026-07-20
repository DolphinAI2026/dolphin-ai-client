import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AxiosHeaders } from 'axios'
import { readFileSync, readdirSync } from 'node:fs'
import { join, relative } from 'node:path'

import request from './request'
import { authApi } from '@/api/auth'
import { authSettingsApi } from '@/api/authSettings'
import { desktopLogin } from '@/api/desktopAuth'

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
    authPolicy?: 'public'
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
    const sessionStorage = new Map<string, string>()
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
      removeItem: (key: string) => storage.delete(key),
    })
    vi.stubGlobal('sessionStorage', {
      getItem: (key: string) => sessionStorage.get(key) ?? null,
      setItem: (key: string, value: string) => sessionStorage.set(key, value),
      removeItem: (key: string) => sessionStorage.delete(key),
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

  it('lets typed public auth requests bypass bootstrap pending without adapter Authorization', async () => {
    localStorage.setItem('token', 'stale-bootstrap-token')

    const config = await runRequestInterceptor({
      headers: {},
      authPolicy: 'public',
    })

    expect(config.headers?.Authorization).toBeUndefined()
  })

  it.each([
    ['Basic', { Authorization: 'Basic caller-credential' }],
    ['lowercase Bearer', { authorization: 'Bearer caller-credential' }],
  ])('preserves explicit %s Authorization for typed public requests', async (_name, headers) => {
    localStorage.setItem('token', 'stale-bootstrap-token')

    const config = await runRequestInterceptor({
      headers,
      authPolicy: 'public',
    })

    expect(config.headers).toEqual(headers)
  })

  it('marks captcha, login, tenant selection, public settings, and desktop login as public', async () => {
    const get = vi.spyOn(request, 'get').mockResolvedValue({} as never)
    const post = vi.spyOn(request, 'post').mockResolvedValue({} as never)

    await authApi.getCaptcha()
    await authApi.login({ username: 'operator', password: 'secret' })
    await authApi.selectTenant({ selection_token: 'selection', tenant_id: 2 })
    await authSettingsApi.getPublic()
    await desktopLogin({ username: 'operator', password: 'secret' })

    expect(get).toHaveBeenCalledWith('/auth/captcha', { authPolicy: 'public' })
    expect(get).toHaveBeenCalledWith('/auth/settings/public', { authPolicy: 'public' })
    expect(post).toHaveBeenCalledWith('/auth/login', {
      username: 'operator',
      password: 'secret',
    }, { authPolicy: 'public' })
    expect(post).toHaveBeenCalledWith('/auth/select-tenant', {
      selection_token: 'selection',
      tenant_id: 2,
    }, { authPolicy: 'public' })
    expect(post).toHaveBeenCalledWith('/desktop-auth/login', {
      username: 'operator',
      password: 'secret',
    }, { authPolicy: 'public' })
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

  it('has no direct localStorage token reads in production business sources', () => {
    const sourceRoot = join(process.cwd(), 'src')
    const allowed = new Set([
      'stores/user.ts',
      'utils/request.ts',
    ])
    const files: string[] = []
    const collect = (directory: string) => {
      for (const entry of readdirSync(directory, { withFileTypes: true })) {
        const path = join(directory, entry.name)
        if (entry.isDirectory()) {
          collect(path)
        } else if (
          (entry.name.endsWith('.ts') || entry.name.endsWith('.vue'))
          && !entry.name.includes('.spec.')
          && !entry.name.includes('.test.')
        ) {
          files.push(path)
        }
      }
    }
    collect(sourceRoot)

    const directReads = files.flatMap((file) => {
      const source = readFileSync(file, 'utf8')
      return /localStorage\.getItem\(['"]token['"]\)/.test(source)
        && !allowed.has(relative(sourceRoot, file))
        ? [relative(sourceRoot, file)]
        : []
    })

    expect(directReads).toEqual([])
  })

  it('does not use the mutable user-store token for native coding streams', () => {
    const source = readFileSync(join(process.cwd(), 'src/views/coding/useCodingPipeline.ts'), 'utf8')

    expect(source).toContain('getCommittedAuthTokenOrThrow')
    expect(source).not.toContain('Bearer ${userStore.token}')
  })
})
