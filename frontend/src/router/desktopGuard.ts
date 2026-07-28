import type { DesktopPhase, DesktopStateSnapshot } from '@/utils/desktop'

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
