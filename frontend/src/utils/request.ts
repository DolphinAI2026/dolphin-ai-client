import axios from 'axios'
import type { AxiosInstance, AxiosResponse } from 'axios'
import { isApaasTokenError } from './errorHandler'

/** API 路径前缀：本地开发固定走 Vite 代理 `/api`，生产环境跟随 base */
export const API_PREFIX = import.meta.env.DEV
  ? '/api'
  : `${import.meta.env.BASE_URL}api`.replace('//', '/')

const request: AxiosInstance = axios.create({
  baseURL: API_PREFIX,
  timeout: 60000
})

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
    const existingAuthorization = config.headers?.Authorization
    if (!existingAuthorization) {
      const token = localStorage.getItem('token')
      if (token) {
        config.headers.Authorization = `Bearer ${token}`
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
    const status = error.response?.status
    const reqUrl = String(error.config?.url || '')
    const errorDetail = String(
      error.response?.data?.detail ||
      error.response?.data?.message ||
      error.response?.data?.error ||
      ''
    )
    const isLoginPage = window.location.pathname.endsWith('/login')
    const sourceToken = localStorage.getItem('token')
    const errorHeaders = error.config?.headers
    const explicitAuthorization = typeof errorHeaders?.get === 'function'
      ? errorHeaders.get('Authorization')
      : errorHeaders?.Authorization || errorHeaders?.authorization
    const isCandidateAuthorization = Boolean(
      sourceToken
      && explicitAuthorization
      && explicitAuthorization !== `Bearer ${sourceToken}`
    )

    if (
      !isCandidateAuthorization
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
