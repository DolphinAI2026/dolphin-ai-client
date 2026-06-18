import { describe, expect, it } from 'vitest'
import { normalizeRunResult } from './runResult'

describe('normalizeRunResult', () => {
  it('maps a manual run_result event', () => {
    const r = normalizeRunResult({
      type: 'run_result', source: 'manual', dev_url: 'http://127.0.0.1:8081/',
      status: 'error', log_tail: ['App running'], errors: ['[console.error] boom'],
      capture_available: true,
    })
    expect(r.source).toBe('manual')
    expect(r.dev_url).toBe('http://127.0.0.1:8081/')
    expect(r.status).toBe('error')
    expect(r.errors).toEqual(['[console.error] boom'])
    expect(r.capture_available).toBe(true)
    expect(r.round).toBeNull()
  })

  it('maps a C5 autofix_round event (verifying → running)', () => {
    const r = normalizeRunResult({
      type: 'autofix_round', round: 0, status: 'verifying', errors: [],
      dev_url: 'http://127.0.0.1:8080/',
    })
    expect(r.source).toBe('autofix')
    expect(r.status).toBe('running')
    expect(r.round).toBe(0)
    expect(r.dev_url).toBe('http://127.0.0.1:8080/')
  })

  it('maps autofix clean → ok and fixing/exhausted/repeated → error', () => {
    expect(normalizeRunResult({ type: 'autofix_round', round: 1, status: 'clean', errors: [] }).status).toBe('ok')
    expect(normalizeRunResult({ type: 'autofix_round', round: 1, status: 'fixing', errors: ['e'] }).status).toBe('error')
    expect(normalizeRunResult({ type: 'autofix_round', round: 2, status: 'exhausted', errors: ['e'] }).status).toBe('error')
    expect(normalizeRunResult({ type: 'autofix_round', round: 2, status: 'repeated', errors: ['e'] }).status).toBe('error')
  })

  it('defaults missing fields safely', () => {
    const r = normalizeRunResult({ type: 'run_result', source: 'manual' })
    expect(r.dev_url).toBe('')
    expect(r.errors).toEqual([])
    expect(r.log_tail).toEqual([])
    expect(r.capture_available).toBe(false)
  })
})
