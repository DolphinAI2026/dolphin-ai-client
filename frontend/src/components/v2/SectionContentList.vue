<template>
  <!--
    SectionContentList.vue — 通用 section 资源列表 (SPEC v2 §1.1 / PR2b §3)

    用途: 在 ChatPage 左侧 SectionNav sub-tab 切换时显资源列表 (模型 / 字典 /
    表单 / 列表 / 流程 / 业务事件 / 角色). 复刻 ApaasMenuSidebar 视觉风格 (270px
    宽 / brand 色选中态 / -t-* token), 但通用化 — 数据源是 backend
    /api/applications/{id}/section-content/{kind}.

    Props:
    - appId (必传): ai-builder 本地应用 id
    - resourceKind: 7 种之一
    - apaasAppId?: 平台 app id, 空 = 应用未部署
    - envId?: 平台环境 id

    Emit:
    - select-item (item: any) — 点击列表项 (P0 由父组件 console.log; P1 接 iframe)
    - request-create — 点击 "+ 新增" (P0 暂不接业务)

    设计原则: 跟 ApaasMenuSidebar 完全一致的视觉 token + 状态机
    (loading/error/empty/未部署/正常). 错误回退: endpoint 缺时 fallback 空列表
    + console.warn, 不抛错卡 UI.
  -->
  <aside class="scl" :class="{ collapsed }">
    <!-- 头部: label + 总数 badge + 刷新按钮 -->
    <header class="scl-head">
      <div v-if="!collapsed" class="scl-head-main">
        <span class="scl-head-title">{{ kindLabel }}</span>
        <span v-if="items.length > 0" class="scl-head-badge">{{ items.length }}</span>
      </div>
      <div class="scl-head-actions">
        <button
          v-if="!collapsed"
          class="scl-icon-btn"
          :class="{ spinning: loading }"
          title="刷新"
          :disabled="loading || !canFetch"
          @click="reload"
        >
          <el-icon><Refresh /></el-icon>
        </button>
        <button
          class="scl-icon-btn"
          :title="collapsed ? '展开' : '收起'"
          @click="collapsed = !collapsed"
        >
          <el-icon><component :is="collapsed ? Expand : Fold" /></el-icon>
        </button>
      </div>
    </header>

    <!-- 搜索栏 (仅展开态) -->
    <div v-if="!collapsed" class="scl-search-row">
      <el-input
        v-model="search"
        size="small"
        :placeholder="`搜索${kindLabel}`"
        clearable
        class="scl-search-input"
      >
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
      </el-input>
    </div>

    <!-- 主体: 状态机 -->
    <div class="scl-body">
      <!-- ① 应用未部署 -->
      <div v-if="!canFetch" v-show="!collapsed" class="scl-state scl-state-undeployed">
        <el-icon><InfoFilled /></el-icon>
        <p>应用还未部署到平台, 部署后这里能看到{{ kindLabel }}</p>
      </div>

      <!-- ② 加载中 -->
      <div v-else-if="loading" class="scl-state">
        <el-skeleton v-if="!collapsed" :rows="6" animated style="width: 100%; padding: 0 8px" />
        <el-icon v-else class="scl-spin"><Loading /></el-icon>
      </div>

      <!-- ③ 错误 -->
      <div v-else-if="error" v-show="!collapsed" class="scl-state scl-state-err">
        <el-icon><Warning /></el-icon>
        <p>{{ error }}</p>
        <el-button size="small" type="primary" @click="reload">重试</el-button>
      </div>

      <!-- ④ 空列表 -->
      <div v-else-if="!filteredItems.length" v-show="!collapsed" class="scl-state scl-state-empty">
        <el-icon><Files /></el-icon>
        <p v-if="search">无匹配「{{ search }}」</p>
        <p v-else>该应用还没有{{ kindLabel }}</p>
      </div>

      <!-- ⑤ 正常列表 -->
      <ul v-else class="scl-list" role="list">
        <li
          v-for="item in filteredItems"
          :key="getItemKey(item)"
          class="scl-list-item"
          :class="{ selected: getItemKey(item) === selectedKey }"
          :title="getItemName(item) || getItemCode(item) || ''"
          @click="onItemClick(item)"
        >
          <span class="scl-list-icon" aria-hidden="true">
            <el-icon><component :is="resourceIcon" /></el-icon>
          </span>
          <span v-if="!collapsed" class="scl-list-text">
            <span class="scl-list-name">{{ getItemName(item) || '(未命名)' }}</span>
            <span v-if="getItemCode(item)" class="scl-list-sub">{{ getItemCode(item) }}</span>
          </span>
        </li>
      </ul>
    </div>

    <!-- 底部: + 新增按钮 -->
    <footer v-if="!collapsed && canFetch && !loading && !error" class="scl-foot">
      <button class="scl-add-btn" @click="onCreateClick">
        <el-icon><Plus /></el-icon>
        <span>新增{{ kindLabel }}</span>
      </button>
    </footer>
  </aside>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { ElIcon, ElInput, ElButton, ElSkeleton } from 'element-plus'
import {
  Search, Refresh, Loading, Warning, Files, Expand, Fold, Plus,
  InfoFilled,
  Tickets, Collection, Document, Grid, Operation, Bell, User,
} from '@element-plus/icons-vue'
import request from '@/utils/request'

// ──────────────── 类型 ────────────────
export type ResourceKind =
  | 'models'
  | 'dicts'
  | 'forms'
  | 'lists'
  | 'processes'
  | 'business-events'
  | 'roles'

interface SectionContentItem {
  // backend 字段 — 我们做容错读取, 字段名差异通过 getItemName / getItemCode 兜底.
  // 已知 backend 各资源返的 key 不完全一致 (model 用 model_name / business_object_name,
  // dict 用 dict_name, role 用 role_name 等), 全部走 getItemName 容错读.
  [k: string]: any
}

interface ContentResponse {
  ok?: boolean
  items?: SectionContentItem[]
  error_code?: string
  message?: string
}

// ──────────────── Props / Emits ────────────────
const props = withDefaults(
  defineProps<{
    appId: number
    resourceKind: ResourceKind
    apaasAppId?: string
    envId?: number
    /** 可选: 父组件可控选中态 */
    selectedKey?: string | null
  }>(),
  {
    apaasAppId: '',
    envId: 0,
    selectedKey: null,
  },
)

const emit = defineEmits<{
  (e: 'select-item', item: SectionContentItem): void
  (e: 'request-create'): void
  (e: 'items-loaded', items: SectionContentItem[]): void
}>()

// ──────────────── 中文 label / 图标 映射 ────────────────
const KIND_LABEL: Record<ResourceKind, string> = {
  'models': '数据模型',
  'dicts': '字典',
  'forms': '表单',
  'lists': '列表',
  'processes': '流程',
  'business-events': '业务事件',
  'roles': '角色',
}

const KIND_ICON: Record<ResourceKind, any> = {
  'models': Tickets,
  'dicts': Collection,
  'forms': Document,
  'lists': Grid,
  'processes': Operation,
  'business-events': Bell,
  'roles': User,
}

const kindLabel = computed(() => KIND_LABEL[props.resourceKind] || props.resourceKind)
const resourceIcon = computed(() => KIND_ICON[props.resourceKind] || Document)

// ──────────────── 状态 ────────────────
const collapsed = ref(false)
const loading = ref(false)
const error = ref('')
const items = ref<SectionContentItem[]>([])
const search = ref('')

// 应用未部署判断: apaasAppId 空 视为未部署. 加载后若 backend 返 APP_NOT_DEPLOYED 也走此分支.
const canFetch = computed(() => Boolean(props.apaasAppId && props.appId))

// ──────────────── 字段读取容错 ────────────────
// backend 各资源返的字段不完全一致, 这里做容错读取.
function getItemName(item: SectionContentItem): string {
  return (
    item?.name
    || item?.label
    || item?.title
    || item?.display_name
    || item?.model_name
    || item?.business_object_name
    || item?.dict_name
    || item?.form_name
    || item?.list_name
    || item?.process_name
    || item?.event_name
    || item?.role_name
    || item?.menu_name
    || ''
  ).toString()
}

function getItemCode(item: SectionContentItem): string {
  return (
    item?.code
    || item?.business_object_code
    || item?.model_code
    || item?.dict_code
    || item?.form_code
    || item?.list_code
    || item?.process_code
    || item?.event_code
    || item?.role_code
    || ''
  ).toString()
}

function getItemKey(item: SectionContentItem): string {
  // 按 id-like 字段优先, fallback name+code
  return String(
    item?.id
    ?? item?.model_id
    ?? item?.business_object_id
    ?? item?.dict_id
    ?? item?.form_id
    ?? item?.list_id
    ?? item?.process_id
    ?? item?.event_id
    ?? item?.role_id
    ?? item?.menu_id
    ?? `${getItemName(item)}-${getItemCode(item)}`,
  )
}

// ──────────────── 过滤 ────────────────
const filteredItems = computed<SectionContentItem[]>(() => {
  const kw = search.value.trim().toLowerCase()
  if (!kw) return items.value
  return items.value.filter((item) => {
    return (
      getItemName(item).toLowerCase().includes(kw)
      || getItemCode(item).toLowerCase().includes(kw)
    )
  })
})

// ──────────────── 拉取 ────────────────
async function reload() {
  if (!canFetch.value) {
    items.value = []
    error.value = ''
    return
  }
  loading.value = true
  error.value = ''
  try {
    const resp = await request.get<any, ContentResponse>(
      `/applications/${props.appId}/section-content/${props.resourceKind}`,
    )
    // 后端约定 ok=false + error_code=APP_NOT_DEPLOYED → 不显错误, 走未部署分支
    if (resp?.error_code === 'APP_NOT_DEPLOYED') {
      items.value = []
      // canFetch 是 computed (基于 props), 这里不能直接改; 用 error 留空 + 列表空,
      // 父组件应保证 apaasAppId 没有时不渲染此组件. 实际生效 path: 此分支基本只在
      // race condition (props.apaasAppId 同步显 / backend 异步说没 deploy) 时触发,
      // 此时清空列表即可, UI 表现就是 "空列表 -> 该应用还没有 XX".
      return
    }
    if (resp && resp.ok === false) {
      error.value = resp.message || `加载${kindLabel.value}失败 (${resp.error_code || 'unknown'})`
      items.value = []
      return
    }
    const list = Array.isArray(resp?.items) ? resp.items : []
    items.value = list
    emit('items-loaded', list)
  } catch (e: any) {
    // endpoint 缺 (404) — fallback 空列表 + console.warn, 不卡 UI
    const status = e?.response?.status
    if (status === 404) {
      // eslint-disable-next-line no-console
      console.warn(
        `[SectionContentList] endpoint /applications/${props.appId}/section-content/${props.resourceKind} `
        + `returned 404, falling back to empty list.`,
      )
      items.value = []
      error.value = ''
      return
    }
    error.value = e?.response?.data?.detail || e?.message || '请求失败'
    items.value = []
  } finally {
    loading.value = false
  }
}

// ──────────────── 事件 ────────────────
function onItemClick(item: SectionContentItem) {
  emit('select-item', item)
}

function onCreateClick() {
  emit('request-create')
}

// ──────────────── lifecycle ────────────────
onMounted(() => reload())
watch(
  () => [props.resourceKind, props.appId, props.apaasAppId],
  () => {
    items.value = []
    search.value = ''
    error.value = ''
    reload()
  },
)

defineExpose({ reload })
</script>

<style scoped>
/* 复刻 ApaasMenuSidebar 视觉风格. 命名空间 .scl / .scl-* 避免冲突.
   主题策略: 全部 var(--t-*) token + 裸跑 fallback. */

/* ───── 容器 ───── */
.scl {
  width: 250px;
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
.scl.collapsed { width: 44px; }

/* ───── 头部 ───── */
.scl-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 40px;
  padding: 0 8px 0 14px;
  border-bottom: 1px solid var(--t-border-subtle, rgba(99, 102, 241, 0.08));
  flex-shrink: 0;
  background: var(--t-brand-subtle, rgba(79, 110, 247, 0.05));
}
.scl-head-main {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
}
.scl-head-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--t-text-primary, #1e293b);
  letter-spacing: 0.4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.scl-head-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 16px;
  padding: 0 5px;
  font-size: 10px;
  font-weight: 600;
  color: var(--t-brand, #4f6ef7);
  background: var(--t-brand-subtle, rgba(79, 110, 247, 0.1));
  border-radius: 8px;
  border: 1px solid var(--t-border-strong, rgba(79, 110, 247, 0.2));
}
.scl-head-actions {
  display: flex;
  align-items: center;
  gap: 2px;
}

/* ───── 通用图标按钮 ───── */
.scl-icon-btn {
  all: unset;
  cursor: pointer;
  width: 26px;
  height: 26px;
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--t-text-secondary, #64748b);
  font-size: 14px;
  transition: background 0.12s, color 0.12s;
}
.scl-icon-btn:hover {
  background: var(--t-bg-panel-hover, rgba(99, 102, 241, 0.08));
  color: var(--t-brand, #4f6ef7);
}
.scl-icon-btn:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}
.scl-icon-btn:disabled:hover {
  background: transparent;
  color: var(--t-text-secondary, #64748b);
}
.scl-icon-btn.spinning { animation: scl-spin 1s linear infinite; }

/* ───── 搜索栏 ───── */
.scl-search-row {
  display: flex;
  gap: 6px;
  padding: 8px 10px;
  flex-shrink: 0;
  align-items: center;
}
.scl-search-input { flex: 1; }
.scl-search-input :deep(.el-input__wrapper) {
  background: var(--t-bg-input, #f5f7fc);
  box-shadow: none;
  border: 1px solid var(--t-border-subtle, rgba(99, 102, 241, 0.1));
  border-radius: 6px;
  padding: 0 8px;
  transition: border-color 0.15s, background 0.15s;
}
.scl-search-input :deep(.el-input__wrapper:hover) {
  border-color: var(--t-border-strong, rgba(99, 102, 241, 0.2));
}
.scl-search-input :deep(.el-input__wrapper.is-focus) {
  border-color: var(--t-brand, #4f6ef7) !important;
  background: var(--t-bg-panel, #fff);
  box-shadow: 0 0 0 2px var(--t-brand-subtle, rgba(79, 110, 247, 0.16)) !important;
}
.scl-search-input :deep(.el-input__inner) {
  color: var(--t-text-primary, #1e293b);
  font-size: 12px;
}
.scl-search-input :deep(.el-input__inner::placeholder) {
  color: var(--t-text-muted, #94a3b8);
}
.scl-search-input :deep(.el-icon) {
  color: var(--t-text-muted, #94a3b8);
  font-size: 12px;
}

/* ───── 主体 ───── */
.scl-body {
  flex: 1;
  overflow-y: auto;
  padding: 4px 6px 12px;
  min-height: 0;
}
.scl-body::-webkit-scrollbar { width: 6px; }
.scl-body::-webkit-scrollbar-track { background: transparent; }
.scl-body::-webkit-scrollbar-thumb {
  background: var(--t-border-strong, rgba(99, 102, 241, 0.15));
  border-radius: 3px;
}
.scl-body::-webkit-scrollbar-thumb:hover {
  background: var(--t-brand, #4f6ef7);
}

/* ───── 状态视图 ───── */
.scl-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 40px 16px;
  color: var(--t-text-muted, #94a3b8);
  font-size: 12px;
  text-align: center;
}
.scl-state .el-icon { font-size: 22px; opacity: 0.7; }
.scl-state p { margin: 0; max-width: 200px; line-height: 1.5; }
.scl-state-err { color: #ef4444; }
.scl-state-err .el-icon { color: #ef4444; }
.scl-state-undeployed { color: var(--t-text-secondary, #64748b); }
.scl-state-undeployed .el-icon {
  color: var(--t-brand, #4f6ef7);
  opacity: 0.6;
}
.scl-spin { animation: scl-spin 1s linear infinite; }

/* ───── 列表 ───── */
.scl-list {
  list-style: none;
  margin: 0;
  padding: 4px 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.scl-list-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 36px;
  padding: 6px 10px 6px 14px;
  cursor: pointer;
  border-radius: 6px;
  color: var(--t-text-primary, #1e293b);
  font-size: 13px;
  user-select: none;
  transition: background 0.12s, color 0.12s, transform 0.08s;
  margin: 1px 2px;
}
.scl-list-item:hover {
  background: var(--t-bg-panel-hover, rgba(99, 102, 241, 0.06));
  color: var(--t-brand, #4f6ef7);
}
.scl-list-item:active { transform: scale(0.985); }

.scl-list-item.selected {
  background: var(--t-brand-subtle, rgba(79, 110, 247, 0.1));
  color: var(--t-brand, #4f6ef7);
  font-weight: 500;
}
.scl-list-item.selected:hover {
  background: var(--t-brand-subtle, rgba(79, 110, 247, 0.14));
  color: var(--t-brand, #4f6ef7);
}
.scl-list-item.selected::before {
  content: '';
  position: absolute;
  left: 0;
  top: 6px;
  bottom: 6px;
  width: 3px;
  background: var(--t-brand, #4f6ef7);
  border-radius: 0 2px 2px 0;
}

.scl-list-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  font-size: 14px;
  flex-shrink: 0;
  color: var(--t-text-secondary, #64748b);
  transition: color 0.12s;
}
.scl-list-item:hover .scl-list-icon,
.scl-list-item.selected .scl-list-icon {
  color: var(--t-brand, #4f6ef7);
}
.scl-list-icon .el-icon { font-size: 14px; }

.scl-list-text {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
  overflow: hidden;
}
.scl-list-name {
  font-size: 13px;
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.scl-list-sub {
  font-size: 11px;
  line-height: 1.2;
  color: var(--t-text-muted, #94a3b8);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.scl-list-item.selected .scl-list-sub {
  color: var(--t-brand, #4f6ef7);
  opacity: 0.65;
}

/* ───── 底部 + 新增按钮 ───── */
.scl-foot {
  padding: 8px 10px 10px;
  border-top: 1px solid var(--t-border-subtle, rgba(99, 102, 241, 0.08));
  flex-shrink: 0;
}
.scl-add-btn {
  all: unset;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 100%;
  height: 32px;
  padding: 0 10px;
  border-radius: 6px;
  border: 1px dashed var(--t-border-strong, rgba(79, 110, 247, 0.25));
  color: var(--t-brand, #4f6ef7);
  background: transparent;
  font-size: 12px;
  font-weight: 500;
  transition: background 0.12s, border-color 0.12s, color 0.12s;
}
.scl-add-btn:hover {
  background: var(--t-brand-subtle, rgba(79, 110, 247, 0.08));
  border-color: var(--t-brand, #4f6ef7);
  border-style: solid;
}
.scl-add-btn .el-icon { font-size: 12px; }

/* ───── 折叠态 ───── */
.scl.collapsed .scl-search-row { display: none; }
.scl.collapsed .scl-foot { display: none; }
.scl.collapsed .scl-list-item {
  justify-content: center;
  padding: 0;
  height: 36px;
  margin: 2px 4px;
}
.scl.collapsed .scl-list-text { display: none; }
.scl.collapsed .scl-list-icon .el-icon { font-size: 16px; }

@keyframes scl-spin {
  to { transform: rotate(360deg); }
}
</style>
