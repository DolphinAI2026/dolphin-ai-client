<template>
  <aside class="session-sidebar" :class="{ collapsed: isCollapsed }">
    <template v-if="!isCollapsed">
      <div class="sidebar-head">
        <div class="brand">
          <span class="brand-dot" :style="brandDotStyle"></span>
          {{ moduleName }}
        </div>
        <button
          v-if="collapsible"
          class="head-toggle"
          @click="setCollapsed(true)"
          title="收起会话列表"
        >«</button>
      </div>

      <!-- 新建按钮：dropdown 或 普通按钮（永远铺满 sidebar 宽度） -->
      <div class="new-btn-wrap">
        <el-dropdown
          v-if="newOptions && newOptions.length"
          trigger="click"
          placement="bottom-start"
          class="new-dropdown"
          @command="onCreateWithOption"
        >
          <button class="new-btn">
            <span>{{ newLabel || '+ 新会话' }}</span>
            <span class="new-btn-caret">▾</span>
          </button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item v-for="opt in newOptions" :key="opt.command" :command="opt.command">
                <div class="new-option">
                  <div class="new-option-title">
                    <el-icon v-if="opt.icon" class="opt-icon"><component :is="opt.icon" /></el-icon>
                    <span>{{ opt.title }}</span>
                  </div>
                  <div v-if="opt.hint" class="new-option-hint">{{ opt.hint }}</div>
                </div>
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <button v-else class="new-btn" @click="$emit('create')">
          <span>{{ newLabel || '+ 新会话' }}</span>
        </button>
      </div>

      <!-- 模式 tabs（可选） -->
      <div v-if="tabs && tabs.length" class="filter-tabs">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          class="filter-tab"
          :class="{ active: activeTabKey === tab.key }"
          @click="$emit('tab-change', tab.key)"
          :title="tab.title || tab.label"
        >
          <el-icon v-if="tab.icon" class="filter-tab-icon"><component :is="tab.icon" /></el-icon>
          <span>{{ tab.label }}</span>
          <span v-if="tab.count !== undefined" class="filter-tab-count">{{ tab.count }}</span>
        </button>
      </div>

      <!-- 会话列表 -->
      <div class="session-list">
        <slot name="list-prefix" />
        <div
          v-for="s in sessions"
          :key="s.id"
          class="session-item"
          :class="{ active: activeId === s.id }"
          @click="$emit('select', s.id)"
          :title="s.title + (s.meta ? ' — ' + s.meta : '')"
        >
          <el-icon
            v-if="s.badgeIcon"
            class="session-badge"
            :class="`tone-${s.badgeTone || 'default'}`"
            :title="s.badgeLabel"
          >
            <component :is="s.badgeIcon" />
          </el-icon>
          <span class="session-name">{{ s.title }}</span>
          <span v-if="s.meta" class="session-meta">{{ s.meta }}</span>
          <button
            v-if="enableRename !== false"
            class="session-menu-btn"
            @click.stop="$emit('rename', s)"
            title="重命名"
          >✎</button>
          <button
            v-if="enableDelete !== false"
            class="session-menu-btn danger"
            @click.stop="$emit('delete', s)"
            title="删除"
          >×</button>
        </div>
        <div v-if="sessions.length === 0" class="empty-hint">
          {{ emptyHint || '还没有会话，点上面新建一个' }}
        </div>
      </div>

      <div v-if="backRoute" class="sidebar-foot">
        <button class="back-btn" @click="onBack">← {{ backLabel || '返回' }}</button>
      </div>
    </template>

    <template v-else>
      <div class="sidebar-rail">
        <button
          class="rail-btn"
          @click="setCollapsed(false)"
          title="展开会话列表"
        >»</button>
        <button
          class="rail-btn"
          @click="onQuickCreate"
          :title="newLabel || '+ 新会话'"
        >+</button>
        <div class="rail-spacer"></div>
        <button
          v-if="backRoute"
          class="rail-btn"
          @click="onBack"
          :title="backLabel || '返回'"
        >←</button>
      </div>
    </template>
  </aside>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

export interface SessionItem {
  id: string | number
  title: string
  badgeIcon?: any
  badgeLabel?: string
  badgeTone?: 'cowork' | 'chat' | 'success' | 'danger' | 'default' | string
  meta?: string
}

export interface SessionTab {
  key: string
  label: string
  count?: number
  icon?: any
  title?: string
}

export interface NewSessionOption {
  command: string
  title: string
  hint?: string
  icon?: any
}

const props = withDefaults(defineProps<{
  moduleName: string
  brandColor?: string
  sessions: SessionItem[]
  activeId?: string | number | null
  tabs?: SessionTab[]
  activeTabKey?: string
  newOptions?: NewSessionOption[]
  newLabel?: string
  backRoute?: string
  backLabel?: string
  collapseKey?: string
  collapsible?: boolean
  enableRename?: boolean
  enableDelete?: boolean
  emptyHint?: string
}>(), {
  collapsible: true,
  enableRename: true,
  enableDelete: true,
})

const emit = defineEmits<{
  (e: 'select', id: string | number): void
  (e: 'create'): void
  (e: 'create-with-option', command: string): void
  (e: 'rename', session: SessionItem): void
  (e: 'delete', session: SessionItem): void
  (e: 'tab-change', key: string): void
  (e: 'collapse-change', collapsed: boolean): void
}>()

const router = useRouter()

const collapsible = computed(() => props.collapsible !== false)
const storageKey = computed(() => props.collapseKey || 'session-sidebar:collapsed')
const isCollapsed = ref<boolean>(
  collapsible.value && typeof localStorage !== 'undefined'
    ? localStorage.getItem(storageKey.value) === '1'
    : false
)

watch(isCollapsed, (v) => {
  if (!collapsible.value) return
  try {
    localStorage.setItem(storageKey.value, v ? '1' : '0')
  } catch {}
  emit('collapse-change', v)
})

function setCollapsed(v: boolean) {
  if (!collapsible.value) return
  isCollapsed.value = v
}

const brandDotStyle = computed(() => {
  if (!props.brandColor) return undefined
  return { background: props.brandColor }
})

function onCreateWithOption(command: string | number | object) {
  emit('create-with-option', String(command))
}

function onQuickCreate() {
  if (props.newOptions && props.newOptions.length) {
    emit('create-with-option', props.newOptions[0].command)
  } else {
    emit('create')
  }
}

function onBack() {
  if (!props.backRoute) return
  router.push(props.backRoute).catch(() => {})
}
</script>

<style scoped>
.session-sidebar {
  width: 240px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--t-bg-elevated, #fff);
  border-right: 1px solid var(--t-border-soft, rgba(116, 128, 171, 0.16));
  min-height: 0;
  overflow: hidden;
}
.session-sidebar.collapsed {
  width: 44px;
}

.sidebar-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px 8px;
}
.brand {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 700;
  color: var(--t-text-primary);
}
.brand-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: #f59e0b;
  display: inline-block;
}
.head-toggle {
  border: none;
  background: transparent;
  color: var(--t-text-muted);
  cursor: pointer;
  font-size: 14px;
  padding: 2px 6px;
  border-radius: 6px;
}
.head-toggle:hover {
  background: var(--t-bg-soft, rgba(99, 102, 241, 0.08));
  color: var(--t-text-primary);
}

/* el-dropdown 默认 inline-block，强制 100%；按钮也铺满 */
.new-btn-wrap {
  margin: 0 12px 8px;
}
.new-btn-wrap :deep(.el-dropdown) {
  display: block;
  width: 100%;
}
.new-btn {
  width: 100%;
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  border: 1px solid var(--t-border-soft, rgba(116, 128, 171, 0.18));
  border-radius: 10px;
  background: var(--t-bg-base, #fff);
  color: var(--t-text-primary);
  font-size: 12px;
  font-weight: 650;
  cursor: pointer;
  transition: background 0.16s, border-color 0.16s;
}
.new-btn:hover {
  border-color: rgba(99, 102, 241, 0.32);
  background: rgba(99, 102, 241, 0.07);
  color: #4f5fe0;
}
.new-btn-caret {
  font-size: 10px;
  opacity: 0.7;
}

.new-option {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 200px;
}
.new-option-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 650;
  color: var(--t-text-primary);
}
.new-option-hint {
  font-size: 11px;
  color: var(--t-text-muted);
  padding-left: 22px;
}
.opt-icon {
  font-size: 14px;
}

/* 三个 tab 在 240px 宽 sidebar 里平分一行，绝不换行 */
.filter-tabs {
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: 1fr;
  gap: 3px;
  padding: 0 12px 8px;
}
.filter-tab {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 3px;
  min-width: 0;
  height: 24px;
  padding: 0 4px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: var(--t-text-muted);
  font-size: 10.5px;
  font-weight: 650;
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
}
.filter-tab > span:not(.filter-tab-count) {
  overflow: hidden;
  text-overflow: ellipsis;
}
.filter-tab.active {
  border-color: rgba(99, 102, 241, 0.22);
  background: rgba(99, 102, 241, 0.1);
  color: #4f5fe0;
}
.filter-tab-icon {
  font-size: 11px;
  flex-shrink: 0;
}
.filter-tab-count {
  flex-shrink: 0;
  min-width: 14px;
  height: 13px;
  padding: 0 4px;
  border-radius: 999px;
  background: rgba(99, 102, 241, 0.12);
  color: inherit;
  line-height: 13px;
  text-align: center;
  font-size: 9.5px;
  font-weight: 700;
}

.session-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 4px 8px 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.session-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  color: var(--t-text-secondary);
  font-size: 13px;
  transition: background 0.14s, color 0.14s;
  position: relative;
}
.session-item:hover {
  background: rgba(99, 102, 241, 0.07);
  color: var(--t-text-primary);
}
.session-item.active {
  background: rgba(99, 102, 241, 0.13);
  color: #4f5fe0;
  font-weight: 650;
}
.session-badge {
  font-size: 12px;
  flex-shrink: 0;
}
.session-badge.tone-cowork { color: #f59e0b; }
.session-badge.tone-chat { color: #6366f1; }
.session-badge.tone-success { color: #16a34a; }
.session-badge.tone-danger { color: #dc2626; }

.session-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.session-meta {
  font-size: 10px;
  color: var(--t-text-muted);
  flex-shrink: 0;
}
.session-menu-btn {
  visibility: hidden;
  width: 22px;
  height: 22px;
  border: none;
  background: transparent;
  border-radius: 6px;
  color: var(--t-text-muted);
  cursor: pointer;
  font-size: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.session-item:hover .session-menu-btn {
  visibility: visible;
}
.session-menu-btn:hover {
  background: rgba(99, 102, 241, 0.12);
  color: var(--t-text-primary);
}
.session-menu-btn.danger:hover {
  background: rgba(239, 68, 68, 0.12);
  color: #dc2626;
}

.empty-hint {
  padding: 24px 12px;
  font-size: 12px;
  color: var(--t-text-muted);
  text-align: center;
  line-height: 1.5;
}

.sidebar-foot {
  padding: 8px 12px 10px;
  border-top: 1px solid var(--t-border-soft, rgba(116, 128, 171, 0.12));
}
.back-btn {
  width: 100%;
  height: 30px;
  border: none;
  background: transparent;
  color: var(--t-text-muted);
  font-size: 12px;
  cursor: pointer;
  border-radius: 8px;
  text-align: left;
  padding: 0 8px;
}
.back-btn:hover {
  background: rgba(99, 102, 241, 0.07);
  color: #4f5fe0;
}

.sidebar-rail {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 10px 4px;
  gap: 6px;
  flex: 1;
}
.rail-btn {
  width: 32px;
  height: 32px;
  border: none;
  background: transparent;
  border-radius: 8px;
  color: var(--t-text-muted);
  cursor: pointer;
  font-size: 14px;
}
.rail-btn:hover {
  background: rgba(99, 102, 241, 0.07);
  color: #4f5fe0;
}
.rail-spacer {
  flex: 1;
}

/* Dark theme */
:global(html[data-theme="dark"]) .session-sidebar {
  background: rgba(15, 18, 25, 0.96);
  border-right-color: rgba(148, 163, 184, 0.16);
}
:global(html[data-theme="dark"]) .session-sidebar .new-btn {
  background: rgba(20, 24, 33, 0.9);
  border-color: rgba(148, 163, 184, 0.18);
  color: #e7edf8;
}
:global(html[data-theme="dark"]) .session-sidebar .new-btn:hover {
  background: rgba(99, 102, 241, 0.18);
  border-color: rgba(124, 140, 255, 0.42);
  color: #c7d2ff;
}
:global(html[data-theme="dark"]) .session-sidebar .session-item:hover {
  background: rgba(99, 102, 241, 0.16);
  color: #e7edf8;
}
:global(html[data-theme="dark"]) .session-sidebar .session-item.active {
  background: rgba(99, 102, 241, 0.22);
  color: #c7d2ff;
}
:global(html[data-theme="dark"]) .session-sidebar .empty-hint,
:global(html[data-theme="dark"]) .session-sidebar .session-meta,
:global(html[data-theme="dark"]) .session-sidebar .session-menu-btn,
:global(html[data-theme="dark"]) .session-sidebar .filter-tab,
:global(html[data-theme="dark"]) .session-sidebar .back-btn,
:global(html[data-theme="dark"]) .session-sidebar .head-toggle,
:global(html[data-theme="dark"]) .session-sidebar .rail-btn {
  color: rgba(203, 213, 225, 0.7);
}
:global(html[data-theme="dark"]) .session-sidebar .filter-tab.active {
  background: rgba(124, 140, 255, 0.18);
  border-color: rgba(124, 140, 255, 0.34);
  color: #c7d2ff;
}
:global(html[data-theme="dark"]) .session-sidebar .brand {
  color: rgba(248, 250, 252, 0.94);
}
</style>
