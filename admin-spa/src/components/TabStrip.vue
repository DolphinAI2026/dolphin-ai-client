<!-- admin-spa/src/components/TabStrip.vue
  2026-05-22 — 平台管理多 tab 栏 (跟 frontend v2/TabStrip.vue 同款架构)
  - <a :href> + onTabClick 检测 modifier 让 cmd+click 真开新 chrome tab
  - 普通 click → 内部切 view (router.push + activeId)
  - tab × 关闭, 首页 / 状态 不可关
-->
<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAdminTabsStore, type TabItem } from '@/stores/tabs'

const router = useRouter()
const tabsStore = useAdminTabsStore()

const tabs = computed(() => tabsStore.tabs)
const activeId = computed(() => tabsStore.activeId)

// admin-spa icon set — 跟 AdminLayout 的 menu icon 一致
const ICONS: Record<string, string> = {
  status:     '<path d="M3 12h4l3-9 4 18 3-9h4"/>',
  connection: '<path d="M9 12 5 8l4-4"/><path d="M5 8h14"/><path d="m15 12 4 4-4 4"/><path d="M19 16H5"/>',
  flask:      '<path d="M10 2v6L4 18a2 2 0 0 0 2 3h12a2 2 0 0 0 2-3l-6-10V2"/><path d="M8 14h8"/>',
  logs:       '<path d="M3 7h18M3 12h12M3 17h18"/>',
  building:   '<rect x="4" y="2" width="16" height="20" rx="1"/><path d="M9 8h2M13 8h2M9 12h2M13 12h2M9 16h2M13 16h2"/>',
  cpu:        '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 2v2M15 2v2M9 20v2M15 20v2M2 9h2M2 15h2M20 9h2M20 15h2"/>',
  user:       '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  workspaces: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  app:        '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
}

function renderIcon(name: string): string {
  const inner = ICONS[name] ?? ICONS.app
  return `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`
}

function activate(tab: TabItem) {
  tabsStore.setActive(tab.id)
  router.push(tab.path)
}

function buildHref(path: string): string {
  try {
    return router.resolve(path).href
  } catch {
    return path
  }
}

function onTabClick(e: MouseEvent, tab: TabItem) {
  // modifier key 或 middle click → 浏览器原生处理 (开新 chrome tab)
  if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) {
    return
  }
  e.preventDefault()
  activate(tab)
}

function close(e: MouseEvent, tab: TabItem) {
  e.preventDefault()
  e.stopPropagation()
  const next = tabsStore.closeTab(tab.id)
  if (next) router.push(next.path)
}

// ─── 溢出滚动 (跟 frontend TabStrip 一致) ───
const scrollerRef = ref<HTMLDivElement | null>(null)
const canScrollLeft = ref(false)
const canScrollRight = ref(false)

function updateScrollState() {
  const el = scrollerRef.value
  if (!el) {
    canScrollLeft.value = false
    canScrollRight.value = false
    return
  }
  canScrollLeft.value = el.scrollLeft > 1
  canScrollRight.value = el.scrollLeft + el.clientWidth < el.scrollWidth - 1
}

function scrollByAmount(delta: number) {
  const el = scrollerRef.value
  if (!el) return
  el.scrollBy({ left: delta, behavior: 'smooth' })
  setTimeout(updateScrollState, 220)
}

let _resizeObs: ResizeObserver | null = null
onMounted(() => {
  nextTick(() => {
    updateScrollState()
    if (typeof ResizeObserver !== 'undefined' && scrollerRef.value) {
      _resizeObs = new ResizeObserver(updateScrollState)
      _resizeObs.observe(scrollerRef.value)
      Array.from(scrollerRef.value.children).forEach(child => {
        if (child instanceof Element) _resizeObs?.observe(child)
      })
    }
  })
})

onBeforeUnmount(() => {
  if (_resizeObs) {
    _resizeObs.disconnect()
    _resizeObs = null
  }
})

watch(tabs, async () => {
  await nextTick()
  updateScrollState()
  if (_resizeObs && scrollerRef.value) {
    _resizeObs.disconnect()
    _resizeObs.observe(scrollerRef.value)
    Array.from(scrollerRef.value.children).forEach(child => {
      if (child instanceof Element) _resizeObs?.observe(child)
    })
  }
}, { deep: false })
</script>

<template>
  <div class="admin-tab-strip-wrap" v-if="tabs.length">
    <button
      v-if="canScrollLeft"
      type="button"
      class="admin-tab-scroll-btn left"
      aria-label="向左滚动 tab"
      @click="scrollByAmount(-220)"
    >‹</button>
    <div
      ref="scrollerRef"
      class="admin-tab-strip"
      @scroll="updateScrollState"
    >
      <a
        v-for="tab in tabs"
        :key="tab.id"
        :href="buildHref(tab.path)"
        class="admin-tab"
        :class="{ active: tab.id === activeId }"
        :title="`${tab.label} (Cmd+点 在新标签中打开)`"
        @click="onTabClick($event, tab)"
        @auxclick="onTabClick($event, tab)"
      >
        <span class="admin-tab-icon" v-html="renderIcon(tab.icon)" />
        <span class="admin-tab-label">{{ tab.label }}</span>
        <button
          v-if="tab.closable"
          type="button"
          class="admin-tab-close"
          :aria-label="`关闭 ${tab.label}`"
          @click="close($event, tab)"
        >×</button>
      </a>
    </div>
    <button
      v-if="canScrollRight"
      type="button"
      class="admin-tab-scroll-btn right"
      aria-label="向右滚动 tab"
      @click="scrollByAmount(220)"
    >›</button>
  </div>
</template>

<style scoped>
.admin-tab-strip-wrap {
  position: relative;
  display: flex;
  align-items: center;
  background: var(--surface-2);
  border-bottom: 1px solid var(--line);
  flex-shrink: 0;
  min-height: 36px;
}

.admin-tab-strip {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  overflow-x: auto;
  scrollbar-width: thin;
  padding: 4px 8px 0;
  scroll-behavior: smooth;
}
.admin-tab-strip::-webkit-scrollbar { height: 4px; }
.admin-tab-strip::-webkit-scrollbar-thumb { background: var(--line); border-radius: 2px; }

.admin-tab-scroll-btn {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: linear-gradient(to right, var(--surface-2) 60%, transparent);
  color: var(--text-2);
  font-size: 18px;
  font-family: inherit;
  line-height: 1;
  cursor: pointer;
  z-index: 2;
  padding: 0 2px;
  transition: color 0.12s, background 0.12s;
}
.admin-tab-scroll-btn.left {
  left: 0;
  border-right: 1px solid var(--line);
}
.admin-tab-scroll-btn.right {
  right: 0;
  border-left: 1px solid var(--line);
  background: linear-gradient(to left, var(--surface-2) 60%, transparent);
}
.admin-tab-scroll-btn:hover {
  color: var(--brand);
  background: var(--surface);
}
.admin-tab-scroll-btn:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: -2px;
}

.admin-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 200px;
  min-width: 0;
  padding: 7px 10px 8px;
  border: 1px solid transparent;
  border-bottom: none;
  border-radius: var(--r-2, 6px) var(--r-2, 6px) 0 0;
  background: transparent;
  color: var(--text-2);
  text-decoration: none;
  font-family: inherit;
  font-size: 12.5px;
  font-weight: var(--fw-medium, 500);
  cursor: pointer;
  transition: background 0.12s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.12s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
  margin-bottom: -1px;
  flex-shrink: 0;
}
.admin-tab:hover {
  background: var(--surface);
  color: var(--text);
}
.admin-tab.active {
  background: var(--surface);
  color: var(--brand);
  border-color: var(--line);
  font-weight: var(--fw-semibold, 600);
}
.admin-tab:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: -2px;
}

.admin-tab-icon {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  color: currentColor;
}

.admin-tab-label {
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.admin-tab-close {
  display: grid;
  place-items: center;
  width: 18px;
  height: 18px;
  padding: 0;
  margin-left: 2px;
  border: none;
  border-radius: var(--r-1, 4px);
  background: transparent;
  color: var(--text-3);
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
  font-family: inherit;
  transition: background 0.12s, color 0.12s;
}
.admin-tab-close:hover {
  background: var(--surface-3, var(--surface-2));
  color: var(--text);
}
</style>
