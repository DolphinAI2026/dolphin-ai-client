export type RouteQueryValue = string | null | Array<string | null> | undefined

export function resolveInitialAppId(raw: RouteQueryValue): number | null {
  const value = Array.isArray(raw) ? raw[0] : raw
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null
}

export function shouldUseRequirementsSpecMode(currentAgent: string, appId: number | null): boolean {
  return currentAgent === 'requirements' && !appId
}
