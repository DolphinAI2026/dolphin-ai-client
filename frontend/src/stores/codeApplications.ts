import { defineStore } from 'pinia'
import {
  codeRuntimeApi,
  type CodeApplicationListResponse,
} from '@/api/codeRuntime'

export interface CodeApplicationCacheScope {
  tenantId: number | string
  tenantEpoch?: number
}

export interface CodeApplicationLoadOptions {
  force?: boolean
}

type CodeApplicationListParams = Parameters<typeof codeRuntimeApi.listApplications>[0]

interface CacheEntry {
  tenantId: string
  loadedAt: number
  page: CodeApplicationListResponse
}

const CACHE_TTL_MS = 5_000

function normalizeParams(params: CodeApplicationListParams = {}) {
  return {
    keyword: String(params.keyword || '').trim(),
    provisionStatus: String(params.provisionStatus || '').trim(),
    page: Number(params.page || 1),
    pageSize: Number(params.pageSize || 100),
  }
}

function cacheKey(
  scope: CodeApplicationCacheScope,
  params: CodeApplicationListParams,
): string {
  const normalized = normalizeParams(params)
  return JSON.stringify({
    tenantId: String(scope.tenantId),
    tenantEpoch: Number(scope.tenantEpoch || 0),
    ...normalized,
  })
}

export const useCodeApplicationsStore = defineStore('codeApplications', () => {
  const cache = new Map<string, CacheEntry>()
  const inflight = new Map<string, Promise<CodeApplicationListResponse>>()
  let cacheGeneration = 0
  const tenantGenerations = new Map<string, number>()

  function refresh(
    scope: CodeApplicationCacheScope,
    params: CodeApplicationListParams = {},
  ): Promise<CodeApplicationListResponse> {
    const key = cacheKey(scope, params)
    const joined = inflight.get(key)
    if (joined) return joined

    const normalized = normalizeParams(params)
    const tenantId = String(scope.tenantId)
    const requestGeneration = cacheGeneration
    const requestTenantGeneration = tenantGenerations.get(tenantId) || 0
    const pending = codeRuntimeApi.listApplications(normalized)
      .then((page) => {
        if (
          cacheGeneration === requestGeneration
          && (tenantGenerations.get(tenantId) || 0) === requestTenantGeneration
        ) {
          cache.set(key, {
            tenantId,
            loadedAt: Date.now(),
            page,
          })
        }
        return page
      })
      .finally(() => {
        if (inflight.get(key) === pending) inflight.delete(key)
      })
    inflight.set(key, pending)
    return pending
  }

  function load(
    scope: CodeApplicationCacheScope,
    params: CodeApplicationListParams = {},
    options: CodeApplicationLoadOptions = {},
  ): Promise<CodeApplicationListResponse> {
    const key = cacheKey(scope, params)
    const cached = cache.get(key)
    if (
      !options.force
      && cached
      && Date.now() - cached.loadedAt < CACHE_TTL_MS
    ) {
      return Promise.resolve(cached.page)
    }
    return refresh(scope, params)
  }

  function invalidateTenant(tenantId: number | string): void {
    const expected = String(tenantId)
    for (const [key, entry] of cache.entries()) {
      if (entry.tenantId === expected) cache.delete(key)
    }
    tenantGenerations.set(expected, (tenantGenerations.get(expected) || 0) + 1)
  }

  function clear(): void {
    cache.clear()
    cacheGeneration += 1
  }

  return { load, invalidateTenant, clear }
})
