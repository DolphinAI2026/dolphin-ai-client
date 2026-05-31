import axios from 'axios'
import type { AxiosInstance, AxiosResponse } from 'axios'
import { isApaasTokenError } from './errorHandler'

/** API 路径前缀：始终走后端 `/api`。页面 base 可能是 `/mcp-server/`，不能污染接口路径。 */
export const API_PREFIX = '/api'

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

// 请求拦截器
request.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
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
    const isAuthRequest =
      reqUrl.includes('/auth/login') ||
      reqUrl.includes('/auth/select-tenant')
    // 平台 session 问题：走集中定义的 APAAS_TOKEN_MARKERS，加一条兜底（"平台" + "token" 共现）
    const isPlatformSessionIssue =
      isApaasTokenError(errorDetail) ||
      (errorDetail.includes('平台') && errorDetail.includes('token'))
    const isLoginPage = window.location.pathname.endsWith('/login')

    if ((status === 401 || status === 403) && !isAuthRequest && !isLoginPage && !isPlatformSessionIssue) {
      localStorage.removeItem('token')
      const redirect = encodeURIComponent(currentRouteAsRedirect())
      window.location.href = `${import.meta.env.BASE_URL}login?redirect=${redirect}`
    }
    return Promise.reject(error)
  }
)

export default request
