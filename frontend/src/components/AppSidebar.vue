<template>
  <aside class="app-sidebar" :class="{ collapsed: collapsed }">
    <!-- 收起态 -->
    <div v-if="collapsed" class="sidebar-collapsed-content">
      <button class="sidebar-toggle-btn" @click="$emit('toggle')" title="展开侧栏">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="7" y1="3" x2="7" y2="21"/><polyline points="13 6 18 12 13 18"/></svg>
      </button>
      <button class="sidebar-icon-btn" @click="$emit('new-app', 'requirements')" title="新建应用">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
      </button>
      <div class="sidebar-collapsed-divider"></div>
      <button
        v-for="app in recentApps"
        :key="app.id"
        class="sidebar-icon-ws"
        :class="{ active: app.id === currentAppId }"
        :title="app.label"
        @click="$emit('select', app)"
      >{{ (app.label || '?')[0] }}</button>
    </div>

    <!-- 展开态 -->
    <template v-else>
      <div class="sidebar-section-header">
        <span class="sidebar-title">应用</span>
        <div class="sidebar-header-actions">
          <button class="sidebar-action-btn sidebar-add-btn" title="新建应用" @click="$emit('new-app', 'requirements')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          </button>
          <button class="sidebar-action-btn" @click="$emit('toggle')" title="收起侧栏">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="17" y1="3" x2="17" y2="21"/><polyline points="11 18 6 12 11 6"/></svg>
          </button>
        </div>
      </div>
      <div class="sidebar-list">
        <template v-for="group in groupedApps" :key="group.key">
          <div class="sidebar-group-header" @click="toggleGroup(group.key)">
            <span class="sidebar-group-label">{{ group.label }}</span>
            <span class="sidebar-group-count">{{ group.items.length }}</span>
            <span class="sidebar-group-arrow" :class="{ collapsed: collapsedGroups.has(group.key) }">▸</span>
          </div>
          <template v-if="!collapsedGroups.has(group.key)">
            <div
              v-for="app in group.items"
              :key="app.id"
              class="sidebar-app-item"
              :class="{ active: app.id === currentAppId }"
              @click="$emit('select', app)"
            >
              <div class="sidebar-app-name">{{ app.label }}</div>
              <div class="sidebar-app-meta">
                <span v-if="app.status === 'updating'" class="sidebar-app-badge gen">更新中</span>
                <span v-else-if="app.status === 'generating'" class="sidebar-app-badge gen">生成中</span>
                <span v-else-if="app.status === 'completed' || app.apaasAppId" class="sidebar-app-badge done">已生成</span>
                <span v-else-if="app.appId" class="sidebar-app-badge draft">草稿</span>
                <span class="sidebar-app-time">{{ app.timeLabel }}</span>
              </div>
            </div>
          </template>
        </template>
        <div v-if="items.length === 0" class="sidebar-empty">暂无应用</div>
      </div>
    </template>
  </aside>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
// Icons replaced with inline SVGs

export interface AppItem {
  id: number | string
  label: string
  status?: string
  timeLabel?: string
  appId?: number       // existingAppId
  conversationId?: number
  apaasAppId?: string
}

const props = defineProps<{
  collapsed: boolean
  items: AppItem[]
  currentAppId?: number | string | null
}>()

defineEmits<{
  toggle: []
  select: [app: AppItem]
  'new-app': [command: string]
}>()

const collapsedGroups = ref(new Set<string>())

const toggleGroup = (key: string) => {
  if (collapsedGroups.value.has(key)) {
    collapsedGroups.value.delete(key)
  } else {
    collapsedGroups.value.add(key)
  }
}

const recentApps = computed(() => props.items.slice(0, 8))

const groupedApps = computed(() => {
  const now = Date.now()
  const day = 86400000
  const week = 7 * day

  const today: AppItem[] = []
  const thisWeek: AppItem[] = []
  const older: AppItem[] = []

  for (const app of props.items) {
    const t = app.timeLabel
    if (!t || t === '刚刚' || t === '今天' || t.includes('分钟')) {
      today.push(app)
    } else if (t === '昨天' || t.includes('天前')) {
      thisWeek.push(app)
    } else {
      older.push(app)
    }
  }

  const groups = []
  if (today.length) groups.push({ key: 'today', label: '今天', items: today })
  if (thisWeek.length) groups.push({ key: 'week', label: '本周', items: thisWeek })
  if (older.length) groups.push({ key: 'older', label: '更早', items: older })
  return groups
})
</script>

<style scoped>
.app-sidebar {
  width: 240px;
  flex-shrink: 0;
  border-right: 1px solid var(--t-border-subtle);
  background: var(--t-bg-panel);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: width 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}
.app-sidebar.collapsed {
  width: 48px;
}

/* Collapsed */
.sidebar-collapsed-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 8px 0;
  gap: 4px;
}
.sidebar-collapsed-divider {
  width: 24px;
  height: 1px;
  background: var(--t-border-subtle);
  margin: 4px 0;
}
.sidebar-toggle-btn,
.sidebar-icon-btn {
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--t-text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s ease;
}
.sidebar-toggle-btn:hover,
.sidebar-icon-btn:hover {
  background: var(--t-bg-elevated);
  color: var(--t-text-primary);
}
.sidebar-icon-ws {
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 6px;
  background: var(--t-bg-elevated);
  color: var(--t-text-secondary);
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s ease;
}
.sidebar-icon-ws.active {
  background: var(--t-brand-primary);
  color: #fff;
}

/* Expanded */
.sidebar-section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 12px 8px;
  flex-shrink: 0;
}
.sidebar-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--t-text-secondary);
}
.sidebar-header-actions {
  display: flex;
  gap: 2px;
}
.sidebar-action-btn {
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--t-text-muted);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s ease;
}
.sidebar-action-btn:hover {
  background: var(--t-bg-elevated);
  color: var(--t-text-primary);
}
.sidebar-list {
  flex: 1;
  overflow-y: auto;
  padding: 0 6px 8px;
}
.sidebar-group-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  font-size: 11px;
  color: var(--t-text-muted);
  cursor: pointer;
  user-select: none;
}
.sidebar-group-label { flex: 1; }
.sidebar-group-count {
  font-size: 10px;
  background: var(--t-bg-elevated);
  padding: 0 5px;
  border-radius: 8px;
  min-width: 16px;
  text-align: center;
}
.sidebar-group-arrow {
  font-size: 10px;
  transition: transform 0.2s;
  transform: rotate(90deg);
}
.sidebar-group-arrow.collapsed {
  transform: rotate(0deg);
}

.sidebar-app-item {
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
  margin-bottom: 2px;
}
.sidebar-app-item:hover {
  background: var(--t-bg-elevated);
}
.sidebar-app-item.active {
  background: var(--t-brand-subtle);
}
.sidebar-app-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--t-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sidebar-app-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 2px;
}
.sidebar-app-badge {
  font-size: 10px;
  padding: 0 5px;
  border-radius: 4px;
  line-height: 16px;
}
.sidebar-app-badge.done {
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
}
.sidebar-app-badge.gen {
  background: rgba(99, 102, 241, 0.15);
  color: #6366f1;
}
.sidebar-app-badge.draft {
  background: rgba(156, 163, 175, 0.15);
  color: #9ca3af;
}
.sidebar-app-time {
  font-size: 11px;
  color: var(--t-text-muted);
}
.sidebar-empty {
  padding: 24px 12px;
  text-align: center;
  font-size: 12px;
  color: var(--t-text-muted);
}

/* Scrollbar */
.sidebar-list::-webkit-scrollbar { width: 4px; }
.sidebar-list::-webkit-scrollbar-thumb { background: var(--t-border-subtle); border-radius: 2px; }
.sidebar-list::-webkit-scrollbar-track { background: transparent; }
</style>
