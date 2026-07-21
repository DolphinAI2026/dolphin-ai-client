import axios, { AxiosHeaders } from 'axios'
import type { AxiosInstance, AxiosResponse } from 'axios'
import { isApaasTokenError } from './errorHandler'

declare module 'axios' {
  interface AxiosRequestConfig {
    authFailurePolicy?: 'preserve-source-session'
    authPolicy?: 'public'
    committedAuthToken?: string | null
    usesCommittedAuthToken?: boolean
    authSessionRevision?: number
    authSessionFailure?: 'authoritative'
  }
}

/** API 路径前缀：本地开发固定走 Vite 代理 `/api`，生产环境跟随 base */
export const API_PREFIX = import.meta.env.DEV
  ? '/api'
  : `${import.meta.env.BASE_URL}api`.replace('//', '/')

const request: AxiosInstance = axios.create({
  baseURL: API_PREFIX,
  timeout: 60000
})

const AUTH_SESSION_STORAGE_KEY = 'ai-builder-auth-session-v1'

export class AuthSessionPendingError extends Error {
  code = 'AUTH_SESSION_PENDING'

  constructor() {
    super('Authentication session validation is pending')
    this.name = 'AuthSessionPendingError'
  }
}

export interface AuthSessionState {
  readonly token: string | null
  readonly revision: number
  readonly initialized: boolean
}

let authSessionStorage: Storage | null | undefined
let authSessionHydrated = false
let committedAuthToken: string | null = null
let authSessionRevision = 0
let authSessionInitialized = false
let authSessionBootstrapToken: string | null = null
let authSessionAlignmentPending = false
const authSessionClearListeners = new Set<() => void>()

function currentSessionStorage(): Storage | null {
  try {
    return typeof sessionStorage === 'undefined' ? null : sessionStorage
  } catch {
    return null
  }
}

function hydrateAuthSession() {
  const storage = currentSessionStorage()
  if (storage !== authSessionStorage) {
    authSessionStorage = storage
    authSessionHydrated = false
    committedAuthToken = null
    authSessionRevision = 0
    authSessionInitialized = false
    authSessionBootstrapToken = null
    authSessionAlignmentPending = false
  }
  if (authSessionHydrated) return

  authSessionHydrated = true
  if (!storage) return

  try {
    const raw = storage.getItem(AUTH_SESSION_STORAGE_KEY)
    if (!raw) return
    const snapshot = JSON.parse(raw) as {
      token?: unknown
      revision?: unknown
    }
    if (
      (typeof snapshot.token === 'string' || snapshot.token === null)
      && Number.isSafeInteger(snapshot.revision)
      && Number(snapshot.revision) >= 0
    ) {
      committedAuthToken = snapshot.token
      authSessionRevision = Number(snapshot.revision)
      authSessionInitialized = true
    }
  } catch {
    try { storage.removeItem(AUTH_SESSION_STORAGE_KEY) } catch { /* ignore */ }
  }
}

function persistAuthSession() {
  const storage = currentSessionStorage()
  if (!storage) return
  try {
    storage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify({
      token: committedAuthToken,
      revision: authSessionRevision,
    }))
  } catch {
    // sessionStorage may be unavailable in private browsing.
  }
}

function authSessionState(): AuthSessionState {
  hydrateAuthSession()
  return {
    token: committedAuthToken,
    revision: authSessionRevision,
    initialized: authSessionInitialized,
  }
}

export function getAuthSessionState(): AuthSessionState {
  return authSessionState()
}

export function getAuthSessionBootstrapToken(): string | null {
  hydrateAuthSession()
  return authSessionBootstrapToken
}

export function beginAuthSessionBootstrap(token: string) {
  hydrateAuthSession()
  authSessionBootstrapToken = token
  authSessionAlignmentPending = false
}

export function beginAuthSessionAlignment(token: string) {
  hydrateAuthSession()
  authSessionRevision += 1
  authSessionBootstrapToken = token
  authSessionAlignmentPending = true
}

export function isAuthSessionAlignmentPending(): boolean {
  hydrateAuthSession()
  return authSessionAlignmentPending
}

function updateAuthSession(token: string | null, notifyClearListeners: boolean): AuthSessionState {
  hydrateAuthSession()
  committedAuthToken = token
  authSessionRevision += 1
  authSessionInitialized = true
  authSessionBootstrapToken = null
  authSessionAlignmentPending = false
  persistAuthSession()
  if (notifyClearListeners) {
    for (const listener of authSessionClearListeners) {
      listener()
    }
  }
  return authSessionState()
}

export function commitAuthSession(token: string): AuthSessionState {
  return updateAuthSession(token, false)
}

export function clearAuthSession(): AuthSessionState {
  return updateAuthSession(null, true)
}

export function subscribeToAuthSessionClear(listener: () => void): () => void {
  authSessionClearListeners.add(listener)
  return () => authSessionClearListeners.delete(listener)
}

type AuthorizationHeaders = {
  has?: (header: string) => boolean
  get?: (header: string) => unknown
  set?: (header: string, value: string) => void
  Authorization?: unknown
  authorization?: unknown
}

function hasExplicitAuthorization(headers: AuthorizationHeaders): boolean {
  if (
    typeof headers.has === 'function'
    && typeof headers.get === 'function'
    && typeof headers.set === 'function'
  ) {
    return headers.has('Authorization') && Boolean(headers.get('Authorization'))
  }
  return Boolean(headers.Authorization || headers.authorization)
}

function setAuthorization(headers: AuthorizationHeaders, token: string) {
  if (typeof headers.set === 'function') {
    headers.set('Authorization', `Bearer ${token}`)
    return
  }
  headers.Authorization = `Bearer ${token}`
}

export function getCommittedAuthToken(): string | null {
  const session = getAuthSessionState()
  if (getAuthSessionBootstrapToken() || !session.initialized) {
    return null
  }
  return session.token
}

export function getCommittedAuthTokenOrThrow(): string {
  const token = getCommittedAuthToken()
  if (!token) {
    throw new AuthSessionPendingError()
  }
  return token
}

function currentRouteAsRedirect(): string {
  const base = import.meta.env.BASE_URL || '/'
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`
  if (base !== '/' && current.startsWith(base)) {
    const withoutBase = current.slice(base.length)
    return `/${withoutBase.replace(/^\/+/, '')}` || '/'
  }
  return current || '/'
}

export function shouldRedirectToLoginOnHttpError(input: {
  status?: number
  reqUrl?: string
  errorDetail?: string
  isLoginPage?: boolean
}): boolean {
  const status = input.status
  const reqUrl = String(input.reqUrl || '')
  const errorDetail = String(input.errorDetail || '')
  const isAuthRequest =
    reqUrl.includes('/auth/login') ||
    reqUrl.includes('/auth/select-tenant')
  const isCodeRuntimeRequest =
    reqUrl.startsWith('/code/') ||
    reqUrl.includes('/code/') ||
    reqUrl.startsWith('/code-runtime/') ||
    reqUrl.includes('/code-runtime/')
  const isPlatformSessionIssue =
    isApaasTokenError(errorDetail) ||
    (errorDetail.includes('平台') && errorDetail.includes('token'))

  return (
    status === 401 &&
    !isAuthRequest &&
    !input.isLoginPage &&
    !isPlatformSessionIssue &&
    !isCodeRuntimeRequest
  )
}

// 请求拦截器
request.interceptors.request.use(
  (config) => {
    const headers = (config.headers ||= new AxiosHeaders()) as AuthorizationHeaders
    if (config.authPolicy === 'public') {
      return config
    }
    if (!hasExplicitAuthorization(headers)) {
      const session = getAuthSessionState()
      if (
        getAuthSessionBootstrapToken()
        || (!session.initialized && localStorage.getItem('token'))
      ) {
        throw new AuthSessionPendingError()
      }
      const token = session.token
      config.committedAuthToken = token
      config.usesCommittedAuthToken = true
      config.authSessionRevision = session.revision
      if (token) {
        setAuthorization(headers, token)
      }
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器
request.interceptors.response.use(
  (response: AxiosResponse) => {
    return response.data
  },
  (error) => {
    if (error.config?.authFailurePolicy === 'preserve-source-session') {
      return Promise.reject(error)
    }

    const status = error.response?.status
    const reqUrl = String(error.config?.url || '')
    const errorDetail = String(
      error.response?.data?.detail ||
      error.response?.data?.message ||
      error.response?.data?.error ||
      ''
    )
    const isLoginPage = window.location.pathname.endsWith('/login')
    const requestToken = error.config?.committedAuthToken
    const session = getAuthSessionState()
    const ownsCurrentSession = (
      error.config?.usesCommittedAuthToken === true
      && typeof requestToken === 'string'
      && requestToken === session.token
      && error.config?.authSessionRevision === session.revision
      && requestToken === localStorage.getItem('token')
    )
    if (
      ownsCurrentSession
      && shouldRedirectToLoginOnHttpError({ status, reqUrl, errorDetail, isLoginPage })
    ) {
      error.config.authSessionFailure = 'authoritative'
      clearAuthSession()
      localStorage.removeItem('token')
      const redirect = encodeURIComponent(currentRouteAsRedirect())
      window.location.href = `${import.meta.env.BASE_URL}login?redirect=${redirect}`
    }
    return Promise.reject(error)
  }
)

export default request
