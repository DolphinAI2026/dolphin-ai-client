import { describe, expect, it } from 'vitest'

import { shouldRedirectToLoginOnHttpError } from './request'

describe('shouldRedirectToLoginOnHttpError', () => {
  it('does not clear ai-builder login for Code Control Plane authorization failures', () => {
    expect(shouldRedirectToLoginOnHttpError({
      status: 401,
      reqUrl: '/code/applications',
      errorDetail: '{"code":"AUTH_TOKEN_INVALID","message":"Authorization Bearer token is invalid"}',
      isLoginPage: false,
    })).toBe(false)
  })

  it('does not treat forbidden business APIs as expired login sessions', () => {
    expect(shouldRedirectToLoginOnHttpError({
      status: 403,
      reqUrl: '/auth/me/tenants',
      errorDetail: 'Forbidden',
      isLoginPage: false,
    })).toBe(false)
  })

  it('still redirects to login for ordinary protected API 401 responses', () => {
    expect(shouldRedirectToLoginOnHttpError({
      status: 401,
      reqUrl: '/applications',
      errorDetail: 'Not authenticated',
      isLoginPage: false,
    })).toBe(true)
  })
})
