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
    if (status === 401 || status === 403) {
      localStorage.removeItem('token')
      window.location.href = `${import.meta.env.BASE_URL}login`
    }
    return Promise.reject(error)
  }
)

export default request
