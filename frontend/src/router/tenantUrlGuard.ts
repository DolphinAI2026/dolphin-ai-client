import type { TenantSwitchContextOutcome } from '@/stores/user'
import type { LocationQuery, RouteLocationRaw } from 'vue-router'

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
const TENANT_SWITCH_MARKER_KEY = 'tenant-url-switch'
const TENANT_SWITCH_MARKER_TTL_MS = 30_000

export interface TenantUrlTenant {
  tenant_id: number
  tenant_public_id?: string | null
}

export type TenantResolutionDecision =
  | { kind: 'continue' }
  | { kind: 'canonicalize'; tenantPublicId: string }
  | { kind: 'switch'; tenantId: number; tenantPublicId: string }
  | { kind: 'reject'; reason: 'invalid' | 'inaccessible' }
  | { kind: 'remove' }

export interface TenantTargetInput {
  rawTenantId: unknown
  currentTenantPublicId: unknown
  availableTenants: TenantUrlTenant[]
  tenantContext?: 'required' | 'none'
}

export interface TenantUrlRoute {
  path: string
  fullPath: string
  query: LocationQuery
  hash: string
  meta: {
    tenantContext?: 'required' | 'none'
  }
}

export interface TenantUrlUserStore {
  user: { tenant_public_id?: string | null } | null
  isPlatformAdmin?: boolean
  availableTenants: TenantUrlTenant[]
  fetchAvailableTenants?: () => Promise<TenantUrlTenant[]>
  switchTenantContext: (
    targetTenantId: number,
    targetTenantPublicId: string,
    destination: string,
  ) => Promise<TenantSwitchContextOutcome>
}

export interface TenantUrlModeStore {
  meta: { home: string }
}

interface TenantSwitchMarker {
  targetTenantPublicId: string
  targetFullPath: string
  startedAt: number
  attempt: number
  ownerId: number
}

interface TenantSwitchFlight {
  targetTenantPublicId: string
  targetFullPath: string
  sourceTenantPublicId: string | null
  sourceUser: TenantUrlUserStore['user']
  userStore: TenantUrlUserStore
  marker: TenantSwitchMarker
  operation: Promise<TenantSwitchContextOutcome>
}

interface TenantResolverIntent {
  generation: number
  targetTenantPublicId: string
  sourceTenantPublicId: string | null
  sourceUser: TenantUrlUserStore['user']
  userStore: TenantUrlUserStore
}

interface TenantResolverIntentState {
  latest: TenantResolverIntent | null
}

let activeTenantSwitch: TenantSwitchFlight | null = null
let nextTenantResolverIntentGeneration = 0
let nextTenantSwitchMarkerOwnerId = 0
const tenantResolverIntentStates = new WeakMap<TenantUrlUserStore, TenantResolverIntentState>()

function firstQueryValue(raw: unknown): unknown {
  return Array.isArray(raw) ? raw[0] : raw
}

export function normalizeTenantPublicId(raw: unknown): string | null {
  const value = firstQueryValue(raw)
  const normalized = typeof value === 'string' ? value.trim().toLowerCase() : ''
  return UUID_RE.test(normalized) ? normalized : null
}

export function classifyTenantTarget({
  rawTenantId,
  currentTenantPublicId,
  availableTenants,
  tenantContext = 'required',
}: TenantTargetInput): TenantResolutionDecision {
  if (tenantContext === 'none') {
    return rawTenantId === undefined ? { kind: 'continue' } : { kind: 'remove' }
  }

  const current = normalizeTenantPublicId(currentTenantPublicId)
  const isArray = Array.isArray(rawTenantId)
  if (isArray && rawTenantId.length !== 1) {
    return { kind: 'reject', reason: 'invalid' }
  }
  const raw = firstQueryValue(rawTenantId)
  if (raw == null) {
    return current
      ? { kind: 'canonicalize', tenantPublicId: current }
      : { kind: 'reject', reason: 'inaccessible' }
  }

  const target = normalizeTenantPublicId(raw)
  if (!target) return { kind: 'reject', reason: 'invalid' }
  if (target === current) {
    return !isArray && raw === target
      ? { kind: 'continue' }
      : { kind: 'canonicalize', tenantPublicId: target }
  }

  const tenant = availableTenants.find((candidate) => (
    normalizeTenantPublicId(candidate.tenant_public_id) === target
  ))
  if (!tenant) return { kind: 'reject', reason: 'inaccessible' }

  return !isArray && raw === target
    ? { kind: 'switch', tenantId: tenant.tenant_id, tenantPublicId: target }
    : { kind: 'canonicalize', tenantPublicId: target }
}

function routeReplace(
  to: TenantUrlRoute,
  query: LocationQuery,
): RouteLocationRaw {
  return {
    path: to.path,
    query,
    ...(to.hash ? { hash: to.hash } : {}),
    replace: true,
  }
}

function tenantHome(
  currentTenantPublicId: string | null,
  modeStore: TenantUrlModeStore,
  isPlatformAdmin = false,
): RouteLocationRaw | false {
  if (!currentTenantPublicId) {
    return isPlatformAdmin ? { path: '/platform-admin', replace: true } : false
  }
  return {
    path: modeStore.meta.home,
    query: { tenantId: currentTenantPublicId },
    replace: true,
  }
}

function tenantSwitchDestination(fullPath: string): string {
  const base = import.meta.env.BASE_URL || '/'
  const basePath = `/${base.replace(/^\/+|\/+$/g, '')}`
  if (basePath === '/' || fullPath === basePath || fullPath.startsWith(`${basePath}/`)) {
    return fullPath
  }
  return `${basePath}${fullPath}`
}

function readSwitchMarker(): TenantSwitchMarker | null {
  try {
    const raw = sessionStorage.getItem(TENANT_SWITCH_MARKER_KEY)
    if (!raw) return null
    const marker = JSON.parse(raw) as Partial<TenantSwitchMarker>
    if (
      normalizeTenantPublicId(marker.targetTenantPublicId) === null
      || typeof marker.targetFullPath !== 'string'
      || !marker.targetFullPath.startsWith('/')
      || !Number.isFinite(marker.startedAt)
      || marker.attempt !== 1
      || !Number.isSafeInteger(marker.ownerId)
      || marker.ownerId < 1
      || Date.now() - marker.startedAt > TENANT_SWITCH_MARKER_TTL_MS
    ) {
      sessionStorage.removeItem(TENANT_SWITCH_MARKER_KEY)
      return null
    }
    return marker as TenantSwitchMarker
  } catch {
    return null
  }
}

function clearSwitchMarkerIfOwned(marker: TenantSwitchMarker): void {
  try {
    const stored = readSwitchMarker()
    if (
      stored
      && stored.ownerId === marker.ownerId
    ) {
      sessionStorage.removeItem(TENANT_SWITCH_MARKER_KEY)
    }
  } catch {
    // Storage may be unavailable; the server-side switch validation remains authoritative.
  }
}

function writeSwitchMarker(marker: TenantSwitchMarker): void {
  try {
    sessionStorage.setItem(TENANT_SWITCH_MARKER_KEY, JSON.stringify(marker))
  } catch {
    // The marker prevents browser loops but must not block an authorized server-side switch.
  }
}

function clearSwitchMarkerForTarget(targetTenantPublicId: string | null): void {
  if (!targetTenantPublicId) return
  const marker = readSwitchMarker()
  if (marker?.targetTenantPublicId === targetTenantPublicId) {
    clearSwitchMarkerIfOwned(marker)
  }
}

function beginTenantResolverIntent(
  targetTenantPublicId: string,
  sourceTenantPublicId: string | null,
  sourceUser: TenantUrlUserStore['user'],
  userStore: TenantUrlUserStore,
): TenantResolverIntent {
  const intent: TenantResolverIntent = {
    generation: ++nextTenantResolverIntentGeneration,
    targetTenantPublicId,
    sourceTenantPublicId,
    sourceUser,
    userStore,
  }
  const state = tenantResolverIntentStates.get(userStore) || { latest: null }
  state.latest = intent
  tenantResolverIntentStates.set(userStore, state)
  return intent
}

function isLatestTenantResolverIntent(intent: TenantResolverIntent): boolean {
  const state = tenantResolverIntentStates.get(intent.userStore)
  return (
    state?.latest === intent
    && state.latest.generation === intent.generation
    && intent.userStore.user === intent.sourceUser
    && normalizeTenantPublicId(intent.userStore.user?.tenant_public_id)
      === intent.sourceTenantPublicId
  )
}

function liveTenantHome(
  userStore: TenantUrlUserStore,
  modeStore: TenantUrlModeStore,
): RouteLocationRaw | false {
  return tenantHome(
    normalizeTenantPublicId(userStore.user?.tenant_public_id),
    modeStore,
    userStore.isPlatformAdmin,
  )
}

function sameTenantSwitchFlight(
  flight: TenantSwitchFlight,
  targetTenantPublicId: string,
  targetFullPath: string,
  sourceTenantPublicId: string | null,
  sourceUser: TenantUrlUserStore['user'],
  userStore: TenantUrlUserStore,
): boolean {
  return (
    flight.targetTenantPublicId === targetTenantPublicId
    && flight.targetFullPath === targetFullPath
    && flight.sourceTenantPublicId === sourceTenantPublicId
    && flight.sourceUser === sourceUser
    && flight.userStore === userStore
  )
}

async function resolveTenantSwitchFlight(
  flight: TenantSwitchFlight,
  targetTenantPublicId: string,
  userStore: TenantUrlUserStore,
  modeStore: TenantUrlModeStore,
): Promise<RouteLocationRaw | false> {
  try {
    const outcome = await flight.operation
    const liveTenantPublicId = normalizeTenantPublicId(userStore.user?.tenant_public_id)
    if (
      outcome === 'committed_reload'
      && liveTenantPublicId === targetTenantPublicId
    ) {
      return false
    }
    clearSwitchMarkerIfOwned(flight.marker)
    return tenantHome(liveTenantPublicId, modeStore, userStore.isPlatformAdmin)
  } catch {
    clearSwitchMarkerIfOwned(flight.marker)
    return tenantHome(
      normalizeTenantPublicId(userStore.user?.tenant_public_id),
      modeStore,
      userStore.isPlatformAdmin,
    )
  }
}

export async function resolveTenantUrl(
  to: TenantUrlRoute,
  userStore: TenantUrlUserStore,
  modeStore: TenantUrlModeStore,
): Promise<RouteLocationRaw | true | false> {
  const currentTenantPublicId = normalizeTenantPublicId(userStore.user?.tenant_public_id)
  const tenantContext = to.meta.tenantContext
  if (tenantContext !== 'required' && tenantContext !== 'none') {
    return tenantHome(currentTenantPublicId, modeStore, userStore.isPlatformAdmin)
  }

  const sourceUser = userStore.user
  const requestedTenantPublicId = tenantContext === 'required'
    ? normalizeTenantPublicId(to.query.tenantId)
    : null
  const resolverIntent = (
    requestedTenantPublicId
    && requestedTenantPublicId !== currentTenantPublicId
  )
    ? beginTenantResolverIntent(
      requestedTenantPublicId,
      currentTenantPublicId,
      sourceUser,
      userStore,
    )
    : null

  let availableTenants = userStore.availableTenants || []
  let decision = classifyTenantTarget({
    rawTenantId: to.query.tenantId,
    currentTenantPublicId,
    availableTenants,
    tenantContext,
  })

  if (
    decision.kind === 'reject'
    && decision.reason === 'inaccessible'
    && tenantContext === 'required'
    && normalizeTenantPublicId(to.query.tenantId)
    && userStore.fetchAvailableTenants
  ) {
    availableTenants = await userStore.fetchAvailableTenants()
    if (resolverIntent && !isLatestTenantResolverIntent(resolverIntent)) {
      return liveTenantHome(userStore, modeStore)
    }
    decision = classifyTenantTarget({
      rawTenantId: to.query.tenantId,
      currentTenantPublicId,
      availableTenants,
      tenantContext,
    })
  }

  if (decision.kind === 'continue') {
    clearSwitchMarkerForTarget(currentTenantPublicId)
    return true
  }

  if (decision.kind === 'remove') {
    const query = { ...to.query }
    delete query.tenantId
    return routeReplace(to, query)
  }

  if (decision.kind === 'canonicalize') {
    return routeReplace(to, { ...to.query, tenantId: decision.tenantPublicId })
  }

  if (decision.kind === 'reject') {
    return tenantHome(currentTenantPublicId, modeStore, userStore.isPlatformAdmin)
  }

  if (resolverIntent && !isLatestTenantResolverIntent(resolverIntent)) {
    return liveTenantHome(userStore, modeStore)
  }

  const activeSwitch = activeTenantSwitch
  if (
    activeSwitch
    && sameTenantSwitchFlight(
      activeSwitch,
      decision.tenantPublicId,
      to.fullPath,
      currentTenantPublicId,
      sourceUser,
      userStore,
    )
  ) {
    return resolveTenantSwitchFlight(
      activeSwitch,
      decision.tenantPublicId,
      userStore,
      modeStore,
    )
  }

  const marker = readSwitchMarker()
  if (
    marker
    && marker.targetTenantPublicId === decision.tenantPublicId
    && marker.targetFullPath === to.fullPath
  ) {
    clearSwitchMarkerIfOwned(marker)
    return tenantHome(currentTenantPublicId, modeStore, userStore.isPlatformAdmin)
  }

  const flightMarker = {
    targetTenantPublicId: decision.tenantPublicId,
    targetFullPath: to.fullPath,
    startedAt: Date.now(),
    attempt: 1,
    ownerId: ++nextTenantSwitchMarkerOwnerId,
  }
  writeSwitchMarker(flightMarker)

  let operation: Promise<TenantSwitchContextOutcome>
  try {
    operation = userStore.switchTenantContext(
      decision.tenantId,
      decision.tenantPublicId,
      tenantSwitchDestination(to.fullPath),
    )
  } catch {
    clearSwitchMarkerIfOwned(flightMarker)
    return tenantHome(currentTenantPublicId, modeStore, userStore.isPlatformAdmin)
  }

  const flight: TenantSwitchFlight = {
    targetTenantPublicId: decision.tenantPublicId,
    targetFullPath: to.fullPath,
    sourceTenantPublicId: currentTenantPublicId,
    sourceUser,
    userStore,
    marker: flightMarker,
    operation,
  }
  activeTenantSwitch = flight
  void operation.then(
    () => {
      if (activeTenantSwitch === flight) activeTenantSwitch = null
    },
    () => {
      if (activeTenantSwitch === flight) activeTenantSwitch = null
    },
  )
  return resolveTenantSwitchFlight(
    flight,
    decision.tenantPublicId,
    userStore,
    modeStore,
  )
}
