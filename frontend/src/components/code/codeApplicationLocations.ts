import type {
  CodeApplication,
  CodeApplicationLocation,
  CodeExecutionLocation,
  UnifiedCodeApplication,
} from '@/api/codeRuntime'
import type { MergedApplication } from '@/types'

export type CodeApplicationLocationFilter = 'all' | CodeExecutionLocation

export type UnifiedCodeApplicationItem = MergedApplication & UnifiedCodeApplication

function stable(value: unknown): string {
  return String(value || '').trim()
}

function fallbackLogicalId(location: CodeExecutionLocation, deploymentId: string, externalId: string) {
  return `${location}:${stable(deploymentId) || 'current'}:${externalId}`
}

function environmentName(application: CodeApplication): string {
  const owner = application.owner || {}
  return stable(
    application.env_name
    || owner.displayName
    || owner.display_name
    || owner.name
    || owner.tenant_name,
  ) || '远程环境'
}

function toLocation(
  application: CodeApplication,
  location: CodeExecutionLocation,
  sourceAvailable = true,
): CodeApplicationLocation {
  const externalId = stable(application.external_application_id || application.id)
  return {
    location,
    location_id: externalId,
    external_application_id: externalId,
    availability: sourceAvailable
      ? (location === 'remote' ? 'ready' : (application.availability || 'unavailable'))
      : 'unavailable',
    workspace_id: application.workspace_id ?? null,
    workspace_path: application.local_workspace_path ?? null,
    environment_name: location === 'remote' ? environmentName(application) : null,
    original_application: application,
  }
}

function toUnified(
  local: CodeApplication | undefined,
  remote: CodeApplication | undefined,
  deploymentId: string,
  localSourceAvailable: boolean,
  remoteSourceAvailable: boolean,
): UnifiedCodeApplicationItem {
  const representative = remote || local
  if (!representative) throw new Error('A unified Code application needs at least one location')
  const localExternalId = stable(local?.external_application_id || local?.id)
  const remoteExternalId = stable(remote?.external_application_id || remote?.id)
  const logicalId = stable(local?.logical_application_id)
    || stable(remote?.logical_application_id)
    || (local
      ? fallbackLogicalId('local', deploymentId, localExternalId)
      : fallbackLogicalId('remote', deploymentId, remoteExternalId))
  const association = local && remote ? 'linked' : local ? 'local_only' : 'remote_only'

  return {
    ...representative,
    id: logicalId,
    logical_application_id: logicalId,
    app_name: stable(local?.app_name) || stable(remote?.app_name) || '未命名应用',
    app_code: stable(local?.app_code) || stable(remote?.app_code) || undefined,
    source: association === 'linked' ? 'linked' : local ? 'desktop-local' : 'd-ai-code',
    status: representative.status || 'ready',
    app_type: 'ai-code',
    models: representative.models || 0,
    forms: representative.forms || 0,
    roles: representative.roles || 0,
    dicts: representative.dicts || 0,
    association,
    ...(local ? { local: toLocation(local, 'local', localSourceAvailable) } : {}),
    ...(remote ? { remote: toLocation(remote, 'remote', remoteSourceAvailable) } : {}),
  }
}

export interface MergeCodeApplicationLocationsOptions {
  localSourceAvailable?: boolean
  remoteSourceAvailable?: boolean
}

export function mergeCodeApplicationLocations(
  localApplications: CodeApplication[],
  remoteApplications: CodeApplication[],
  deploymentId: string,
  options: MergeCodeApplicationLocationsOptions = {},
): UnifiedCodeApplicationItem[] {
  const localSourceAvailable = options.localSourceAvailable !== false
  const remoteSourceAvailable = options.remoteSourceAvailable !== false
  const remoteByExternalId = new Map<string, CodeApplication>()
  const remoteByLogicalId = new Map<string, CodeApplication>()
  for (const remote of remoteApplications) {
    const externalId = stable(remote.external_application_id || remote.id)
    const logicalId = stable(remote.logical_application_id)
    if (externalId) remoteByExternalId.set(externalId, remote)
    if (logicalId) remoteByLogicalId.set(logicalId, remote)
  }

  const consumedRemoteIds = new Set<string>()
  const unified = localApplications.map((local) => {
    const linkedRemoteId = stable(local.linked_remote_application_id)
    const logicalId = stable(local.logical_application_id)
    const linkedRemote = linkedRemoteId ? remoteByExternalId.get(linkedRemoteId) : undefined
    const logicalRemote = logicalId ? remoteByLogicalId.get(logicalId) : undefined
    const remote = [linkedRemote, logicalRemote].find((candidate) => {
      const externalId = stable(candidate?.external_application_id || candidate?.id)
      return Boolean(candidate && externalId && !consumedRemoteIds.has(externalId))
    })
    if (remote) consumedRemoteIds.add(stable(remote.external_application_id || remote.id))
    const item = toUnified(
      local,
      remote,
      deploymentId,
      localSourceAvailable,
      remoteSourceAvailable,
    )
    if (
      !remote
      && linkedRemoteId
      && !remoteSourceAvailable
      && !consumedRemoteIds.has(linkedRemoteId)
    ) {
      consumedRemoteIds.add(linkedRemoteId)
      item.association = 'linked'
      item.source = 'linked'
      item.remote = {
        location: 'remote',
        location_id: linkedRemoteId,
        external_application_id: linkedRemoteId,
        availability: 'unavailable',
        environment_name: '远程环境',
      }
    }
    return item
  })

  for (const remote of remoteApplications) {
    const externalId = stable(remote.external_application_id || remote.id)
    if (!consumedRemoteIds.has(externalId)) {
      unified.push(toUnified(
        undefined,
        remote,
        deploymentId,
        localSourceAvailable,
        remoteSourceAvailable,
      ))
    }
  }
  return unified
}

export function filterUnifiedCodeApplications(
  applications: UnifiedCodeApplicationItem[],
  filter: CodeApplicationLocationFilter,
): UnifiedCodeApplicationItem[] {
  if (filter === 'all') return applications
  return applications.filter(application => application[filter]?.availability === 'ready')
}

export interface CodeApplicationOpenState {
  primaryLocation: CodeExecutionLocation | null
  readyLocations: CodeExecutionLocation[]
  requiresSelection: boolean
  rememberedUnavailable: boolean
}

export type CodeApplicationRecoveryState =
  | 'local_missing'
  | 'remote_unavailable'
  | 'remembered_unavailable'
  | 'all_unavailable'

export interface CodeApplicationLocationRecovery {
  state: CodeApplicationRecoveryState
  alternativeLocation: CodeExecutionLocation | null
}

export function resolveCodeApplicationShellSessionRef(session: {
  route_id?: unknown
  public_id?: unknown
  id?: unknown
}): string {
  return stable(session.route_id) || stable(session.public_id) || stable(session.id)
}

export function resolveCodeApplicationLocationRecovery(
  application: UnifiedCodeApplicationItem,
  failedLocation: CodeExecutionLocation,
  errorCode = '',
  rememberedLocation: CodeExecutionLocation | null = null,
): CodeApplicationLocationRecovery {
  const alternativeLocation = failedLocation === 'local' ? 'remote' : 'local'
  const alternativeReady = application[alternativeLocation]?.availability === 'ready'
  if (errorCode === 'CODE_APPLICATION_ALL_LOCATIONS_UNAVAILABLE') {
    return { state: 'all_unavailable', alternativeLocation: null }
  }
  if (errorCode === 'CODE_APPLICATION_LOCAL_LOCATION_MISSING') {
    return { state: 'local_missing', alternativeLocation: null }
  }
  if (errorCode === 'CODE_APPLICATION_REMOTE_LOCATION_UNAVAILABLE') {
    return { state: 'remote_unavailable', alternativeLocation: null }
  }
  if (errorCode === 'CODE_APPLICATION_LOCATION_UNAVAILABLE') {
    return {
      state: failedLocation === 'local' ? 'local_missing' : 'remote_unavailable',
      alternativeLocation: alternativeReady ? alternativeLocation : null,
    }
  }

  const allUnavailable = (['local', 'remote'] as const)
    .every(location => application[location]?.availability !== 'ready')
  if (rememberedLocation === failedLocation && alternativeReady) {
    return { state: 'remembered_unavailable', alternativeLocation }
  }
  if (allUnavailable) return { state: 'all_unavailable', alternativeLocation: null }
  return {
    state: failedLocation === 'local' ? 'local_missing' : 'remote_unavailable',
    alternativeLocation: null,
  }
}

export function resolveCodeApplicationOpenState(
  application: UnifiedCodeApplicationItem,
  preferredLocation: CodeExecutionLocation | null,
): CodeApplicationOpenState {
  const existingLocations = (['local', 'remote'] as const)
    .filter(location => Boolean(application[location]))
  const readyLocations = existingLocations
    .filter(location => application[location]?.availability === 'ready')
  const hasRememberedLocation = Boolean(preferredLocation)
  const primaryLocation = hasRememberedLocation
    ? preferredLocation
    : readyLocations.length === 1
      ? readyLocations[0]
      : null

  return {
    primaryLocation,
    readyLocations,
    requiresSelection: !hasRememberedLocation && readyLocations.length > 1,
    rememberedUnavailable: Boolean(
      preferredLocation
      && application[preferredLocation]?.availability !== 'ready',
    ),
  }
}

export interface CodeApplicationSourceState {
  loaded: boolean
  loading: boolean
  error: string
}

export function resolveCodeApplicationSourceAvailability(
  desktop: boolean,
  states: { local: CodeApplicationSourceState; remote: CodeApplicationSourceState },
) {
  const initialLoadComplete = desktop
    ? states.local.loaded && states.remote.loaded
    : states.remote.loaded
  return {
    local: desktop
      && initialLoadComplete
      && !states.local.loading
      && !states.local.error,
    remote: initialLoadComplete
      && !states.remote.loading
      && !states.remote.error,
    initialLoadComplete,
  }
}

export function canOpenCodeApplicationLocation(
  application: UnifiedCodeApplicationItem,
  location: CodeExecutionLocation,
  opening: boolean,
): boolean {
  return !opening && application[location]?.availability === 'ready'
}

export function codeApplicationAssociationLabel(application: UnifiedCodeApplicationItem): string {
  if (application.association === 'linked') return '本机与远程已关联'
  return application.association === 'local_only' ? '仅在本机' : '仅在远程'
}

export function codeApplicationLocationLabel(location: CodeApplicationLocation): string {
  if (location.location === 'remote') return location.environment_name || '远程环境'
  const path = stable(location.workspace_path).replace(/[\\/]+$/, '')
  return path.split(/[\\/]/).filter(Boolean).pop() || '本机项目'
}
