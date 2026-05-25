<template>
  <aside class="ams" :class="{ collapsed }">
    <!-- 头部 -->
    <header class="ams-head">
      <div v-if="!collapsed" class="ams-head-main">
        <span class="ams-head-title">应用菜单</span>
        <span v-if="flatCount > 0" class="ams-head-badge">{{ flatCount }}</span>
      </div>
      <div class="ams-head-actions">
        <button v-if="!collapsed" class="ams-icon-btn" title="新建分组" @click="openCreateGroupDialog">
          <el-icon><FolderAdd /></el-icon>
        </button>
        <button class="ams-icon-btn" :title="collapsed ? '展开' : '收起'" @click="collapsed = !collapsed">
          <el-icon><component :is="collapsed ? Expand : Fold" /></el-icon>
        </button>
      </div>
    </header>

    <!-- 搜索栏 -->
    <div v-if="!collapsed" class="ams-search-row">
      <el-input
        v-model="search"
        size="small"
        placeholder="搜索菜单"
        clearable
        class="ams-search-input"
      >
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
      </el-input>
      <button class="ams-icon-btn" :class="{ spinning: loading }" title="刷新" @click="reload">
        <el-icon><Refresh /></el-icon>
      </button>
    </div>

    <!-- 列表区 -->
    <div class="ams-body">
      <!-- 加载 -->
      <div v-if="loading" class="ams-state">
        <el-icon class="ams-spin"><Loading /></el-icon>
        <span v-if="!collapsed">加载菜单…</span>
      </div>

      <!-- 错误 -->
      <div v-else-if="error" v-show="!collapsed" class="ams-state ams-state-err">
        <el-icon><Warning /></el-icon>
        <p>{{ error }}</p>
        <el-button size="small" type="primary" @click="reload">重试</el-button>
      </div>

      <!-- 空态 -->
      <div v-else-if="!filteredMenus.length" v-show="!collapsed" class="ams-state ams-state-empty">
        <el-icon><Files /></el-icon>
        <p v-if="search">无匹配「{{ search }}」</p>
        <p v-else>该应用还没有菜单</p>
      </div>

      <!-- 树 -->
      <div v-else class="ams-tree" role="tree">
        <MenuNode
          v-for="m in filteredMenus"
          :key="m.menu_id"
          :menu="m"
          :selected-id="selectedMenuId"
          :collapsed="collapsed"
          :depth="0"
          :expanded-groups="expandedGroups"
          :group-options="groupOptions"
          @select="handleSelect"
          @toggle-group="toggleGroup"
          @move-to-parent="moveToParent"
        />
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, h, defineComponent, type PropType } from 'vue'
import { ElIcon, ElInput, ElButton, ElMessage, ElMessageBox, ElDropdown, ElDropdownMenu, ElDropdownItem } from 'element-plus'
import {
  Search, Refresh, Loading, Warning, Files, Expand, Fold,
  Folder, FolderOpened, FolderAdd, ArrowRight, ArrowDown, More,
  Tickets, DataAnalysis, Link, Bell, MagicStick, Document, Connection, Menu as MenuIcon,
} from '@element-plus/icons-vue'
import request from '@/utils/request'

interface ApaasMenu {
  menu_id: string
  menu_name: string
  menu_type: string
  menu_display?: string
  form_id?: string | null
  form_code?: string | null
  icon?: string
  depth?: number
  path?: string
  parent_menu_id?: string | null
  is_group?: boolean
  dashboard_id?: string | null
  link_url?: string | null
  sort_order?: number
  children?: ApaasMenu[]
}

interface MenusResponse {
  ok: boolean
  env_id?: number
  apaas_app_id?: string
  menus?: ApaasMenu[]
  flat_count?: number
  error_code?: string
  message?: string
}

const props = defineProps<{
  appId: number | string | null
  selectedMenuId?: string | null
}>()

const emit = defineEmits<{
  (e: 'menu-selected', menu: ApaasMenu): void
  (e: 'menus-loaded', menus: ApaasMenu[], firstFormMenu: ApaasMenu | null): void
}>()

const collapsed = ref(false)
const loading = ref(false)
const error = ref('')
const menus = ref<ApaasMenu[]>([])
const search = ref('')
const expandedGroups = ref<Set<string>>(new Set())
const flatCount = ref(0)

function flatten(list: ApaasMenu[]): ApaasMenu[] {
  const out: ApaasMenu[] = []
  for (const m of list) {
    out.push(m)
    if (m.children?.length) out.push(...flatten(m.children))
  }
  return out
}

const filteredMenus = computed<ApaasMenu[]>(() => {
  const k = search.value.trim().toLowerCase()
  if (!k) return menus.value
  // 搜索时打平展示
  const hits = flatten(menus.value).filter(m =>
    (m.menu_name || '').toLowerCase().includes(k)
    || (m.form_code || '').toLowerCase().includes(k),
  )
  return hits.map(m => ({ ...m, children: undefined }))
})

function toggleGroup(menuId: string) {
  if (expandedGroups.value.has(menuId)) expandedGroups.value.delete(menuId)
  else expandedGroups.value.add(menuId)
  // 触发响应式
  expandedGroups.value = new Set(expandedGroups.value)
}

async function reload() {
  if (!props.appId) {
    menus.value = []
    flatCount.value = 0
    return
  }
  loading.value = true
  error.value = ''
  try {
    const resp = await request.get<any, MenusResponse>(`/applications/${props.appId}/apaas-menus`)
    if (!resp.ok) {
      error.value = resp.message || `菜单拉取失败 (${resp.error_code || 'unknown'})`
      menus.value = []
      flatCount.value = 0
      return
    }
    menus.value = resp.menus || []
    flatCount.value = resp.flat_count || flatten(menus.value).length
    // 默认展开所有 group (第一次加载时)
    const groups = flatten(menus.value).filter(m => m.is_group)
    expandedGroups.value = new Set(groups.map(g => g.menu_id))

    const findFirstForm = (list: ApaasMenu[]): ApaasMenu | null => {
      for (const m of list) {
        if (m.form_id) return m
        if (m.children?.length) {
          const inner = findFirstForm(m.children)
          if (inner) return inner
        }
      }
      return null
    }
    emit('menus-loaded', menus.value, findFirstForm(menus.value))
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '请求失败'
    menus.value = []
    flatCount.value = 0
  } finally {
    loading.value = false
  }
}

function handleSelect(menu: ApaasMenu) {
  emit('menu-selected', menu)
}

// ───── 分组管理 ─────
// 当前所有 group 菜单, 给"移动到分组"菜单用
const groupOptions = computed(() => {
  const all = flatten(menus.value).filter(m => m.is_group)
  return all
})

async function openCreateGroupDialog() {
  if (!props.appId) {
    ElMessage.warning('应用未确定')
    return
  }
  try {
    const { value } = await ElMessageBox.prompt('输入新分组名称', '新建菜单分组', {
      inputPlaceholder: '譬如：业务管理 / 系统配置',
      inputValidator: (v) => (v && v.trim().length > 0) || '分组名不能为空',
      confirmButtonText: '创建',
      cancelButtonText: '取消',
    })
    const name = (value || '').trim()
    if (!name) return
    const resp = await request.post<any, any>(
      `/applications/${props.appId}/apaas-menu-group`,
      { group_name: name },
    )
    if (resp?.ok) {
      ElMessage.success(`分组「${name}」已创建`)
      await reload()
    } else {
      ElMessage.error(resp?.message || '创建分组失败')
    }
  } catch (e: any) {
    if (e === 'cancel' || e === 'close') return
    ElMessage.error(e?.response?.data?.detail || e?.message || '操作失败')
  }
}

async function moveToParent(menu: ApaasMenu, parentId: string, parentName: string) {
  if (!props.appId) return
  if (String(menu.parent_menu_id || '') === String(parentId || '')) {
    ElMessage.info('菜单已在该位置')
    return
  }
  try {
    const resp = await request.post<any, any>(
      `/applications/${props.appId}/apaas-menu-set-parent`,
      { menu_id: menu.menu_id, parent_id: parentId, menu_order: 0 },
    )
    if (resp?.ok) {
      ElMessage.success(`菜单「${menu.menu_name}」已移到 ${parentName}`)
      await reload()
    } else {
      ElMessage.error(resp?.message || '移动菜单失败')
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '操作失败')
  }
}

watch(() => props.appId, () => reload(), { immediate: false })
onMounted(() => reload())
defineExpose({ reload })

// ──────────────────── 节点组件 ────────────────────
function iconForMenu(menu: ApaasMenu, isExpanded: boolean) {
  const t = (menu.menu_type || '').toUpperCase()
  const isGroup = !!menu.is_group || (menu.children && menu.children.length > 0 && !menu.form_id)
  if (isGroup) return isExpanded ? FolderOpened : Folder
  if (t.includes('MODEL')) return Tickets
  if (t.includes('DASHBOARD') || t.includes('DATA_VIZ') || t.includes('BI')) return DataAnalysis
  if (t.includes('TASK')) return Bell
  if (t.includes('EXTERNAL') || t.includes('LINK')) return Link
  if (t.includes('QUOTE')) return Connection
  if (t.includes('CUSTOM') || t.includes('PAGE')) return MagicStick
  if (t.includes('MENU')) return MenuIcon
  return Document
}

const MenuNode = defineComponent({
  name: 'ApaasMenuNode',
  props: {
    menu: { type: Object as PropType<ApaasMenu>, required: true },
    selectedId: { type: String as PropType<string | null | undefined>, default: null },
    collapsed: { type: Boolean, default: false },
    depth: { type: Number, default: 0 },
    expandedGroups: { type: Object as PropType<Set<string>>, required: true },
    groupOptions: { type: Array as PropType<ApaasMenu[]>, default: () => [] },
  },
  emits: ['select', 'toggle-group', 'move-to-parent'],
  setup(p, { emit: emitNode }) {
    const hasChildren = computed(() => !!(p.menu.children && p.menu.children.length))
    const isGroup = computed(() => !!p.menu.is_group || (hasChildren.value && !p.menu.form_id))
    const isExpanded = computed(() => p.expandedGroups.has(p.menu.menu_id))
    const isSelected = computed(() => String(p.selectedId || '') === String(p.menu.menu_id))

    function handleMoveCommand(cmd: { parentId: string; parentName: string }) {
      emitNode('move-to-parent', p.menu, cmd.parentId, cmd.parentName)
    }

    return () => {
      const iconComp = iconForMenu(p.menu, isExpanded.value)
      const padLeft = `${(p.depth || 0) * 12 + 10}px`

      // "..." 下拉: 移动菜单到分组 (普通菜单可移, group 自身暂不支持移)
      // 收起态 + group 自身 不显示
      const showActions = !p.collapsed && !isGroup.value
      const movableTargets = (p.groupOptions || []).filter(g =>
        // 不能移到自己 (group 排除自己, menu 不在 groupOptions 里所以这条对 group 移动有用)
        String(g.menu_id) !== String(p.menu.menu_id)
        // 不能移到当前已在的分组
        && String(g.menu_id) !== String(p.menu.parent_menu_id || ''),
      )
      const canMoveToRoot = !!p.menu.parent_menu_id

      const actionsNode = showActions
        ? h(ElDropdown, {
            trigger: 'click',
            placement: 'bottom-end',
            onCommand: handleMoveCommand,
          }, {
            default: () => h('button', {
              class: 'amsn-actions',
              title: '更多操作',
              onClick: (e: Event) => e.stopPropagation(),
            }, [h(ElIcon, null, () => h(More))]),
            dropdown: () => h(ElDropdownMenu, null, () => {
              const items = []
              if (canMoveToRoot) {
                items.push(h(ElDropdownItem, {
                  command: { parentId: '', parentName: '根级' },
                }, () => '↰ 移出分组到根级'))
              }
              if (movableTargets.length === 0 && !canMoveToRoot) {
                items.push(h(ElDropdownItem, { disabled: true }, () => '暂无可移动的分组'))
              }
              for (const g of movableTargets) {
                items.push(h(ElDropdownItem, {
                  command: { parentId: g.menu_id, parentName: g.menu_name },
                }, () => '📁 移到「' + (g.menu_name || '未命名') + '」'))
              }
              return items
            }),
          })
        : null

      const rowChildren = [
        // 展开箭头
        hasChildren.value
          ? h('span', {
              class: 'amsn-chevron',
              onClick: (e: Event) => {
                e.stopPropagation()
                emitNode('toggle-group', p.menu.menu_id)
              },
            }, [h(ElIcon, null, () => h(isExpanded.value ? ArrowDown : ArrowRight))])
          : h('span', { class: 'amsn-chevron-placeholder' }),
        // 图标
        h('span', { class: ['amsn-icon', { 'amsn-icon-group': isGroup.value }] }, [
          h(ElIcon, null, () => h(iconComp)),
        ]),
        // 名称
        !p.collapsed
          ? h('span', { class: 'amsn-name', title: p.menu.menu_name }, p.menu.menu_name || '(未命名)')
          : null,
        // 操作菜单
        actionsNode,
      ]

      return [
        h('div', {
          class: ['amsn', {
            selected: isSelected.value && !isGroup.value,
            'amsn-group': isGroup.value,
          }],
          style: { paddingLeft: padLeft },
          onClick: () => {
            if (isGroup.value && hasChildren.value) {
              emitNode('toggle-group', p.menu.menu_id)
            } else if (!isGroup.value) {
              emitNode('select', p.menu)
            }
          },
        }, rowChildren),
        isExpanded.value && hasChildren.value
          ? h('div', { class: 'amsn-children' },
              (p.menu.children || []).map(c => h(MenuNode, {
                key: c.menu_id,
                menu: c,
                selectedId: p.selectedId,
                collapsed: p.collapsed,
                depth: (p.depth || 0) + 1,
                expandedGroups: p.expandedGroups,
                groupOptions: p.groupOptions,
                onSelect: (m: ApaasMenu) => emitNode('select', m),
                'onToggle-group': (id: string) => emitNode('toggle-group', id),
                'onMove-to-parent': (m: ApaasMenu, pid: string, pname: string) =>
                  emitNode('move-to-parent', m, pid, pname),
              })),
            )
          : null,
      ]
    }
  },
})
</script>

<style>
/* 2026-05-25: 全局 (不 scoped) 因为内联 MenuNode 是 defineComponent, scoped data-v-xx
   attr 不会传给它. 所有 selectors 都带 .ams / .amsn 前缀避免命名冲突. */
/* ───────── 容器 ───────── */
.ams {
  width: 248px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--t-bg-base, #0e0e16);
  border-right: 1px solid var(--t-border-subtle, rgba(255, 255, 255, 0.06));
  min-height: 0;
  overflow: hidden;
  transition: width 0.2s ease;
}
.ams.collapsed { width: 44px; }

/* ───────── 头部 ───────── */
.ams-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 40px;
  padding: 0 8px 0 14px;
  border-bottom: 1px solid var(--t-border-subtle, rgba(255, 255, 255, 0.06));
  flex-shrink: 0;
  background: linear-gradient(180deg, rgba(124, 58, 237, 0.06) 0%, rgba(124, 58, 237, 0) 100%);
}
.ams-head-main { display: flex; align-items: center; gap: 8px; }
.ams-head-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--t-text-secondary, rgba(255, 255, 255, 0.88));
  letter-spacing: 0.4px;
}
.ams-head-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 16px;
  padding: 0 5px;
  font-size: 10px;
  font-weight: 600;
  color: var(--t-brand-light, #c4b5fd);
  background: rgba(124, 58, 237, 0.18);
  border-radius: 8px;
  border: 1px solid rgba(124, 58, 237, 0.3);
}

.ams-head-actions {
  display: flex;
  align-items: center;
  gap: 2px;
}

/* ───────── 通用图标按钮 ───────── */
.ams-icon-btn {
  all: unset;
  cursor: pointer;
  width: 26px;
  height: 26px;
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--t-text-muted, rgba(255, 255, 255, 0.5));
  font-size: 14px;
  transition: background 0.12s, color 0.12s;
}
.ams-icon-btn:hover { background: rgba(255, 255, 255, 0.06); color: var(--t-text-secondary, #fff); }
.ams-icon-btn.spinning { animation: ams-spin 1s linear infinite; }

/* ───────── 搜索栏 ───────── */
.ams-search-row {
  display: flex;
  gap: 6px;
  padding: 8px 10px;
  flex-shrink: 0;
  align-items: center;
}
.ams-search-input { flex: 1; }
.ams-search-input :deep(.el-input__wrapper) {
  background: rgba(255, 255, 255, 0.04);
  box-shadow: none;
  border: 1px solid var(--t-border-subtle, rgba(255, 255, 255, 0.08));
  border-radius: 6px;
  padding: 0 8px;
  transition: border-color 0.15s, background 0.15s;
}
.ams-search-input :deep(.el-input__wrapper:hover) {
  border-color: rgba(255, 255, 255, 0.15);
}
.ams-search-input :deep(.el-input__wrapper.is-focus) {
  border-color: var(--t-brand-light, #818cf8) !important;
  background: rgba(124, 58, 237, 0.08);
  box-shadow: 0 0 0 2px rgba(124, 58, 237, 0.12) !important;
}
.ams-search-input :deep(.el-input__inner) {
  color: var(--t-text-secondary, rgba(255, 255, 255, 0.88));
  font-size: 12px;
}
.ams-search-input :deep(.el-input__inner::placeholder) {
  color: var(--t-text-muted, rgba(255, 255, 255, 0.35));
}
.ams-search-input :deep(.el-icon) {
  color: var(--t-text-muted, rgba(255, 255, 255, 0.4));
  font-size: 12px;
}

/* ───────── 列表区 ───────── */
.ams-body {
  flex: 1;
  overflow-y: auto;
  padding: 4px 6px 12px;
  min-height: 0;
}
.ams-body::-webkit-scrollbar { width: 6px; }
.ams-body::-webkit-scrollbar-track { background: transparent; }
.ams-body::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.08); border-radius: 3px; }
.ams-body::-webkit-scrollbar-thumb:hover { background: rgba(255, 255, 255, 0.16); }

/* ───────── 状态视图 ───────── */
.ams-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 40px 16px;
  color: var(--t-text-muted, rgba(255, 255, 255, 0.45));
  font-size: 12px;
  text-align: center;
}
.ams-state .el-icon { font-size: 22px; opacity: 0.7; }
.ams-state p { margin: 0; max-width: 200px; line-height: 1.5; }
.ams-state-err { color: #fca5a5; }
.ams-state-err .el-icon { color: #ef4444; }
.ams-spin { animation: ams-spin 1s linear infinite; }

/* ───────── 树 ───────── */
.ams-tree { display: flex; flex-direction: column; gap: 1px; padding-top: 4px; }

.amsn {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  height: 32px;
  padding-right: 8px;
  cursor: pointer;
  border-radius: 6px;
  color: var(--t-text-secondary, rgba(255, 255, 255, 0.78));
  font-size: 13px;
  user-select: none;
  transition: background 0.12s, color 0.12s, transform 0.08s;
  margin: 1px 2px;
}
.amsn:hover {
  background: rgba(255, 255, 255, 0.05);
  color: var(--t-text-primary, #fff);
}
.amsn:active { transform: scale(0.985); }

/* 分组标题: 更小字号 + 强调色 */
.amsn.amsn-group {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: var(--t-text-muted, rgba(255, 255, 255, 0.5));
  height: 28px;
  margin-top: 6px;
}
.amsn.amsn-group:hover { color: var(--t-text-secondary, #fff); }

/* 选中态: 背景 + 左侧紫条 + 加粗 */
.amsn.selected {
  background: linear-gradient(90deg, rgba(124, 58, 237, 0.22) 0%, rgba(124, 58, 237, 0.10) 100%);
  color: var(--t-brand-light, #c4b5fd);
  font-weight: 500;
}
.amsn.selected::before {
  content: '';
  position: absolute;
  left: 0;
  top: 6px;
  bottom: 6px;
  width: 3px;
  background: var(--t-brand-light, #a78bfa);
  border-radius: 0 2px 2px 0;
}

/* ── 子元素 ── */
.amsn-chevron,
.amsn-chevron-placeholder {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  font-size: 10px;
  flex-shrink: 0;
  color: var(--t-text-muted, rgba(255, 255, 255, 0.4));
  border-radius: 3px;
  transition: color 0.12s, background 0.12s;
}
.amsn-chevron { cursor: pointer; }
.amsn-chevron:hover { color: var(--t-text-secondary, #fff); background: rgba(255, 255, 255, 0.08); }
.amsn-chevron .el-icon { font-size: 10px; }

.amsn-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  font-size: 14px;
  flex-shrink: 0;
  color: var(--t-text-muted, rgba(255, 255, 255, 0.55));
  transition: color 0.12s;
}
.amsn:hover .amsn-icon { color: var(--t-text-secondary, rgba(255, 255, 255, 0.9)); }
.amsn.selected .amsn-icon { color: var(--t-brand-light, #c4b5fd); }
.amsn-icon-group { color: var(--t-text-muted, rgba(255, 255, 255, 0.5)); }
.amsn-icon .el-icon { font-size: 14px; }

.amsn-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* "..." 操作按钮 — hover 时 / 选中时显示 */
.amsn-actions {
  all: unset;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 4px;
  color: var(--t-text-muted, rgba(255, 255, 255, 0.45));
  font-size: 14px;
  flex-shrink: 0;
  opacity: 0;
  transition: opacity 0.12s, background 0.12s, color 0.12s;
}
.amsn:hover .amsn-actions,
.amsn.selected .amsn-actions { opacity: 1; }
.amsn-actions:hover { background: rgba(255, 255, 255, 0.1); color: var(--t-text-secondary, #fff); }
.amsn-actions .el-icon { font-size: 14px; }

/* ── 收起态 ── */
.ams.collapsed .amsn {
  justify-content: center;
  padding: 0;
  height: 36px;
  margin: 2px 4px;
}
.ams.collapsed .amsn-chevron,
.ams.collapsed .amsn-chevron-placeholder { display: none; }
.ams.collapsed .amsn-icon .el-icon { font-size: 16px; }
.ams.collapsed .ams-search-row { display: none; }

/* 子级树缩进 (group children) — 加左侧细线表层级 */
.amsn-children {
  position: relative;
}
.amsn-children::before {
  content: '';
  position: absolute;
  left: 18px;
  top: 0;
  bottom: 4px;
  width: 1px;
  background: rgba(255, 255, 255, 0.06);
}

@keyframes ams-spin {
  to { transform: rotate(360deg); }
}
</style>
