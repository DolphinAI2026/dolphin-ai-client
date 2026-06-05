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
  <aside
    class="snv"
    :class="{ collapsed }"
    role="navigation"
    aria-label="应用配置分类导航"
  >
    <div class="snv-head">
      <span class="snv-head-title">应用配置</span>
    </div>

    <ul class="snv-list" role="tablist">
      <li
        v-for="section in SECTIONS"
        :key="section.code"
        class="snv-item"
      >
        <!-- 一级 section -->
        <button
          type="button"
          class="snv-section"
          :class="{ selected: section.code === effectiveSection }"
          role="tab"
          :aria-selected="section.code === effectiveSection"
          :aria-current="section.code === effectiveSection ? 'page' : undefined"
          :aria-expanded="isSectionExpanded(section.code)"
          :title="section.label"
          @click="handleSectionClick(section)"
        >
          <AppIcon class="snv-icon" :name="section.icon" :size="18" />
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
          :aria-label="`${section.label} 子分类`"
        >
          <li
            v-for="tab in section.tabs"
            :key="tab.code"
            class="snv-tab-item"
          >
            <button
              type="button"
              class="snv-tab"
              role="tab"
              :class="{
                selected:
                  section.code === effectiveSection
                  && tab.code === props.currentTab,
              }"
              :aria-selected="section.code === effectiveSection && tab.code === props.currentTab"
              :aria-current="
                section.code === effectiveSection && tab.code === props.currentTab
                  ? 'page'
                  : undefined
              "
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
import { computed, ref, watch } from 'vue'
import AppIcon from '@/components/common/AppIcon.vue'

// ──────────────── 类型 ────────────────
/**
 * PR2a reviewer P2 (2026-05-26):
 * - SECTION_CODES = SectionCode 的唯一 source-of-truth (与 SECTIONS 数据同步).
 * - 父组件 / 内部 emit / template 校验全部走这套白名单, 防止打字错 / 上游污染
 *   传入 invalid section code 时 UI 落到空状态.
 */
// 2026-05-26 fix: `<script setup>` 禁 `export const` — 删 export, 通过
// defineExpose 暴露给 template ref. 未来如有跨文件复用需求, 把这俩 const + type
// 移到 `frontend/src/components/v2/section-nav-constants.ts` 单独导出.
const VALID_SECTION_CODES = [
  'data',
  'ui',
  'logic',
  'permission',
  'extension',
] as const
type SectionCode = typeof VALID_SECTION_CODES[number]

/** runtime 白名单判定 — 收紧 narrow 同时 console.warn. */
function isValidSectionCode(code: unknown): code is SectionCode {
  return (
    typeof code === 'string'
    && (VALID_SECTION_CODES as readonly string[]).includes(code)
  )
}

interface SectionTab {
  code: string
  label: string
}
interface Section {
  code: SectionCode
  label: string
  icon: string
  tabs: SectionTab[]
}

// ──────────────── 数据 (hardcoded, PR2b 改成 tool_registry 派生) ────────────────
const SECTIONS: Section[] = [
  {
    code: 'data',
    label: '数据',
    icon: 'bar-chart',
    tabs: [
      { code: 'models', label: '数据模型' },
      { code: 'dicts', label: '字典' },
    ],
  },
  {
    code: 'ui',
    label: '界面',
    icon: 'palette',
    tabs: [
      { code: 'menus', label: '菜单' },
      { code: 'forms', label: '表单' },
      { code: 'lists', label: '列表' },
    ],
  },
  {
    code: 'logic',
    label: '逻辑',
    icon: 'settings',
    tabs: [
      { code: 'processes', label: '流程' },
      { code: 'events', label: '业务事件' },
    ],
  },
  {
    code: 'permission',
    label: '权限',
    icon: 'lock',
    tabs: [
      { code: 'roles', label: '角色' },
      { code: 'field_perm', label: '字段权限' },
      { code: 'menu_vis', label: '菜单可见性' },
    ],
  },
  {
    code: 'extension',
    label: '扩展',
    icon: 'puzzle',
    tabs: [
      { code: 'dev_kit', label: '自开发组件' },
      { code: 'code_node', label: '代码节点' },
    ],
  },
]

/** invalid currentSection prop 时回退到的 section. */
const FALLBACK_SECTION: SectionCode = 'ui'

// ──────────────── Props / Emits ────────────────
/**
 * PR2a reviewer P2: currentSection narrow 到 `SectionCode | string`
 * — 保留 string 兼容老父组件 (未升级到 SectionCode), 但内部一律走 effectiveSection.
 */
const props = withDefaults(
  defineProps<{
    currentSection?: SectionCode | string
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

/**
 * PR2a reviewer P2: emit payload narrow 到 SectionCode 联合类型.
 * 这样父组件 onSwitchSection 可以拿到精确类型, 不再是 string.
 * 内部 emit 前会经过 isValidSectionCode 校验防内部 bug.
 */
const emit = defineEmits<{
  'switch-section': [section: SectionCode, tab?: string]
}>()

// ──────────────── 防御性校验: effectiveSection ────────────────
/**
 * 父组件传 invalid currentSection 时 (打字错 / 上游数据污染 / lpc 攻击注入),
 * UI 不会卡空状态 — fallback 到 FALLBACK_SECTION 并 console.warn.
 * 全 template / 全 handler 一律走 effectiveSection.
 */
const effectiveSection = computed<SectionCode>(() => {
  if (isValidSectionCode(props.currentSection)) {
    return props.currentSection
  }
  // eslint-disable-next-line no-console
  console.warn(
    `[SectionNav] invalid currentSection="${String(props.currentSection)}", `
    + `expected one of [${VALID_SECTION_CODES.join(', ')}]. `
    + `Falling back to "${FALLBACK_SECTION}".`,
  )
  return FALLBACK_SECTION
})

// watch 单独打 warn, 避免每次 render 都触发 console.warn 噪音 (computed 已加 warn, 这里只在变化时再次提醒).
watch(
  () => props.currentSection,
  (newCode) => {
    if (newCode !== undefined && !isValidSectionCode(newCode)) {
      // eslint-disable-next-line no-console
      console.warn(
        `[SectionNav] currentSection prop changed to invalid value "${String(newCode)}". `
        + `Using fallback "${FALLBACK_SECTION}".`,
      )
    }
  },
)

// ──────────────── 内部展开状态 ────────────────
// 默认: 当前 effectiveSection 是展开的; 其他可选展开 (多个互不影响, 不强制单展开)
const expandedSections = ref<Set<SectionCode>>(new Set([effectiveSection.value]))

function isSectionExpanded(code: SectionCode): boolean {
  return expandedSections.value.has(code)
}

// 外部 effectiveSection 变 → 自动展开它 (但不收别的)
watch(
  effectiveSection,
  (newCode) => {
    if (newCode && !expandedSections.value.has(newCode)) {
      expandedSections.value = new Set([...expandedSections.value, newCode])
    }
  },
)

// ──────────────── 行为 ────────────────
/** PR2a reviewer P2: 内部 emit 前再校验一次 section.code, 防内部 bug 传 invalid. */
function safeEmitSwitch(sectionCode: SectionCode, tab?: string) {
  if (!isValidSectionCode(sectionCode)) {
    // eslint-disable-next-line no-console
    console.warn(
      `[SectionNav] refusing to emit switch-section with invalid section="${String(sectionCode)}". `
      + `Expected one of [${VALID_SECTION_CODES.join(', ')}].`,
    )
    return
  }
  emit('switch-section', sectionCode, tab)
}

function handleSectionClick(section: Section) {
  const isCurrent = section.code === effectiveSection.value
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
  safeEmitSwitch(section.code, defaultTab)
}

function handleTabClick(section: Section, tab: SectionTab) {
  // 点 tab: 如果当前不是这个 section, 先切 section
  safeEmitSwitch(section.code, tab.code)
}

// ──────────────── 暴露 (PR2b 测试用) ────────────────
defineExpose({
  SECTIONS,
  VALID_SECTION_CODES,
  expandedSections,
  effectiveSection,
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
