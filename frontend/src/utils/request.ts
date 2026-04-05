import axios from 'axios'
import type { AxiosInstance, AxiosResponse } from 'axios'

/** API 路径前缀，适配 vite base（本地 /api，生产 /ai-builder/api） */
export const API_PREFIX = `${import.meta.env.BASE_URL}api`.replace('//', '/')

const request: AxiosInstance = axios.create({
  baseURL: API_PREFIX,
  timeout: 60000
})

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
      reqUrl.includes('/auth/register') ||
      reqUrl.includes('/auth/select-tenant')
    const isPlatformSessionIssue =
      errorDetail.includes('Token已过期或无效') ||
      errorDetail.includes('重新连接APaaS平台') ||
      errorDetail.includes('平台') && errorDetail.includes('token')
    const isLoginPage = window.location.pathname.endsWith('/login')

    if ((status === 401 || status === 403) && !isAuthRequest && !isLoginPage && !isPlatformSessionIssue) {
      localStorage.removeItem('token')
      window.location.href = `${import.meta.env.BASE_URL}login`
    }
    // 把后端 detail 挂到 error.message，让业务层 catch 时能直接用 e?.message 拿到
    if (errorDetail) {
      error.message = errorDetail
    }
    return Promise.reject(error)
  }
)

export default request
