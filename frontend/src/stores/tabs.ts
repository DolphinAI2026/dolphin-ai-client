// frontend/src/stores/tabs.ts
//
// Browser-style multi-tab navigation state.
// - tabs[]: list of opened tabs (nav items + opened apps)
// - activeId: currently active tab id
// - openTab(tab): add or activate
// - closeTab(id): remove + auto-switch to neighbor
// - syncFromRoute(path): when user navigates (back/forward/typed URL), match an
//   existing tab as active; if no match, do nothing (avoid creating phantom tabs)
//
// Persistence: localStorage key 'ai-builder-tabs-v1'

import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

export interface TabItem {
  id: string             // unique stable key (use path for nav tabs, app:{id} for app tabs)
  path: string           // router path (with query if any)
  label: string          // shown on tab
  icon: string           // icon key (matches RailSidebar.ICONS) — 'home/apps/chat/code/sparkles/store/database/spark/app'
  closable: boolean      // 首页 false，其它 true
  kind: 'nav' | 'app'    // nav = sidebar nav item; app = opened app instance
}

const STORAGE_KEY = 'ai-builder-tabs-v1'

const HOME_TAB: TabItem = {
  id: 'home',
  path: '/',
  label: '首页',
  icon: 'home',
  closable: false,
  kind: 'nav',
}

export const useTabsStore = defineStore('tabs', () => {
  const tabs = ref<TabItem[]>([HOME_TAB])
  const activeId = ref<string>('home')

  // Restore from localStorage
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const data = JSON.parse(raw)
      if (Array.isArray(data.tabs) && data.tabs.length) {
        const hasHome = data.tabs.some((t: TabItem) => t.id === 'home')
        tabs.value = hasHome ? data.tabs : [HOME_TAB, ...data.tabs]
      }
      if (typeof data.activeId === 'string') activeId.value = data.activeId
    }
  } catch { /* ignore */ }

  function persist() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ tabs: tabs.value, activeId: activeId.value }))
    } catch { /* ignore (quota / private mode) */ }
  }

  watch([tabs, activeId], persist, { deep: true })

  function openTab(tab: TabItem) {
    const existing = tabs.value.find((t) => t.id === tab.id)
    if (existing) {
      activeId.value = existing.id
      // 如果新传入的 path/label 跟之前不一样（如同一应用 tab 但 path query 变了），更新
      if (tab.path !== existing.path) existing.path = tab.path
      if (tab.label && tab.label !== existing.label) existing.label = tab.label
      return
    }
    tabs.value.push(tab)
    activeId.value = tab.id
  }

  function closeTab(id: string): TabItem | null {
    const idx = tabs.value.findIndex((t) => t.id === id)
    if (idx === -1) return null
    const target = tabs.value[idx]
    if (!target || !target.closable) return null
    tabs.value.splice(idx, 1)
    // 如果关的是当前 active，落到邻居 tab
    let nextActive: TabItem | null = null
    if (activeId.value === id) {
      nextActive = tabs.value[Math.max(0, idx - 1)] || tabs.value[0] || null
      if (nextActive) activeId.value = nextActive.id
    }
    return nextActive
  }

  function setActive(id: string) {
    if (tabs.value.find((t) => t.id === id)) {
      activeId.value = id
    }
  }

  /**
   * Called by App.vue watch(route.fullPath) — if path matches an existing tab,
   * activate it AND update tab.path to the new path (so refresh restores the
   * last-browsed location, not the initial openTab path).
   *
   * Matching priority:
   *   1. exact fullPath match
   *   2. same base path + matching constraints:
   *      - app tab (id 'app:N'): query.app_id must match (跨 app 不污染)
   *      - nav tab: same base or path is a sub-path (e.g., /ai-chat ↔ /ai-chat/15)
   *   3. home '/' 特判：仅当 path === '/' 时 match (防 home 兜底污染)
   *
   * No auto-create (避免每次浏览都建 phantom tab).
   *
   * Phase 4 #1 (2026-05-23): tab.path 跟随浏览实时更新 — 解决刷新还原丢
   * 失浏览位置 (e.g., /chat?app_id=4&tab=spec → &tab=preview 切回 spec) 的问题.
   */
  function syncFromRoute(path: string) {
    // ?? '' fallback 兼容 TS strict noUncheckedIndexedAccess (split[0] 类型是 string | undefined)
    const pathBase = path.split('?')[0] ?? ''

    // home '/' 特判: 仅当 path 也是 '/' 时 match (任何 /foo 都不该激活 home)
    if (pathBase === '/') {
      const home = tabs.value.find((t) => t.path === '/')
      if (home) activeId.value = home.id
      return
    }

    // 1. exact fullPath match 优先
    let hit = tabs.value.find((t) => t.path === path)

    // 2. fallback: 同 base / 子路径 matching
    if (!hit) {
      const candidates = tabs.value.filter((t) => {
        if (t.path === '/') return false  // home 不参与兜底
        const tBase = t.path.split('?')[0] ?? ''

        // 同 base
        if (tBase === pathBase) {
          // app tab: 必须 query.app_id 一致 — 跨 app 不污染
          if (t.id.startsWith('app:')) {
            const tAppId = new URLSearchParams(t.path.split('?')[1] || '').get('app_id')
            const pAppId = new URLSearchParams(path.split('?')[1] || '').get('app_id')
            return tAppId !== null && tAppId === pAppId
          }
          return true
        }

        // 子路径 (e.g., nav tab '/ai-chat' ↔ route '/ai-chat/15')
        // app tab id 严格隔离，不允许子路径 fallback
        if (!t.id.startsWith('app:') && pathBase.startsWith(tBase + '/')) return true
        return false
      })
      // 选 base 最长的 (更具体 tab 优先, 防 '/ai-chat' tab 抢走 '/ai-chat/15/edit')
      candidates.sort((a, b) => (b.path.split('?')[0] ?? '').length - (a.path.split('?')[0] ?? '').length)
      hit = candidates[0]
    }

    if (!hit) return
    activeId.value = hit.id

    // 2026-05-23 Phase 4 #1: 把 tab.path 更新成最新浏览路径,
    // 让刷新 / localStorage 还原后, 各 tab 还原到最后浏览位置而非初始 openTab path
    if (hit.path !== path) hit.path = path
  }

  function findTab(id: string): TabItem | undefined {
    return tabs.value.find((t) => t.id === id)
  }

  return { tabs, activeId, openTab, closeTab, setActive, syncFromRoute, findTab }
})
