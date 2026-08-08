import { describe, expect, it } from 'vitest'

import * as loginRedirect from './loginRedirect'

describe('external login redirect', () => {
  it('maps the web console route to a hard navigation under the Builder base path', () => {
    const resolveExternalLoginRedirect = (
      loginRedirect as typeof loginRedirect & {
        resolveExternalLoginRedirect?: (raw: unknown, baseUrl: string) => string
      }
    ).resolveExternalLoginRedirect

    expect(resolveExternalLoginRedirect).toBeTypeOf('function')
    expect(resolveExternalLoginRedirect?.('/web-console/', '/builder-standalone/')).toBe(
      '/builder-standalone/web-console/',
    )
    expect(resolveExternalLoginRedirect?.('/apps', '/builder-standalone/')).toBe('')
  })
})
