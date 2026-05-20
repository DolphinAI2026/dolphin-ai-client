/**
 * Axios client — admin SPA 走 /api/ 反代到当前 ai-builder backend。
 *
 * 拦截器：
 *  - request: 注入 Authorization: Bearer <admin_token>
 *  - response: 401 自动跳 /login（admin token 过期或被踢）
 */
import axios from 'axios'
import type { AxiosInstance, AxiosError } from 'axios'

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'

export const api: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30_000,
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('admin_token') || localStorage.getItem('token')
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (resp) => resp,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('admin_token')
      // 当前不在 /login 才跳
      if (!window.location.pathname.endsWith('/login')) {
        window.location.href = `${import.meta.env.BASE_URL}login`
      }
    }
    return Promise.reject(error)
  },
)

/** 包装常用方法（保留 axios 完整 response 给调用方按需取 .data） */
export const apiGet  = <T = any>(url: string, params?: any) => api.get<T>(url, { params }).then((r) => r.data)
export const apiPost = <T = any>(url: string, body?: any)   => api.post<T>(url, body).then((r) => r.data)
export const apiPut  = <T = any>(url: string, body?: any)   => api.put<T>(url, body).then((r) => r.data)
export const apiDel  = <T = any>(url: string)               => api.delete<T>(url).then((r) => r.data)
