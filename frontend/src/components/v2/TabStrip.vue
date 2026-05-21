<!-- frontend/src/components/v2/TabStrip.vue
  浏览器风格的多 tab 栏，挂在 WorkbenchShell 顶部 RailSidebar 右侧。
  - 点 tab → router.push 该 tab path
  - 点 × → tabsStore.closeTab + 自动跳到邻居 tab
  - 首页 tab 不可关
-->
<script setup lang="ts">
import { computed } from 'vue'
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

function close(e: MouseEvent, tab: TabItem) {
  e.stopPropagation()
  const next = tabsStore.closeTab(tab.id)
  if (next) router.push(next.path)
}
</script>

<template>
  <div class="tab-strip" v-if="tabs.length">
    <button
      v-for="tab in tabs"
      :key="tab.id"
      type="button"
      class="tab"
      :class="{ active: tab.id === activeId }"
      :title="tab.label"
      @click="activate(tab)"
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
    </button>
  </div>
</template>

<style scoped>
.tab-strip {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  overflow-x: auto;
  scrollbar-width: thin;
  padding: 4px 8px 0;
  background: var(--surface-2);
  border-bottom: 1px solid var(--line);
  flex-shrink: 0;  /* ChatPage 等 flex 布局父容器会压缩它，强制不压 */
  min-height: 36px;
}
.tab-strip::-webkit-scrollbar { height: 4px; }
.tab-strip::-webkit-scrollbar-thumb { background: var(--line); border-radius: 2px; }

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
