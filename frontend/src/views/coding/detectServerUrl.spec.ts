import { describe, it, expect } from 'vitest'
import { detectServerUrl, stripAnsi } from './detectServerUrl'

describe('detectServerUrl', () => {
  it('vue-cli / webpack: App running at', () => {
    const out = '  App running at:\n  - Local:   http://127.0.0.1:8083/\n'
    expect(detectServerUrl(out)).toEqual({ url: 'http://127.0.0.1:8083/', port: 8083 })
  })

  it('vite: ➜  Local:', () => {
    const out = '  VITE v5.0  ready\n  ➜  Local:   http://localhost:5174/\n  ➜  Network: use --host'
    expect(detectServerUrl(out)).toEqual({ url: 'http://localhost:5174/', port: 5174 })
  })

  it('strips ANSI color codes before matching', () => {
    const out = '\x1b[32m  - Local:\x1b[0m   \x1b[36mhttp://127.0.0.1:61999/\x1b[0m'
    expect(detectServerUrl(out)).toEqual({ url: 'http://127.0.0.1:61999/', port: 61999 })
  })

  it('takes the LAST match (port-increment / re-run)', () => {
    const out =
      'App running at: - Local: http://127.0.0.1:8080/\n' +
      'Port 8080 in use, retrying...\n' +
      'App running at: - Local: http://127.0.0.1:8081/\n'
    expect(detectServerUrl(out)).toEqual({ url: 'http://127.0.0.1:8081/', port: 8081 })
  })

  it('normalizes to origin + slash', () => {
    expect(detectServerUrl('Local: http://127.0.0.1:3000')).toEqual({
      url: 'http://127.0.0.1:3000/',
      port: 3000,
    })
  })

  it('returns null for noise (no server line)', () => {
    expect(detectServerUrl('$ ls -la\ntotal 24\ndrwxr-xr-x  node_modules')).toBeNull()
    expect(detectServerUrl('just see http://127.0.0.1:8080 in a readme')).toBeNull() // 无 Local/Network 前缀
    expect(detectServerUrl('')).toBeNull()
  })

  it('stripAnsi removes escape sequences', () => {
    expect(stripAnsi('\x1b[1mhi\x1b[0m')).toBe('hi')
  })
})
