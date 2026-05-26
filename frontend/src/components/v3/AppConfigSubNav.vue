<!-- AppConfigSubNav.vue — Claude Design v3 左侧 sub-tab 导航.

  2026-05-26: 配 AppConfigTopTabs 一起用 — 顶部选 top tab 后, 左侧显该 tab 下的
  子分类列表 (像 design 截图的"页面/组件/数据").

  5 top tab 对应的 sub-tabs:
    - design: 菜单/表单/列表
    - data:   模型/字典
    - logic:  流程/业务事件
    - perm:   角色/字段权限/菜单可见性
    - log:    操作日志/部署历史

  Props:
    top-tab: 'design'|'data'|'logic'|'perm'|'log'
    current-sub: string

  Emit:
    switch-sub(subCode: string)
-->
<template>
  <nav class="acsn" role="navigation" aria-label="子分类">
    <ul role="tablist" class="acsn-list">
      <li v-for="sub in currentSubTabs" :key="sub.code" class="acsn-li">
        <button
          type="button"
          role="tab"
          class="acsn-item"
          :class="{ active: currentSub === sub.code }"
          :aria-selected="currentSub === sub.code"
          :aria-current="currentSub === sub.code ? 'page' : undefined"
          @click="onSubClick(sub.code)"
        >
          <span class="acsn-item-icon" v-html="sub.icon" aria-hidden="true"></span>
          <span class="acsn-item-label">{{ sub.label }}</span>
        </button>
      </li>
    </ul>
  </nav>
</template>

<script setup lang="ts">
import { computed } from 'vue'

type TopTab = 'design' | 'data' | 'logic' | 'perm' | 'log'

interface SubTab {
  code: string
  label: string
  icon: string
}

const SUB_TABS_MAP: Record<TopTab, SubTab[]> = {
  design: [
    {
      code: 'menus', label: '菜单',
      icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>',
    },
    {
      code: 'forms', label: '表单',
      icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="9" y1="9" x2="15" y2="9"/><line x1="9" y1="13" x2="15" y2="13"/><line x1="9" y1="17" x2="13" y2="17"/></svg>',
    },
    {
      code: 'lists', label: '列表',
      icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="3" y1="15" x2="21" y2="15"/></svg>',
    },
  ],
  data: [
    {
      code: 'models', label: '数据模型',
      icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5"/></svg>',
    },
    {
      code: 'dicts', label: '字典',
      icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>',
    },
  ],
  logic: [
    {
      code: 'processes', label: '流程',
      icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="6" height="6"/><rect x="15" y="3" width="6" height="6"/><rect x="9" y="15" width="6" height="6"/></svg>',
    },
    {
      code: 'events', label: '业务事件',
      icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>',
    },
  ],
  perm: [
    {
      code: 'roles', label: '角色',
      icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="9" cy="7" r="4"/><path d="M3 21v-2a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v2"/><circle cx="17" cy="7" r="3" opacity="0.5"/></svg>',
    },
    {
      code: 'field_perm', label: '字段权限',
      icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>',
    },
    {
      code: 'menu_vis', label: '菜单可见性',
      icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>',
    },
  ],
  log: [
    {
      code: 'op_log', label: '操作日志',
      icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>',
    },
    {
      code: 'deploy_history', label: '部署历史',
      icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/></svg>',
    },
  ],
}

const props = defineProps<{
  topTab: string
  currentSub: string
}>()

const emit = defineEmits<{
  (e: 'switch-sub', code: string): void
}>()

const currentSubTabs = computed(() => SUB_TABS_MAP[(props.topTab as TopTab)] || [])

function onSubClick(code: string) {
  emit('switch-sub', code)
}

defineExpose({ SUB_TABS_MAP })
</script>

<style scoped>
.acsn {
  width: 200px;
  flex-shrink: 0;
  background: var(--surface);
  border-right: 1px solid var(--line);
  padding: 8px 0;
  overflow-y: auto;
  font-family: var(--font-sans);
}

.acsn-list {
  list-style: none;
  padding: 0;
  margin: 0;
}

.acsn-li {
  margin: 0;
}

.acsn-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: calc(100% - 16px);
  margin: 1px 8px;
  height: 36px;
  padding: 0 12px;
  background: transparent;
  border: none;
  border-radius: 6px;
  color: var(--text-2);
  font-size: 14px;
  font-weight: 500;
  font-family: inherit;
  text-align: left;
  cursor: pointer;
  transition: background 0.12s, color 0.12s;
  outline: none;
}

.acsn-item:hover {
  background: var(--surface-2);
  color: var(--text);
}

.acsn-item:focus-visible {
  outline: 2px solid var(--brand);
  outline-offset: -2px;
}

.acsn-item.active {
  background: var(--brand-soft);
  color: var(--brand);
  font-weight: 600;
}

.acsn-item-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: currentColor;
  flex-shrink: 0;
}

.acsn-item-icon :deep(svg) {
  display: block;
}

.acsn-item-label {
  flex: 1;
}
</style>
