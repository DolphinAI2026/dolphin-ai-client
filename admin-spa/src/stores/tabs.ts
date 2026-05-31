// admin-spa/src/stores/tabs.ts
//
// 2026-05-22 — 平台管理多 tab 状态管理 (跟 frontend stores/tabs.ts 同款架构)
// localStorage key 'admin-tabs-v1' 跟 frontend 'ai-builder-tabs-v1' 隔离避免污染.

import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

export interface TabItem {
  id: string             // unique stable key (use path)
  path: string           // router path
  label: string          // shown on tab
  icon: string           // icon key (matches admin sidebar menu icons)
  closable: boolean      // 首页默认不可关
  kind: 'nav' | 'app'    // nav = sidebar nav; app 预留
}

const STORAGE_KEY = 'admin-tabs-v1'
const RETIRED_PATHS = new Set(['/status', '/datasources'])

const HOME_TAB: TabItem = {
  id: '/mcp',
  path: '/mcp',
  label: 'MCP 接入',
  icon: 'connection',
  closable: false,
  kind: 'nav',
}

function normalizePath(path: string): string {
  return path.split('?')[0] || path
}

function isRestorableTab(tab: unknown): tab is TabItem {
  if (!tab || typeof tab !== 'object') return false
  const candidate = tab as Partial<TabItem>
  if (typeof candidate.id !== 'string' || typeof candidate.path !== 'string') return false
  return !RETIRED_PATHS.has(normalizePath(candidate.path))
}

export const useAdminTabsStore = defineStore('admin-tabs', () => {
  const tabs = ref<TabItem[]>([HOME_TAB])
  const activeId = ref<string>(HOME_TAB.id)

  // Restore from localStorage
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const data = JSON.parse(raw)
      if (Array.isArray(data.tabs) && data.tabs.length) {
        const restoredTabs = data.tabs.filter(isRestorableTab)
        const hasHome = restoredTabs.some((t: TabItem) => t.id === HOME_TAB.id)
        tabs.value = hasHome ? restoredTabs : [HOME_TAB, ...restoredTabs]
      }
      if (typeof data.activeId === 'string' && tabs.value.some((t) => t.id === data.activeId)) {
        activeId.value = data.activeId
      }
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
    // 关的是当前 active → 落到邻居
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
   * router.afterEach 调用 — path 匹配现有 tab 就激活, 不 auto-create 防 phantom.
   */
  function syncFromRoute(path: string) {
    const hit = tabs.value.find((t) => t.path === path || t.path.split('?')[0] === path.split('?')[0])
    if (hit) activeId.value = hit.id
  }

  function findTab(id: string): TabItem | undefined {
    return tabs.value.find((t) => t.id === id)
  }

  return { tabs, activeId, openTab, closeTab, setActive, syncFromRoute, findTab }
})
