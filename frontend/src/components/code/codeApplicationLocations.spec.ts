import { describe, expect, it } from 'vitest'
import type { CodeApplication } from '@/api/codeRuntime'
import {
  filterUnifiedCodeApplications,
  mergeCodeApplicationLocations,
  resolveCodeApplicationOpenState,
} from './codeApplicationLocations'

function application(
  externalId: string,
  source: 'd-ai-code' | 'desktop-local',
  overrides: Partial<CodeApplication> = {},
): CodeApplication {
  return {
    id: externalId,
    external_application_id: externalId,
    app_name: 'CRM',
    app_code: 'crm',
    source,
    app_type: 'ai-code',
    status: 'ready',
    models: 0,
    forms: 0,
    roles: 0,
    dicts: 0,
    ...overrides,
  }
}

describe('unified Code application locations', () => {
  it('merges only stable links and keeps each location opening identity', () => {
    const local = application('local-crm', 'desktop-local', {
      logical_application_id: 'logical-crm',
      linked_remote_application_id: 'remote-crm',
      local_workspace_path: '/workspaces/crm',
      availability: 'ready',
    })
    const remote = application('remote-crm', 'd-ai-code', {
      logical_application_id: 'remote-logical-crm',
    })

    const [merged] = mergeCodeApplicationLocations([local], [remote], 'deployment-a')

    expect(merged).toMatchObject({
      logical_application_id: 'logical-crm',
      association: 'linked',
      local: {
        external_application_id: 'local-crm',
        workspace_path: '/workspaces/crm',
      },
      remote: {
        external_application_id: 'remote-crm',
        availability: 'ready',
      },
    })
  })

  it('does not merge same-name records without a stable relationship', () => {
    const local = application('local-crm', 'desktop-local', {
      logical_application_id: 'logical-local-crm',
    })
    const remote = application('remote-crm', 'd-ai-code', {
      logical_application_id: 'logical-remote-crm',
    })

    const merged = mergeCodeApplicationLocations([local], [remote], 'deployment-a')

    expect(merged).toHaveLength(2)
    expect(merged.map(app => app.association).sort()).toEqual(['local_only', 'remote_only'])
  })

  it('uses a deployment-scoped remote fallback id and filters ready locations', () => {
    const remote = application('remote-crm', 'd-ai-code', {
      logical_application_id: null,
    })
    const [merged] = mergeCodeApplicationLocations([], [remote], 'deployment-a')

    expect(merged.logical_application_id).toBe('remote:deployment-a:remote-crm')
    expect(filterUnifiedCodeApplications([merged], 'local')).toEqual([])
    expect(filterUnifiedCodeApplications([merged], 'remote')).toEqual([merged])
  })

  it('requires an explicit first choice for two ready locations', () => {
    const [merged] = mergeCodeApplicationLocations(
      [application('local-crm', 'desktop-local', {
        logical_application_id: 'logical-crm',
        linked_remote_application_id: 'remote-crm',
        availability: 'ready',
      })],
      [application('remote-crm', 'd-ai-code')],
      'deployment-a',
    )

    expect(resolveCodeApplicationOpenState(merged, null)).toMatchObject({
      primaryLocation: null,
      requiresSelection: true,
      rememberedUnavailable: false,
    })
  })

  it('does not silently fall back when the remembered location is unavailable', () => {
    const [merged] = mergeCodeApplicationLocations(
      [application('local-crm', 'desktop-local', {
        logical_application_id: 'logical-crm',
        linked_remote_application_id: 'remote-crm',
        availability: 'missing',
      })],
      [application('remote-crm', 'd-ai-code')],
      'deployment-a',
    )

    expect(resolveCodeApplicationOpenState(merged, 'local')).toMatchObject({
      primaryLocation: 'local',
      requiresSelection: false,
      rememberedUnavailable: true,
    })
  })

  it('keeps a known remote link unavailable when the remote source fails', () => {
    const [merged] = mergeCodeApplicationLocations(
      [application('local-crm', 'desktop-local', {
        logical_application_id: 'logical-crm',
        linked_remote_application_id: 'remote-crm',
        availability: 'ready',
      })],
      [],
      'deployment-a',
      { remoteSourceAvailable: false },
    )

    expect(merged).toMatchObject({
      association: 'linked',
      local: { availability: 'ready' },
      remote: {
        external_application_id: 'remote-crm',
        availability: 'unavailable',
      },
    })
  })
})
