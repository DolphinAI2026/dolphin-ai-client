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

const NAV_LABELS: Record<string, string> = {
  builder: 'AI Builder',
  coding: 'AI Coding',
  marketplace: '组件市场',
}

function normalizeTab(tab: TabItem): TabItem {
  const next = { ...tab }
  if (next.id in NAV_LABELS) next.label = NAV_LABELS[next.id]
  if (next.label === '睿鲸 AI Builder') next.label = 'AI Builder'
  if (next.label === '睿鲸 AI Coding') next.label = 'AI Coding'
  if (next.label === 'aPaaS Builder AI' || next.label === 'aPaaS Builder') next.label = '睿鲸AI工作台'
  return next
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
        const restoredTabs = data.tabs.map((t: TabItem) => normalizeTab(t))
        tabs.value = hasHome ? restoredTabs : [HOME_TAB, ...restoredTabs]
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
    const normalizedTab = normalizeTab(tab)
    const existing = tabs.value.find((t) => t.id === normalizedTab.id)
    if (existing) {
      activeId.value = existing.id
      // 如果新传入的 path/label 跟之前不一样（如同一应用 tab 但 path query 变了），更新
      if (normalizedTab.path !== existing.path) existing.path = normalizedTab.path
      if (normalizedTab.label && normalizedTab.label !== existing.label) existing.label = normalizedTab.label
      return
    }
    tabs.value.push(normalizedTab)
    activeId.value = normalizedTab.id
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
   * Called by router.afterEach — if the route matches an existing tab path,
   * activate it. Doesn't auto-create tabs (避免每次浏览都建 phantom tab)。
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
