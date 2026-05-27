<!-- AppConfigTopTabs.vue — Claude Design v3 顶部 4 tab.

  2026-05-26: 替换原 SectionNav (vertical 200px sidebar) 为 horizontal 顶部 tab strip.
  2026-05-27 Q2: 顶部 3 → 4 tab — 加 "数据源".

  4 tab: 设计 / 数据源 / 权限 / 日志

  - 设计 (design):     菜单/表单/列表/流程/数据 schema — 应用 UI + 数据结构
  - 数据源 (datasource): 应用关联的数据库连接 (MySQL/PG/Mongo etc.)
  - 权限 (perm):       角色/字段权限/菜单可见性 — 访问控制
  - 日志 (log):        操作日志 + 部署历史 — 审计

  Props:
    current-tab: 'design' | 'datasource' | 'perm' | 'log'

  Emit:
    switch-tab(tab: string)

  视觉: 跟 supperagent design 截图对齐 — 淡蓝下划线 + 选中色 #1f72d4 系.
-->
<template>
  <nav class="actt" role="tablist" aria-label="应用配置分类">
    <button
      v-for="tab in TABS"
      :key="tab.code"
      class="actt-tab"
      :class="{ active: currentTab === tab.code }"
      role="tab"
      :aria-selected="currentTab === tab.code"
      :aria-current="currentTab === tab.code ? 'page' : undefined"
      @click="onTabClick(tab.code)"
    >
      <span class="actt-tab-icon" v-html="tab.icon" aria-hidden="true"></span>
      <span class="actt-tab-label">{{ tab.label }}</span>
    </button>
  </nav>
</template>

<script setup lang="ts">
// N1 (2026-05-27): 顶部 tab 5 → 3 (设计/权限/日志).
// 删 '数据' (跟设计 sub '数据 schema' 撞车) + '流程' (跟设计 sub '流程设计' 撞).
// 现 model/process 编辑全归"设计 tab + 选菜单 + sub". 跨菜单 list view 用 ConfigAssistant 对话.
//
// Q2 (2026-05-27): 3 → 4 tab — 加 "数据源". 跟 model schema (设计/数据 sub) 不同,
// 数据源是 connection 维度 (host/port/db/credentials), 应用层只读看用了哪些数据源.
type TabCode = 'design' | 'datasource' | 'perm' | 'log'

const TABS: Array<{ code: TabCode; label: string; icon: string }> = [
  {
    code: 'design',
    label: '功能',
    // pencil/sparkle SVG inline (avoid extra deps)
    icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 19l7-7 3 3-7 7-3-3z"/><path d="M18 13l-1.5-7.5L2 2l3.5 14.5L13 18l5-5z"/><circle cx="6" cy="6" r="2"/></svg>',
  },
  {
    code: 'datasource',
    label: '数据源',
    // database cylinder SVG
    icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><ellipse cx="12" cy="6" rx="9" ry="3"/><path d="M3 6v6c0 1.66 4.03 3 9 3s9-1.34 9-3V6"/><path d="M3 12v6c0 1.66 4.03 3 9 3s9-1.34 9-3v-6"/></svg>',
  },
  {
    code: 'perm',
    label: '权限',
    icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="7" r="4"/><path d="M5 21v-2a7 7 0 0 1 14 0v2"/></svg>',
  },
  {
    code: 'log',
    label: '日志',
    icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
  },
]

defineProps<{
  currentTab: string
}>()

const emit = defineEmits<{
  (e: 'switch-tab', tab: TabCode): void
}>()

function onTabClick(code: TabCode) {
  emit('switch-tab', code)
}

defineExpose({ TABS })
</script>

<style scoped>
.actt {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 0 20px;
  height: 48px;
  background: var(--surface);
  border-bottom: 1px solid var(--line);
  flex-shrink: 0;
  font-family: var(--font-sans);
}

.actt-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 36px;
  padding: 0 16px;
  background: transparent;
  border: none;
  border-radius: 8px;
  color: var(--text-3);
  font-size: 14px;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  position: relative;
  transition: color 0.15s, background 0.15s;
  white-space: nowrap;
  outline: none;
}

.actt-tab:hover {
  color: var(--text);
  background: var(--surface-2);
}

.actt-tab:focus-visible {
  outline: 2px solid var(--brand);
  outline-offset: -2px;
}

.actt-tab.active {
  color: var(--brand);
  background: var(--brand-soft);
  font-weight: 600;
}

.actt-tab-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.actt-tab-icon :deep(svg) {
  display: block;
}

.actt-tab-label {
  display: inline-block;
}
</style>
