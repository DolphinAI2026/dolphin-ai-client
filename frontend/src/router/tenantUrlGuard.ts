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
  advanceTenantNavigationEpoch: () => number
  isTenantNavigationEpochCurrent: (epoch: number) => boolean
  switchTenantContext: (
    targetTenantId: number,
    targetTenantPublicId: string,
    destination: string,
    navigationEpoch: number,
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
  epoch: number
  marker: TenantSwitchMarker
  operation: Promise<TenantSwitchContextOutcome>
}

let activeTenantSwitch: TenantSwitchFlight | null = null
let nextTenantSwitchMarkerOwnerId = 0

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
    const startedAt = marker.startedAt
    const ownerId = marker.ownerId
    if (
      normalizeTenantPublicId(marker.targetTenantPublicId) === null
      || typeof marker.targetFullPath !== 'string'
      || !marker.targetFullPath.startsWith('/')
      || typeof startedAt !== 'number'
      || !Number.isFinite(startedAt)
      || marker.attempt !== 1
      || typeof ownerId !== 'number'
      || !Number.isSafeInteger(ownerId)
      || ownerId < 1
      || Date.now() - startedAt > TENANT_SWITCH_MARKER_TTL_MS
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
      userStore.isTenantNavigationEpochCurrent(flight.epoch)
      &&
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
  const resolverEpoch = userStore.advanceTenantNavigationEpoch()
  const currentTenantPublicId = normalizeTenantPublicId(userStore.user?.tenant_public_id)
  const sourceUser = userStore.user
  const tenantContext = to.meta.tenantContext
  if (tenantContext !== 'required' && tenantContext !== 'none') {
    return tenantHome(currentTenantPublicId, modeStore, userStore.isPlatformAdmin)
  }

  const isEpochCurrent = () => userStore.isTenantNavigationEpochCurrent(resolverEpoch)
  const isPreflightCurrent = () => (
    isEpochCurrent()
    && userStore.user === sourceUser
    && normalizeTenantPublicId(userStore.user?.tenant_public_id) === currentTenantPublicId
  )

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
    if (!isPreflightCurrent()) {
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

  if (!isPreflightCurrent()) {
    return liveTenantHome(userStore, modeStore)
  }

  const marker = readSwitchMarker()
  if (
    marker
    && marker.targetTenantPublicId === decision.tenantPublicId
    && marker.targetFullPath === to.fullPath
    && activeTenantSwitch?.marker.ownerId !== marker.ownerId
  ) {
    clearSwitchMarkerIfOwned(marker)
    return tenantHome(currentTenantPublicId, modeStore, userStore.isPlatformAdmin)
  }

  if (!isPreflightCurrent()) {
    return liveTenantHome(userStore, modeStore)
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
      resolverEpoch,
    )
  } catch {
    clearSwitchMarkerIfOwned(flightMarker)
    return tenantHome(currentTenantPublicId, modeStore, userStore.isPlatformAdmin)
  }

  const flight: TenantSwitchFlight = {
    targetTenantPublicId: decision.tenantPublicId,
    epoch: resolverEpoch,
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
