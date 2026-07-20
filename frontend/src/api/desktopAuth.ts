import request from '@/utils/request'

export function desktopLogin(data: { username: string; password: string }) {
  return request.post('/desktop-auth/login', data, { authPolicy: 'public' })
}
