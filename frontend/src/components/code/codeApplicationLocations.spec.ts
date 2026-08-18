import { describe, expect, it } from 'vitest'
import type { CodeApplication } from '@/api/codeRuntime'
import {
  canOpenCodeApplicationLocation,
  filterUnifiedCodeApplications,
  mergeCodeApplicationLocations,
  resolveCodeApplicationLocationRecovery,
  resolveCodeApplicationShellSessionRef,
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

  it('uses an explicit environment name and never treats owner data as one', () => {
    const remote = application('remote-crm', 'd-ai-code', {
      owner: { displayName: 10 } as any,
    })
    const [merged] = mergeCodeApplicationLocations([], [remote], 'deployment-a')

    expect(merged.remote?.environment_name).toBe('远程环境')
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

  it('uses route_id as the canonical shell ref when it differs from public_id', () => {
    expect(resolveCodeApplicationShellSessionRef({
      public_id: 'legacy-public-id',
      route_id: 'canonical-route-id',
      id: 42,
    })).toBe('canonical-route-id')
  })

  it('maps server location errors without trusting a stale ready cache', () => {
    const [linked] = mergeCodeApplicationLocations(
      [application('local-crm', 'desktop-local', {
        logical_application_id: 'logical-crm',
        linked_remote_application_id: 'remote-crm',
        availability: 'ready',
      })],
      [application('remote-crm', 'd-ai-code')],
      'deployment-a',
    )

    expect(resolveCodeApplicationLocationRecovery(
      linked,
      'local',
      'CODE_APPLICATION_ALL_LOCATIONS_UNAVAILABLE',
    )).toEqual({ state: 'all_unavailable', alternativeLocation: null })
    expect(resolveCodeApplicationLocationRecovery(
      linked,
      'local',
      'CODE_APPLICATION_LOCAL_LOCATION_MISSING',
    )).toEqual({ state: 'local_missing', alternativeLocation: 'remote' })
    expect(resolveCodeApplicationLocationRecovery(
      linked,
      'remote',
      'CODE_APPLICATION_REMOTE_LOCATION_UNAVAILABLE',
    )).toEqual({ state: 'remote_unavailable', alternativeLocation: 'local' })
    expect(resolveCodeApplicationLocationRecovery(
      { ...linked, remote: { ...linked.remote!, availability: 'unavailable' } },
      'local',
      'CODE_APPLICATION_LOCAL_LOCATION_MISSING',
    )).toEqual({ state: 'local_missing', alternativeLocation: null })
  })

  it('offers another location only for generic unavailability when that cached location is ready', () => {
    const [linked] = mergeCodeApplicationLocations(
      [application('local-crm', 'desktop-local', {
        logical_application_id: 'logical-crm',
        linked_remote_application_id: 'remote-crm',
        availability: 'ready',
      })],
      [application('remote-crm', 'd-ai-code')],
      'deployment-a',
    )

    expect(resolveCodeApplicationLocationRecovery(
      linked,
      'local',
      'CODE_APPLICATION_LOCATION_UNAVAILABLE',
    )).toEqual({ state: 'local_missing', alternativeLocation: 'remote' })
  })

  it('merges the persisted local API projection with its linked remote application after refresh', () => {
    const [linked] = mergeCodeApplicationLocations(
      [application('local-sales', 'desktop-local', {
        logical_application_id: 'logical-sales',
        linked_remote_application_id: 'remote-sales',
        linked_remote_deployment_id: 'deployment-sales',
        local_workspace_path: '/workspace/sales',
        workspace_id: 'workspace-sales',
        availability: 'missing',
      })],
      [application('remote-sales', 'd-ai-code')],
      'deployment-sales',
    )

    expect(linked.logical_application_id).toBe('logical-sales')
    expect(linked.association).toBe('linked')
    expect(linked.local).toMatchObject({
      availability: 'missing',
      workspace_id: 'workspace-sales',
      workspace_path: '/workspace/sales',
    })
    expect(linked.remote?.location_id).toBe('remote-sales')
  })

  it('maps every stable backend location error to a recovery state', async () => {
    const module = await import('./codeApplicationLocations') as typeof import('./codeApplicationLocations') & {
      codeApplicationRecoveryStateFromError?: (
        errorCode: string,
        location: 'local' | 'remote',
      ) => string | null
    }
    expect(module.codeApplicationRecoveryStateFromError).toBeTypeOf('function')
    expect(module.codeApplicationRecoveryStateFromError!(
      'CODE_APPLICATION_LOCATION_UNAVAILABLE',
      'local',
    )).toBe('local_missing')
    expect(module.codeApplicationRecoveryStateFromError!(
      'CODE_APPLICATION_LOCAL_LOCATION_MISSING',
      'local',
    )).toBe('local_missing')
    expect(module.codeApplicationRecoveryStateFromError!(
      'CODE_APPLICATION_REMOTE_LOCATION_UNAVAILABLE',
      'remote',
    )).toBe('remote_unavailable')
    expect(module.codeApplicationRecoveryStateFromError!(
      'CODE_APPLICATION_ALL_LOCATIONS_UNAVAILABLE',
      'remote',
    )).toBe('all_unavailable')
  })
})
