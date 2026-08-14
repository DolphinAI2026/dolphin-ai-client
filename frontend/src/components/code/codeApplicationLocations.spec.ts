import { describe, expect, it } from 'vitest'
import type { CodeApplication } from '@/api/codeRuntime'
import {
  canOpenCodeApplicationLocation,
  filterUnifiedCodeApplications,
  mergeCodeApplicationLocations,
  resolveCodeApplicationOpenState,
  resolveCodeApplicationSourceAvailability,
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

  it('keeps a disappeared durable location invalid until the user chooses again', () => {
    const [localOnly] = mergeCodeApplicationLocations(
      [application('local-crm', 'desktop-local', {
        logical_application_id: 'logical-crm',
        availability: 'ready',
      })],
      [],
      'deployment-a',
    )

    expect(resolveCodeApplicationOpenState(localOnly, 'remote')).toMatchObject({
      primaryLocation: 'remote',
      rememberedUnavailable: true,
    })
  })

  it('projects source failures and retries as unavailable without reviving cached records', () => {
    const localFailed = resolveCodeApplicationSourceAvailability(true, {
      local: { loaded: true, loading: false, error: 'local failed' },
      remote: { loaded: true, loading: false, error: '' },
    })
    const remoteRetrying = resolveCodeApplicationSourceAvailability(true, {
      local: { loaded: true, loading: false, error: '' },
      remote: { loaded: true, loading: true, error: '' },
    })

    expect(localFailed).toEqual({ local: false, remote: true, initialLoadComplete: true })
    expect(remoteRetrying).toEqual({ local: true, remote: false, initialLoadComplete: true })

    const [localFailureProjection] = mergeCodeApplicationLocations(
      [application('local-crm', 'desktop-local', { availability: 'ready' })],
      [application('remote-crm', 'd-ai-code')],
      'deployment-a',
      { localSourceAvailable: localFailed.local, remoteSourceAvailable: localFailed.remote },
    )
    const [remoteRetryProjection] = mergeCodeApplicationLocations(
      [],
      [application('remote-crm', 'd-ai-code')],
      'deployment-a',
      { localSourceAvailable: remoteRetrying.local, remoteSourceAvailable: remoteRetrying.remote },
    )
    expect(localFailureProjection.local?.availability).toBe('unavailable')
    expect(remoteRetryProjection.remote?.availability).toBe('unavailable')
  })

  it('keeps every location unavailable until the initial desktop sources settle', () => {
    const availability = resolveCodeApplicationSourceAvailability(true, {
      local: { loaded: true, loading: false, error: '' },
      remote: { loaded: false, loading: true, error: '' },
    })
    const [merged] = mergeCodeApplicationLocations(
      [application('local-crm', 'desktop-local', {
        logical_application_id: 'logical-crm',
        linked_remote_application_id: 'remote-crm',
        availability: 'ready',
      })],
      [application('remote-crm', 'd-ai-code')],
      'deployment-a',
      {
        localSourceAvailable: availability.local,
        remoteSourceAvailable: availability.remote,
      },
    )

    expect(merged.local?.availability).toBe('unavailable')
    expect(merged.remote?.availability).toBe('unavailable')
    expect(resolveCodeApplicationOpenState(merged, null).primaryLocation).toBeNull()
    expect(canOpenCodeApplicationLocation(merged, 'local', false)).toBe(false)
  })

  it('lets only one local record consume a remote application', () => {
    const merged = mergeCodeApplicationLocations(
      [
        application('local-one', 'desktop-local', { linked_remote_application_id: 'remote-crm' }),
        application('local-two', 'desktop-local', { linked_remote_application_id: 'remote-crm' }),
      ],
      [application('remote-crm', 'd-ai-code')],
      'deployment-a',
      { remoteSourceAvailable: false },
    )

    expect(merged.filter(app => app.association === 'linked')).toHaveLength(1)
    expect(merged.filter(app => app.association === 'local_only')).toHaveLength(1)
  })

  it('rejects repeated opens while an application is already opening', () => {
    const [localOnly] = mergeCodeApplicationLocations(
      [application('local-crm', 'desktop-local', { availability: 'ready' })],
      [],
      'deployment-a',
    )

    expect(canOpenCodeApplicationLocation(localOnly, 'local', false)).toBe(true)
    expect(canOpenCodeApplicationLocation(localOnly, 'local', true)).toBe(false)
  })
})
