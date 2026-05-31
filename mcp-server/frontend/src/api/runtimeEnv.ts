import request from '@/utils/request'

/**
 * /runtime envs tab — frontend view of the existing /platform-envs response.
 *
 * Backend (backend/app/routes/platform_envs.py:list_envs) returns a flat
 * array with health/heartbeat/deployed_apps/key_expiry/etc. We adapt the
 * snake_case backend payload into camelCase-ish for the v2 page.
 */
export interface RuntimeEnv {
  id: string  // map from alias OR existing id
  name: string
  endpoint: string
  tenant: string
  tenant_name: string
  health: 'ok' | 'warn' | 'error'
  heartbeat: string
  deployed_apps: number
  default: boolean
  key_expiry: string
  key_warn?: boolean
}

export interface RuntimeEnvListResponse {
  environments: RuntimeEnv[]
  total: number
}

export const runtimeEnvApi = {
  list(): Promise<RuntimeEnvListResponse> {
    // .then runs AFTER the response interceptor (which has already unwrapped
    // .data). It's used here to *adapt*, not to unwrap.
    return (request({ url: '/platform-envs', method: 'get' }) as any).then((items: any) => {
      const list: any[] = Array.isArray(items) ? items : (items?.envs || items?.items || [])
      const environments: RuntimeEnv[] = list.map((e: any) => ({
        id: e.alias || String(e.id || ''),
        name: e.name || e.env_name || '',
        endpoint: e.endpoint || e.base_url || '',
        tenant: String(e.platform_tenant_id || e.tenant || ''),
        tenant_name: e.tenant_name || e.platform_tenant_name || '',
        health: (e.health as RuntimeEnv['health']) || 'ok',
        heartbeat: e.heartbeat || e.last_test_at || '—',
        deployed_apps: Number(e.deployed_apps || 0),
        default: !!e.is_default,
        key_expiry: e.key_expiry || '—',
        key_warn: !!e.key_warn,
      }))
      return { environments, total: environments.length }
    }) as Promise<RuntimeEnvListResponse>
  },
}
