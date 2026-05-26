<template>
  <!--
    SectionNav.vue — 应用配置中心左侧 5-section 导航 (SPEC v2 §1.1 / §2 / §7)

    PR2a 范围: 纯 UI 子组件 + demo 验收, 不接 ChatPage / 不接业务逻辑.
    PR2b 会把它嵌入 ChatPage, 并把 "ui / 菜单" sub-tab 的主区域接到现有 ApaasMenuSidebar.

    设计:
    - 5 section (data / ui / logic / permission / extension), 每 section N 个 sub-tab
    - 一级 44px / 二级 32px, brand 色选中态 + 左 3px 竖条 (跟 ApaasMenuSidebar 一致)
    - 全部用 --t-* CSS token, light/dark 自动跟主题
    - 选中态由 props.currentSection / props.currentTab 控制 (受控组件)
  -->
  <aside class="snv" :class="{ collapsed }" role="navigation" aria-label="应用配置区域">
    <div class="snv-head">
      <span class="snv-head-title">应用配置</span>
    </div>

    <ul class="snv-list" role="tree">
      <li
        v-for="section in SECTIONS"
        :key="section.code"
        class="snv-item"
      >
        <!-- 一级 section -->
        <button
          type="button"
          class="snv-section"
          :class="{ selected: section.code === props.currentSection }"
          :aria-expanded="isSectionExpanded(section.code)"
          :title="section.label"
          @click="handleSectionClick(section)"
        >
          <span class="snv-icon" aria-hidden="true">{{ section.icon }}</span>
          <span v-if="!collapsed" class="snv-label">{{ section.label }}</span>
          <span
            v-if="!collapsed && section.tabs.length"
            class="snv-chevron"
            :class="{ open: isSectionExpanded(section.code) }"
            aria-hidden="true"
          >▸</span>
        </button>

        <!-- 二级 sub-tab -->
        <ul
          v-if="!collapsed && isSectionExpanded(section.code) && section.tabs.length"
          class="snv-tabs"
          role="group"
        >
          <li
            v-for="tab in section.tabs"
            :key="tab.code"
            class="snv-tab-item"
          >
            <button
              type="button"
              class="snv-tab"
              :class="{
                selected:
                  section.code === props.currentSection
                  && tab.code === props.currentTab,
              }"
              :title="tab.label"
              @click="handleTabClick(section, tab)"
            >
              <span class="snv-tab-label">{{ tab.label }}</span>
            </button>
          </li>
        </ul>
      </li>
    </ul>

    <div class="snv-foot" v-if="!collapsed">
      <span class="snv-foot-hint">v2 配置中心</span>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'

// ──────────────── 类型 ────────────────
interface SectionTab {
  code: string
  label: string
}
interface Section {
  code: string
  label: string
  icon: string
  tabs: SectionTab[]
}

// ──────────────── 数据 (hardcoded, PR2b 改成 tool_registry 派生) ────────────────
const SECTIONS: Section[] = [
  {
    code: 'data',
    label: '数据',
    icon: '📊',
    tabs: [
      { code: 'models', label: '数据模型' },
      { code: 'dicts', label: '字典' },
    ],
  },
  {
    code: 'ui',
    label: '界面',
    icon: '🎨',
    tabs: [
      { code: 'menus', label: '菜单' },
      { code: 'forms', label: '表单' },
      { code: 'lists', label: '列表' },
    ],
  },
  {
    code: 'logic',
    label: '逻辑',
    icon: '⚙️',
    tabs: [
      { code: 'processes', label: '流程' },
      { code: 'events', label: '业务事件' },
    ],
  },
  {
    code: 'permission',
    label: '权限',
    icon: '🔒',
    tabs: [
      { code: 'roles', label: '角色' },
      { code: 'field_perm', label: '字段权限' },
      { code: 'menu_vis', label: '菜单可见性' },
    ],
  },
  {
    code: 'extension',
    label: '扩展',
    icon: '🧩',
    tabs: [
      { code: 'dev_kit', label: '自开发组件' },
      { code: 'code_node', label: '代码节点' },
    ],
  },
]

// ──────────────── Props / Emits ────────────────
const props = withDefaults(
  defineProps<{
    currentSection?: string
    currentTab?: string
    /** P0 不实现折叠 UI, 留 prop 占位 — true 时只显 icon, 无 label / 无二级 */
    collapsed?: boolean
  }>(),
  {
    currentSection: 'data',
    currentTab: '',
    collapsed: false,
  },
)

const emit = defineEmits<{
  (e: 'switch-section', section: string, tab?: string): void
}>()

// ──────────────── 内部展开状态 ────────────────
// 默认: 当前 currentSection 是展开的; 其他可选展开 (多个互不影响, 不强制单展开)
const expandedSections = ref<Set<string>>(new Set([props.currentSection]))

function isSectionExpanded(code: string): boolean {
  return expandedSections.value.has(code)
}

// 外部 currentSection 变 → 自动展开它 (但不收别的)
watch(
  () => props.currentSection,
  (newCode) => {
    if (newCode && !expandedSections.value.has(newCode)) {
      expandedSections.value = new Set([...expandedSections.value, newCode])
    }
  },
)

// ──────────────── 行为 ────────────────
function handleSectionClick(section: Section) {
  const isCurrent = section.code === props.currentSection
  const isExpanded = expandedSections.value.has(section.code)

  if (isCurrent && isExpanded) {
    // 当前 section 已展开 → 折叠 (但不取消选中, 选中态留给父组件 currentSection 控制)
    const next = new Set(expandedSections.value)
    next.delete(section.code)
    expandedSections.value = next
    return
  }

  // 否则: 展开 + 通知父切 section, 默认进第一个 tab
  if (!isExpanded) {
    expandedSections.value = new Set([...expandedSections.value, section.code])
  }
  const defaultTab = section.tabs[0]?.code
  emit('switch-section', section.code, defaultTab)
}

function handleTabClick(section: Section, tab: SectionTab) {
  // 点 tab: 如果当前不是这个 section, 先切 section
  emit('switch-section', section.code, tab.code)
}

// ──────────────── 暴露 (PR2b 测试用) ────────────────
defineExpose({
  SECTIONS,
  expandedSections,
})
</script>

<style scoped>
/* 主题策略: 全部 var(--t-*) token + 裸跑 fallback, 跟 ApaasMenuSidebar 一致.
   命名空间: .snv / .snv-* 避免冲突. */

/* ───── 容器 ───── */
.snv {
  width: 200px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--t-bg-panel, #ffffff);
  border-right: 1px solid var(--t-border-subtle, rgba(99, 102, 241, 0.08));
  min-height: 0;
  overflow: hidden;
  transition: width 0.2s ease;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC',
               'Hiragino Sans GB', sans-serif;
}
.snv.collapsed {
  width: 56px;
}

/* ───── 头部 ───── */
.snv-head {
  display: flex;
  align-items: center;
  height: 40px;
  padding: 0 14px;
  border-bottom: 1px solid var(--t-border-subtle, rgba(99, 102, 241, 0.08));
  background: var(--t-brand-subtle, rgba(79, 110, 247, 0.05));
  flex-shrink: 0;
}
.snv-head-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--t-text-primary, #1e293b);
  letter-spacing: 0.4px;
}

/* ───── 列表 ───── */
.snv-list {
  flex: 1;
  list-style: none;
  margin: 0;
  padding: 6px 4px;
  overflow-y: auto;
  min-height: 0;
}
.snv-list::-webkit-scrollbar { width: 6px; }
.snv-list::-webkit-scrollbar-track { background: transparent; }
.snv-list::-webkit-scrollbar-thumb {
  background: var(--t-border-strong, rgba(99, 102, 241, 0.15));
  border-radius: 3px;
}
.snv-list::-webkit-scrollbar-thumb:hover {
  background: var(--t-brand, #4f6ef7);
}

.snv-item { list-style: none; margin: 0; padding: 0; }

/* ───── 一级 section 按钮 (高 44px) ───── */
.snv-section {
  all: unset;
  position: relative;
  box-sizing: border-box;
  display: flex;
  align-items: center;
  gap: 10px;
  height: 44px;
  width: 100%;
  padding: 0 10px 0 14px;
  border-radius: 6px;
  cursor: pointer;
  color: var(--t-text-primary, #1e293b);
  font-size: 13px;
  font-weight: 500;
  transition: background 0.12s, color 0.12s, transform 0.08s;
  user-select: none;
}
.snv-section:hover {
  background: var(--t-bg-panel-hover, rgba(99, 102, 241, 0.06));
  color: var(--t-brand, #4f6ef7);
}
.snv-section:active { transform: scale(0.985); }
.snv-section:focus-visible {
  outline: 2px solid var(--t-brand, #4f6ef7);
  outline-offset: -2px;
}

/* 选中态: brand subtle 背景 + brand 字 + 左 3px 竖条 (复刻 ApaasMenuSidebar) */
.snv-section.selected {
  background: var(--t-brand-subtle, rgba(79, 110, 247, 0.1));
  color: var(--t-brand, #4f6ef7);
  font-weight: 600;
}
.snv-section.selected:hover {
  background: var(--t-brand-subtle, rgba(79, 110, 247, 0.14));
  color: var(--t-brand, #4f6ef7);
}
.snv-section.selected::before {
  content: '';
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 3px;
  background: var(--t-brand, #4f6ef7);
  border-radius: 0 2px 2px 0;
}

/* icon: emoji 大字号 */
.snv-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  font-size: 18px;
  line-height: 1;
  flex-shrink: 0;
}

.snv-label {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 折叠箭头 */
.snv-chevron {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  font-size: 10px;
  color: var(--t-text-muted, #94a3b8);
  transition: transform 0.15s ease, color 0.12s;
  flex-shrink: 0;
}
.snv-chevron.open { transform: rotate(90deg); }
.snv-section:hover .snv-chevron,
.snv-section.selected .snv-chevron {
  color: var(--t-brand, #4f6ef7);
}

/* ───── 二级 tab 列表 (高 32px, 缩进 16px) ───── */
.snv-tabs {
  list-style: none;
  margin: 2px 0 6px 0;
  padding: 0;
  position: relative;
}
/* 左侧细线表层级 (复刻 ApaasMenuSidebar .amsn-children::before) */
.snv-tabs::before {
  content: '';
  position: absolute;
  left: 22px;
  top: 0;
  bottom: 2px;
  width: 1px;
  background: var(--t-border-subtle, rgba(99, 102, 241, 0.1));
}

.snv-tab-item { list-style: none; margin: 0; padding: 0; }

.snv-tab {
  all: unset;
  position: relative;
  box-sizing: border-box;
  display: flex;
  align-items: center;
  gap: 8px;
  height: 32px;
  width: 100%;
  padding: 0 10px 0 30px;  /* 缩进 16px + 内边距 14px = 30 */
  border-radius: 6px;
  cursor: pointer;
  color: var(--t-text-secondary, #64748b);
  font-size: 12.5px;
  transition: background 0.12s, color 0.12s, transform 0.08s;
  user-select: none;
}
.snv-tab:hover {
  background: var(--t-bg-panel-hover, rgba(99, 102, 241, 0.06));
  color: var(--t-brand, #4f6ef7);
}
.snv-tab:active { transform: scale(0.985); }
.snv-tab:focus-visible {
  outline: 2px solid var(--t-brand, #4f6ef7);
  outline-offset: -2px;
}

.snv-tab.selected {
  background: var(--t-brand-subtle, rgba(79, 110, 247, 0.1));
  color: var(--t-brand, #4f6ef7);
  font-weight: 600;
}
.snv-tab.selected:hover {
  background: var(--t-brand-subtle, rgba(79, 110, 247, 0.14));
  color: var(--t-brand, #4f6ef7);
}
.snv-tab.selected::before {
  content: '';
  position: absolute;
  left: 16px;
  top: 6px;
  bottom: 6px;
  width: 3px;
  background: var(--t-brand, #4f6ef7);
  border-radius: 0 2px 2px 0;
}

.snv-tab-label {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ───── 底部小字 ───── */
.snv-foot {
  padding: 8px 14px 10px;
  border-top: 1px solid var(--t-border-subtle, rgba(99, 102, 241, 0.08));
  flex-shrink: 0;
}
.snv-foot-hint {
  font-size: 10px;
  color: var(--t-text-muted, #94a3b8);
  letter-spacing: 0.3px;
}

/* ───── 折叠态 (placeholder, P0 不实现完整) ───── */
.snv.collapsed .snv-head { justify-content: center; padding: 0; }
.snv.collapsed .snv-head-title { display: none; }
.snv.collapsed .snv-section {
  justify-content: center;
  padding: 0;
  gap: 0;
}
.snv.collapsed .snv-label,
.snv.collapsed .snv-chevron,
.snv.collapsed .snv-tabs,
.snv.collapsed .snv-foot { display: none; }
</style>
