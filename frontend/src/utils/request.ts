import axios, { AxiosHeaders } from 'axios'
import type { AxiosInstance, AxiosResponse } from 'axios'
import { isApaasTokenError } from './errorHandler'

declare module 'axios' {
  interface AxiosRequestConfig {
    authFailurePolicy?: 'preserve-source-session'
    committedAuthToken?: string | null
    usesCommittedAuthToken?: boolean
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

let committedAuthToken: string | null | undefined

export function setCommittedAuthToken(token: string | null) {
  committedAuthToken = token
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
    if (!hasExplicitAuthorization(headers)) {
      const token = committedAuthToken === undefined
        ? localStorage.getItem('token')
        : committedAuthToken
      config.committedAuthToken = token
      config.usesCommittedAuthToken = true
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
    const ownsCurrentSession = (
      error.config?.usesCommittedAuthToken === true
      && typeof requestToken === 'string'
      && requestToken === committedAuthToken
      && requestToken === localStorage.getItem('token')
    )
    if (
      ownsCurrentSession
      && shouldRedirectToLoginOnHttpError({ status, reqUrl, errorDetail, isLoginPage })
    ) {
      localStorage.removeItem('token')
      const redirect = encodeURIComponent(currentRouteAsRedirect())
      window.location.href = `${import.meta.env.BASE_URL}login?redirect=${redirect}`
    }
    return Promise.reject(error)
  }
)

export default request
