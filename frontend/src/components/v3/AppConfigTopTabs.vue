<!-- AppConfigTopTabs.vue — Claude Design v3 顶部 5 tab.

  2026-05-26: 替换原 SectionNav (vertical 200px sidebar) 为 horizontal 顶部 tab strip.
  5 tab: 设计 / 数据 / 流程 / 权限 / 日志.

  - 设计 (design): 菜单/表单/列表 — 应用 UI 设计
  - 数据 (data):   模型/字典 — 数据结构
  - 流程 (logic):  流程/业务事件 — 业务逻辑
  - 权限 (perm):   角色/字段权限/菜单可见性 — 访问控制
  - 日志 (log):    操作日志 + 部署历史 — 审计

  Props:
    current-tab: 'design' | 'data' | 'logic' | 'perm' | 'log'

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
type TabCode = 'design' | 'data' | 'logic' | 'perm' | 'log'

const TABS: Array<{ code: TabCode; label: string; icon: string }> = [
  {
    code: 'design',
    label: '设计',
    // pencil/sparkle SVG inline (avoid extra deps)
    icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 19l7-7 3 3-7 7-3-3z"/><path d="M18 13l-1.5-7.5L2 2l3.5 14.5L13 18l5-5z"/><circle cx="6" cy="6" r="2"/></svg>',
  },
  {
    code: 'data',
    label: '数据',
    icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5"/><path d="M3 12a9 3 0 0 0 18 0"/></svg>',
  },
  {
    code: 'logic',
    label: '流程',
    icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="6" height="6"/><rect x="15" y="3" width="6" height="6"/><rect x="9" y="15" width="6" height="6"/><path d="M6 9v3a3 3 0 0 0 3 3"/><path d="M18 9v3a3 3 0 0 1-3 3"/></svg>',
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
