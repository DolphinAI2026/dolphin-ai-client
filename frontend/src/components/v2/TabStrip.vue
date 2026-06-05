<!-- frontend/src/components/v2/TabStrip.vue
  浏览器风格的多 tab 栏，挂在 WorkbenchShell 顶部 RailSidebar 右侧。
  - 点 tab → router.push 该 tab path
  - 点 × → tabsStore.closeTab + 自动跳到邻居 tab
  - 首页 tab 不可关
  - 2026-05-21 UI audit Fix 19: tab 多到溢出时显式给出 ‹ › 滚动按钮（之前只有 overflow-x auto，用户看不出还有更多 tab）
-->
<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useTabsStore, type TabItem } from '@/stores/tabs'

const router = useRouter()
const tabsStore = useTabsStore()

const tabs = computed(() => tabsStore.tabs)
const activeId = computed(() => tabsStore.activeId)

const ICONS: Record<string, string> = {
  home: '<path d="M3 11.5 12 4l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>',
  apps: '<path d="M3 5h7v7H3z"/><path d="M14 5h7v7h-7z"/><path d="M3 16h7v5H3z"/><path d="M14 16h7v5h-7z"/>',
  chat: '<path d="M21 12a8 8 0 0 1-11.9 7L4 21l1.6-4.4A8 8 0 1 1 21 12z"/>',
  code: '<path d="m9 17-5-5 5-5"/><path d="m15 7 5 5-5 5"/><path d="m13 5-2 14"/>',
  sparkles: '<path d="M9 4 10 7 13 8 10 9 9 12 8 9 5 8 8 7z"/><path d="M17 3l.7 2.3L20 6l-2.3.7L17 9l-.7-2.3L14 6l2.3-.7z"/><path d="M16 15l1 2.5 2.5 1-2.5 1-1 2.5-1-2.5-2.5-1 2.5-1z"/>',
  store: '<path d="M3 9 5 4h14l2 5"/><path d="M4 9v10a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V9"/><path d="M3 9h18"/>',
  database: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5"/><path d="M3 12a9 3 0 0 0 18 0"/>',
  spark: '<path d="M12 3 14 9l6 2-6 2-2 6-2-6-6-2 6-2z"/>',
  shield: '<path d="M12 3 19 6v5c0 4.5-2.8 8.5-7 10-4.2-1.5-7-5.5-7-10V6z"/><path d="m9.5 12 1.8 1.8L15 10"/>',
  app: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
}

function renderIcon(name: string): string {
  const inner = ICONS[name] ?? ICONS.app
  return `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`
}

function activate(tab: TabItem) {
  tabsStore.setActive(tab.id)
  router.push(tab.path)
}

// 2026-05-22 Phase 4 #4: 浏览器原生 tab 一致 — cmd/ctrl/middle click 让浏览器开新 chrome tab
// 普通 click 走 SPA 内部切换. 用 router.resolve 把 path 拼成完整 URL 让 href 有效.
function buildHref(path: string): string {
  try {
    return router.resolve(path).href
  } catch {
    return path
  }
}

function onTabClick(e: MouseEvent, tab: TabItem) {
  // modifier key 或 middle click (button=1) → 不阻止默认, 让浏览器原生开新 tab
  if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) {
    return  // 浏览器会按 href 在新 tab 打开
  }
  // 普通 left click → SPA 内部切换
  e.preventDefault()
  activate(tab)
}

function close(e: MouseEvent, tab: TabItem) {
  e.preventDefault()
  e.stopPropagation()
  const next = tabsStore.closeTab(tab.id)
  if (next) router.push(next.path)
}

// ─────────────────────────────────────────────
// 2026-05-21 UI audit Fix 19: 溢出滚动按钮
// 监听 scrollLeft / scrollWidth / clientWidth：决定左右按钮是否显示
// ─────────────────────────────────────────────
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
  // 留 1px 容差避免亚像素抖动
  canScrollLeft.value = el.scrollLeft > 1
  canScrollRight.value = el.scrollLeft + el.clientWidth < el.scrollWidth - 1
}

function scrollByAmount(delta: number) {
  const el = scrollerRef.value
  if (!el) return
  el.scrollBy({ left: delta, behavior: 'smooth' })
  // smooth scroll 完成后再更新一次状态（200ms 足够覆盖 chrome smooth scroll）
  setTimeout(updateScrollState, 220)
}

let _resizeObs: ResizeObserver | null = null
onMounted(() => {
  nextTick(() => {
    updateScrollState()
    if (typeof ResizeObserver !== 'undefined' && scrollerRef.value) {
      _resizeObs = new ResizeObserver(updateScrollState)
      _resizeObs.observe(scrollerRef.value)
      // 内部 tab 数量变化也算 resize 触发
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

// tab 增删时 dom 重建，需要在 nextTick 后再观察新 child
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
  <div class="tab-strip-wrap" v-if="tabs.length">
    <button
      v-if="canScrollLeft"
      type="button"
      class="tab-scroll-btn left"
      aria-label="向左滚动 tab"
      @click="scrollByAmount(-220)"
    >‹</button>
    <div
      ref="scrollerRef"
      class="tab-strip"
      @scroll="updateScrollState"
    >
      <!-- 2026-05-22 Phase 4 #4: button → <a> 让浏览器原生处理 cmd+click / 右键"在新标签中打开" -->
      <a
        v-for="tab in tabs"
        :key="tab.id"
        :href="buildHref(tab.path)"
        class="tab"
        :class="{ active: tab.id === activeId }"
        :title="`${tab.label} (Cmd+点 在新标签中打开)`"
        @click="onTabClick($event, tab)"
        @auxclick="onTabClick($event, tab)"
      >
        <span class="tab-icon" v-html="renderIcon(tab.icon)" />
        <span class="tab-label">{{ tab.label }}</span>
        <button
          v-if="tab.closable"
          type="button"
          class="tab-close"
          :aria-label="`关闭 ${tab.label}`"
          @click="close($event, tab)"
        >×</button>
      </a>
    </div>
    <button
      v-if="canScrollRight"
      type="button"
      class="tab-scroll-btn right"
      aria-label="向右滚动 tab"
      @click="scrollByAmount(220)"
    >›</button>
  </div>
</template>

<style scoped>
/* 外壳：position relative 让滚动按钮浮在 tab 之上 */
.tab-strip-wrap {
  position: relative;
  display: flex;
  align-items: center;
  background: var(--surface-2);
  border-bottom: 1px solid var(--line);
  flex-shrink: 0;
  min-height: 36px;
}

.tab-strip {
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
.tab-strip::-webkit-scrollbar { height: 4px; }
.tab-strip::-webkit-scrollbar-thumb { background: var(--line); border-radius: 2px; }

/* 2026-05-21 UI audit Fix 19: 溢出滚动按钮
   绝对定位浮在 tab strip 两侧，加 gradient 让边缘 tab 看起来"渐隐" */
.tab-scroll-btn {
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
.tab-scroll-btn.left {
  left: 0;
  border-right: 1px solid var(--line);
  background: linear-gradient(to right, var(--surface-2) 60%, transparent);
}
.tab-scroll-btn.right {
  right: 0;
  border-left: 1px solid var(--line);
  background: linear-gradient(to left, var(--surface-2) 60%, transparent);
}
.tab-scroll-btn:hover {
  color: var(--brand);
  background: var(--surface);
}
.tab-scroll-btn:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: -2px;
}

.tab {
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
  font-family: inherit;
  font-size: 12.5px;
  font-weight: var(--fw-medium, 500);
  cursor: pointer;
  transition: background 0.12s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.12s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
  margin-bottom: -1px;
  flex-shrink: 0;
}
.tab:hover {
  background: var(--surface);
  color: var(--text);
}
.tab.active {
  background: var(--surface);
  color: var(--brand);
  border-color: var(--line);
  font-weight: var(--fw-semibold, 600);
}
.tab:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: -2px;
}

.tab-icon {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  color: currentColor;
}

.tab-label {
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.tab-close {
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
.tab-close:hover {
  background: var(--surface-3, var(--surface-2));
  color: var(--text);
}
</style>
