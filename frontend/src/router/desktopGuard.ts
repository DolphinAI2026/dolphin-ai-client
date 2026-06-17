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
