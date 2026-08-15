import { isCodeRoutePath } from '@/stores/mode'
import type {
  DesktopPhase,
  DesktopStateSnapshot,
  DesktopWorkspaceEntryScope,
} from '@/utils/desktop'

export interface DesktopBootstrapDecision {
  readyForDocument: boolean
  redirect: string | null
}

export function resolveDesktopBootstrapRedirect(
  phase: DesktopPhase,
  targetPath: string,
): string | null {
  if (phase === 'ready') return null
  if (targetPath.startsWith('/desktop-setup')) return null
  return '/desktop-setup'
}

export async function loadDesktopBootstrapDecision(
  loadState: () => Promise<Pick<DesktopStateSnapshot, 'phase'>>,
  targetPath: string,
): Promise<DesktopBootstrapDecision> {
  try {
    const state = await loadState()
    return {
      readyForDocument: state.phase === 'ready',
      redirect: resolveDesktopBootstrapRedirect(state.phase, targetPath),
    }
  } catch {
    return {
      readyForDocument: false,
      redirect: resolveDesktopBootstrapRedirect('failed', targetPath),
    }
  }
}

const DESKTOP_WORKSPACE_SCOPE_EXEMPT_PATHS = new Set([
  '/desktop-setup',
  '/login',
  '/tenant-select',
  '/workspace-catalog',
  '/desktop-settings',
  '/desktop-unavailable',
])

// Desktop settings is the only local configuration surface. These routes are
// retained for web compatibility and old bookmarks, but must never mount the
// tenant-scoped Builder settings pages inside the desktop shell.
const DESKTOP_LEGACY_SETTINGS_PATHS = new Set([
  '/settings',
  '/platform-envs',
  '/skills',
  '/knowledge',
  '/admin/mcp',
  '/hub',
])

export function resolveDesktopSettingsRedirect(
  isDesktop: boolean,
  targetPath: string,
): string | null {
  if (!isDesktop) return null
  const isLegacyPath = DESKTOP_LEGACY_SETTINGS_PATHS.has(targetPath)
    || targetPath.startsWith('/skills/')
    || targetPath.startsWith('/knowledge/')
    || targetPath.startsWith('/admin/mcp/')
  if (!isLegacyPath) return null
  return '/desktop-settings'
}

export function resolveDesktopWorkspaceRedirect(
  scope: DesktopWorkspaceEntryScope,
  targetPath: string,
): string | null {
  if (DESKTOP_WORKSPACE_SCOPE_EXEMPT_PATHS.has(targetPath)) return null
  if (scope === 'apaas' && isCodeRoutePath(targetPath)) return '/'
  if (scope === 'ai_platform' && !isCodeRoutePath(targetPath)) return '/code/apps'
  return null
}

// 桌面功能边界守卫纯逻辑。meta.desktop==='hidden' 的路由在桌面 build 下落降级页。
export function resolveDesktopRedirect(
  isDesktop: boolean,
  meta: { desktop?: 'hidden' | 'ok' },
  targetPath: string,
): string | null {
  if (!isDesktop) return null
  if (meta.desktop !== 'hidden') return null
  if (targetPath === '/desktop-unavailable') return null
  return '/desktop-unavailable'
}
