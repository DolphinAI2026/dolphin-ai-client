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
    availability: location === 'remote'
      ? (sourceAvailable ? 'ready' : 'unavailable')
      : (application.availability || 'unavailable'),
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
    ...(local ? { local: toLocation(local, 'local') } : {}),
    ...(remote ? { remote: toLocation(remote, 'remote', remoteSourceAvailable) } : {}),
  }
}

export interface MergeCodeApplicationLocationsOptions {
  remoteSourceAvailable?: boolean
}

export function mergeCodeApplicationLocations(
  localApplications: CodeApplication[],
  remoteApplications: CodeApplication[],
  deploymentId: string,
  options: MergeCodeApplicationLocationsOptions = {},
): UnifiedCodeApplicationItem[] {
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
    const remote = (linkedRemoteId && remoteByExternalId.get(linkedRemoteId))
      || (logicalId && remoteByLogicalId.get(logicalId))
      || undefined
    if (remote) consumedRemoteIds.add(stable(remote.external_application_id || remote.id))
    const item = toUnified(local, remote, deploymentId, remoteSourceAvailable)
    if (!remote && linkedRemoteId && !remoteSourceAvailable) {
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
      unified.push(toUnified(undefined, remote, deploymentId, remoteSourceAvailable))
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

export function resolveCodeApplicationOpenState(
  application: UnifiedCodeApplicationItem,
  preferredLocation: CodeExecutionLocation | null,
): CodeApplicationOpenState {
  const existingLocations = (['local', 'remote'] as const)
    .filter(location => Boolean(application[location]))
  const readyLocations = existingLocations
    .filter(location => application[location]?.availability === 'ready')
  const rememberedExists = preferredLocation
    ? existingLocations.includes(preferredLocation)
    : false
  const primaryLocation = rememberedExists
    ? preferredLocation
    : readyLocations.length === 1
      ? readyLocations[0]
      : null

  return {
    primaryLocation,
    readyLocations,
    requiresSelection: !rememberedExists && readyLocations.length > 1,
    rememberedUnavailable: Boolean(
      rememberedExists
      && preferredLocation
      && application[preferredLocation]?.availability !== 'ready',
    ),
  }
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
