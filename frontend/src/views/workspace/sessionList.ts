import type { SessionItem } from '@/components/common/SessionSidebar.vue'
import type { Binding } from './binding'
import { bindingBadge, prefixedId } from './binding'

export interface WorkspaceSession {
  id: string | number
  title: string
  binding: Binding
  updated_at?: string | null
  created_at?: string | null
}

const DAY = 24 * 60 * 60 * 1000

export function timeGroup(iso: string | null | undefined, nowMs: number): string {
  if (!iso) return '更早'
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return '更早'
  const now = new Date(nowMs)
  const today0 = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  if (t >= today0) return '今天'
  if (t >= today0 - DAY) return '昨天'
  if (t >= today0 - 7 * DAY) return '本周'
  if (t >= today0 - 30 * DAY) return '本月'
  return '更早'
}

export function toSessionItems(sessions: WorkspaceSession[], nowMs: number): SessionItem[] {
  const sorted = [...sessions].sort((a, b) => {
    const ta = new Date(a.updated_at || a.created_at || 0).getTime()
    const tb = new Date(b.updated_at || b.created_at || 0).getTime()
    return tb - ta
  })
  return sorted.map(s => {
    const badge = bindingBadge(s.binding)
    return {
      id: prefixedId(s.binding.kind, s.id),
      title: s.title,
      badgeTone: badge.tone,
      badgeLabel: badge.label,
      group: timeGroup(s.updated_at || s.created_at, nowMs),
    }
  })
}
