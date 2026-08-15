import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  commitCodeApplicationLocationPreference,
  commitPendingCodeApplicationLocationPreferenceByShellSessionRef,
  discardPendingCodeApplicationLocationPreference,
  discardPendingCodeApplicationLocationPreferenceByShellSessionRef,
  loadCodeApplicationLocationPreference,
  stageCodeApplicationLocationPreference,
} from './codeApplicationLocationPreference'

const scope = {
  deploymentId: 'deployment-a',
  userId: 'user-7',
  logicalApplicationId: 'logical-crm',
}

describe('Code application location preference', () => {
  beforeEach(() => {
    const durable = new Map<string, string>()
    const pending = new Map<string, string>()
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => durable.get(key) ?? null,
      setItem: (key: string, value: string) => durable.set(key, value),
      removeItem: (key: string) => durable.delete(key),
    })
    vi.stubGlobal('sessionStorage', {
      getItem: (key: string) => pending.get(key) ?? null,
      setItem: (key: string, value: string) => pending.set(key, value),
      removeItem: (key: string) => pending.delete(key),
    })
  })

  it('stages a shell selection without changing the durable preference', () => {
    stageCodeApplicationLocationPreference(scope, 'local', 'shell-42')

    expect(loadCodeApplicationLocationPreference(scope)).toBeNull()
  })

  it('commits only the matching application and shell session', () => {
    stageCodeApplicationLocationPreference(scope, 'remote', 'shell-42')

    expect(commitCodeApplicationLocationPreference(scope, 'shell-other')).toBe(false)
    expect(commitCodeApplicationLocationPreference({ ...scope, logicalApplicationId: 'other' }, 'shell-42')).toBe(false)
    expect(loadCodeApplicationLocationPreference(scope)).toBeNull()

    expect(commitCodeApplicationLocationPreference(scope, 'shell-42')).toBe(true)
    expect(loadCodeApplicationLocationPreference(scope)).toBe('remote')
  })

  it('keeps a durable preference when pending storage cleanup fails', () => {
    stageCodeApplicationLocationPreference(scope, 'local', 'shell-42')
    vi.stubGlobal('sessionStorage', {
      getItem: sessionStorage.getItem,
      setItem: sessionStorage.setItem,
      removeItem: () => { throw new Error('storage cleanup unavailable') },
    })

    expect(commitCodeApplicationLocationPreference(scope, 'shell-42')).toBe(true)
    expect(loadCodeApplicationLocationPreference(scope)).toBe('local')
  })

  it('discards a pending selection without changing a previous durable preference', () => {
    stageCodeApplicationLocationPreference(scope, 'local', 'shell-1')
    expect(commitCodeApplicationLocationPreference(scope, 'shell-1')).toBe(true)
    stageCodeApplicationLocationPreference(scope, 'remote', 'shell-2')

    expect(discardPendingCodeApplicationLocationPreference(scope, 'shell-2')).toBe(true)
    expect(loadCodeApplicationLocationPreference(scope)).toBe('local')
  })

  it('uses the shell session index to commit only its pending scope', () => {
    const billingScope = { ...scope, logicalApplicationId: 'logical-billing' }
    stageCodeApplicationLocationPreference(scope, 'local', 'shell-crm')
    stageCodeApplicationLocationPreference(billingScope, 'remote', 'shell-billing')

    expect(commitPendingCodeApplicationLocationPreferenceByShellSessionRef('shell-crm')).toBe(true)
    expect(loadCodeApplicationLocationPreference(scope)).toBe('local')
    expect(loadCodeApplicationLocationPreference(billingScope)).toBeNull()
  })

  it('uses the shell session index to discard only its pending scope', () => {
    const billingScope = { ...scope, logicalApplicationId: 'logical-billing' }
    stageCodeApplicationLocationPreference(scope, 'local', 'shell-crm')
    stageCodeApplicationLocationPreference(billingScope, 'remote', 'shell-billing')

    expect(discardPendingCodeApplicationLocationPreferenceByShellSessionRef('shell-billing')).toBe(true)
    expect(commitPendingCodeApplicationLocationPreferenceByShellSessionRef('shell-crm')).toBe(true)
    expect(loadCodeApplicationLocationPreference(scope)).toBe('local')
    expect(loadCodeApplicationLocationPreference(billingScope)).toBeNull()
  })
})
