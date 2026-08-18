import type {
  CodeExecutionLocation,
  CodeRailHistoryApp,
  CodeRailHistoryResponse,
  CodeSessionPurpose,
} from '@/api/codeRuntime'
import type { RailSession, RailSessionGroup } from '@/composables/railSessions'

export interface CodeRailSession extends RailSession {
  logicalApplicationId: string
  externalApplicationId: string
  executionLocation: CodeExecutionLocation
  sessionPurpose: CodeSessionPurpose
  locationSummary: string
}

export interface CodeRailSessionGroup extends RailSessionGroup {
  items: CodeRailSession[]
  logicalApplicationId: string
  availableLocations: CodeExecutionLocation[]
  localShellSessionId?: string
  remoteShellSessionId?: string
  standardShellSessionId?: string
  locationSessions: Partial<Record<CodeExecutionLocation, CodeRailSession>>
  standardLocationSessions: Partial<Record<CodeExecutionLocation, CodeRailSession>>
}

function text(value: unknown): string {
  return String(value || '').trim()
}

function executionLocation(value: unknown, externalApplicationId: unknown): CodeExecutionLocation {
  if (value === 'local' || value === 'remote') return value
  // Old desktop records were created before execution_location existed.  Their
  // local application id is still authoritative and must not render as remote.
  return text(externalApplicationId).startsWith('local-') ? 'local' : 'remote'
}

function sessionPurpose(value: unknown): CodeSessionPurpose {
  return value === 'project_initialization' || value === 'project_recheck'
    ? value
    : 'standard'
}

function logicalApplicationId(app: CodeRailHistoryApp): string {
  return text(app.logical_application_id) || `legacy:${text(app.external_application_id)}`
}

function applicationName(app: CodeRailHistoryApp): string {
  return text(app.app_name) || text(app.app_code) || text(app.external_application_id) || '未关联应用'
}

export function formatCodeRailLocationSummary(
  location: CodeExecutionLocation,
  workspacePath?: string | null,
  environmentName?: string | null,
): string {
  if (location === 'remote') return `远程 · ${text(environmentName) || '远程环境'}`
  const directory = text(workspacePath)
    .replace(/[\\/]+$/, '')
    .split(/[\\/]/)
    .filter(Boolean)
    .pop()
  return `本机 · ${directory || '本机项目'}`
}

function appSessions(app: CodeRailHistoryApp): CodeRailSession[] {
  const shellSessionId = text(app.shell_session_id)
  if (!shellSessionId) return []
  const location = executionLocation(app.execution_location, app.external_application_id)
  const purpose = sessionPurpose(app.session_purpose)
  const logicalId = logicalApplicationId(app)
  const name = applicationName(app)
  const locationSummary = formatCodeRailLocationSummary(
    location,
    app.workspace_path,
    app.environment_name,
  )
  const runtimeSessions = app.sessions || []
  if (!runtimeSessions.length) {
    return [{
      id: shellSessionId,
      title: `${name} Code`,
      appName: name,
      shellSessionId,
      current: false,
      source: 'code-shell',
      logicalApplicationId: logicalId,
      externalApplicationId: text(app.external_application_id),
      executionLocation: location,
      sessionPurpose: purpose,
      locationSummary,
    }]
  }
  return runtimeSessions.flatMap((session) => {
    const runtimeSessionId = text(session.runtimeSessionId)
    if (!runtimeSessionId || session.deletedAt) return []
    return [{
      id: runtimeSessionId,
      title: text(session.title) || `会话 ${runtimeSessionId.replace(/^runtime-/, '').slice(0, 8)}`,
      updatedAt: session.lastActiveAt || session.updatedAt || session.createdAt || undefined,
      status: session.state || undefined,
      appName: name,
      shellSessionId,
      runtimeSessionId,
      current: Boolean(session.current),
      source: 'code-agent' as const,
      logicalApplicationId: logicalId,
      externalApplicationId: text(app.external_application_id),
      executionLocation: location,
      sessionPurpose: purpose,
      locationSummary,
    }]
  })
}

export function codeRailHistorySessions(history: CodeRailHistoryResponse | null | undefined): CodeRailSession[] {
  return (history?.apps || []).flatMap(appSessions)
}

export function groupCodeRailHistoryByApplication(
  history: CodeRailHistoryResponse | null | undefined,
): CodeRailSessionGroup[] {
  const grouped = new Map<string, CodeRailSession[]>()
  for (const session of codeRailHistorySessions(history)) {
    const items = grouped.get(session.logicalApplicationId) || []
    items.push(session)
    grouped.set(session.logicalApplicationId, items)
  }
  return [...grouped.entries()].map(([logicalApplicationId, items]) => {
    const sorted = [...items].sort((left, right) => Date.parse(right.updatedAt || '') - Date.parse(left.updatedAt || ''))
    const locationSessions: Partial<Record<CodeExecutionLocation, CodeRailSession>> = {}
    const standardLocationSessions: Partial<Record<CodeExecutionLocation, CodeRailSession>> = {}
    for (const session of sorted) {
      if (session.sessionPurpose === 'standard') {
        if (!standardLocationSessions[session.executionLocation]) {
          standardLocationSessions[session.executionLocation] = session
        }
        locationSessions[session.executionLocation] = standardLocationSessions[session.executionLocation]
      } else if (!locationSessions[session.executionLocation]) {
        locationSessions[session.executionLocation] = session
      }
    }
    const availableLocations = (['local', 'remote'] as const)
      .filter(location => Boolean(locationSessions[location]))
    const localShellSessionId = locationSessions.local?.shellSessionId
    const remoteShellSessionId = locationSessions.remote?.shellSessionId
    const standardShellSessionId = (
      standardLocationSessions.local?.shellSessionId
      || standardLocationSessions.remote?.shellSessionId
    )
    return {
      label: sorted[0]?.appName || '未关联应用',
      items: sorted,
      shellSessionId: localShellSessionId || remoteShellSessionId,
      logicalApplicationId,
      availableLocations,
      ...(localShellSessionId ? { localShellSessionId } : {}),
      ...(remoteShellSessionId ? { remoteShellSessionId } : {}),
      ...(standardShellSessionId ? { standardShellSessionId } : {}),
      locationSessions,
      standardLocationSessions,
    }
  }).sort((left, right) => Date.parse(right.items[0]?.updatedAt || '') - Date.parse(left.items[0]?.updatedAt || ''))
}

export function findCodeRailHistoryApp(
  history: CodeRailHistoryResponse | null | undefined,
  shellSessionId: string,
): CodeRailHistoryApp | undefined {
  return (history?.apps || []).find(app => text(app.shell_session_id) === text(shellSessionId))
}
