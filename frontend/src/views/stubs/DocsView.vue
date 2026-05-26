<!-- DocsView.vue — 文档统一管理 (design-v4 Phase I1, 2026-05-26).

  替换 G3 stub. 复用 /api/specs-v2 (specsV2Api), 每个 Application 1 个 synthetic SPEC.

  视觉对齐 DatasourcesView.vue (H3 pattern).

  4 sub-tab 按 doc_type 区分:
    - SPEC: doc_type === 'spec' (6 章节 SPEC)
    - 需求: 'general' (其他需求文档)
    - API 文档: 'self_dev_package' (自开发包文档)
    - 用户手册: 'page_design' (页面设计/用户手册)

  P6 留尾: 真多文档支持 (当前每应用 1 篇).
-->
<template>
  <main class="ds-page">
    <!-- 顶部 header -->
    <header class="ds-head">
      <div class="ds-head-meta">
        <h1 class="ds-title">文档</h1>
        <p class="ds-stats">
          <span>{{ totalCount }} 篇</span>
          <span class="ds-stat-sep">·</span>
          <span>{{ publishedCount }} 已发布</span>
          <span v-if="draftCount > 0" class="ds-stat-sep">·</span>
          <span v-if="draftCount > 0" class="ds-stat-muted">{{ draftCount }} 草稿</span>
        </p>
      </div>
      <div class="ds-head-actions">
        <button class="ds-btn ds-btn-ghost" disabled title="P6 接入 — 新建文档需关联应用">
          <span class="ds-btn-icon">+</span>
          新建文档
        </button>
      </div>
    </header>

    <!-- 4 sub-tab -->
    <div class="ds-subnav" role="tablist">
      <button
        v-for="t in SUB_TABS"
        :key="t.code"
        class="ds-subnav-tab"
        :class="{ active: subTab === t.code }"
        role="tab"
        :aria-selected="subTab === t.code"
        @click="subTab = t.code"
      >
        {{ t.label }}
        <span v-if="t.count !== undefined" class="ds-subnav-count">{{ t.count }}</span>
      </button>
    </div>

    <!-- table -->
    <section class="ds-section">
      <div v-if="loading" class="ds-state">加载中…</div>
      <div v-else-if="error" class="ds-state ds-state-err">
        {{ error }}
        <button class="ds-btn ds-btn-ghost" @click="loadDocs">重试</button>
      </div>
      <div v-else-if="filteredDocs.length === 0" class="ds-empty">
        <div class="ds-empty-icon">📄</div>
        <h3>暂无文档</h3>
        <p>每个应用自动生成 1 篇 SPEC 文档. 创建应用即自动落 SPEC.</p>
        <button class="ds-btn ds-btn-primary" @click="goCreateApp">前往新建应用</button>
      </div>
      <div v-else class="ds-table-wrap">
        <table class="ds-table">
          <thead>
            <tr>
              <th class="num">#</th>
              <th class="col-title">标题</th>
              <th class="col-type">类型</th>
              <th class="col-author">作者</th>
              <th class="col-time">修改时间</th>
              <th class="col-version">版本</th>
              <th class="col-status">状态</th>
              <th class="col-ops">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(d, i) in filteredDocs" :key="d.id">
              <td class="num">{{ i + 1 }}</td>
              <td class="col-title">
                <div class="ds-cell-name">{{ d.title }}</div>
                <div v-if="d.excerpt" class="ds-cell-desc">{{ d.excerpt }}</div>
              </td>
              <td class="col-type">
                <span class="ds-badge ds-badge-doc mono">{{ d.typeLabel }}</span>
              </td>
              <td class="col-author muted">{{ d.author || '—' }}</td>
              <td class="col-time mono muted">{{ d.updatedAt || '—' }}</td>
              <td class="col-version mono">v{{ d.latestVersion }}</td>
              <td class="col-status">
                <span class="ds-status-chip" :class="statusClass(d.statusCode)">
                  {{ statusLabel(d.statusCode) }}
                </span>
              </td>
              <td class="col-ops">
                <button class="ds-link-btn" @click="openDoc(d)" title="查看文档">查看</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </main>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { specsV2Api, type SpecListItem, type SpecDocType } from '@/api/specsV2'

type SubCode = 'spec' | 'general' | 'self_dev' | 'page_design'

interface DocItem {
  id: string
  appId: number
  title: string
  excerpt?: string
  docType: SpecDocType
  typeLabel: string
  author?: string
  updatedAt?: string
  latestVersion: number
  statusCode: 'draft' | 'test' | 'prod' | 'archived'
}

const router = useRouter()
const subTab = ref<SubCode>('spec')
const loading = ref(true)
const error = ref('')
const docs = ref<DocItem[]>([])

function mapDocType(t?: SpecDocType): { code: SubCode; label: string } {
  if (t === 'self_dev_package') return { code: 'self_dev', label: 'API 文档' }
  if (t === 'page_design')      return { code: 'page_design', label: '用户手册' }
  if (t === 'general')          return { code: 'general', label: '需求' }
  return { code: 'spec', label: 'SPEC' }
}

function toDocItem(s: SpecListItem): DocItem {
  const meta = mapDocType(s.doc_type)
  // 取最新版本信息
  const latest = s.versions?.[0]
  return {
    id: s.id,
    appId: s.app_id,
    title: s.app_name,
    excerpt: s.excerpt,
    docType: s.doc_type || 'spec',
    typeLabel: meta.label,
    author: latest?.author,
    updatedAt: latest?.date,
    latestVersion: s.latest || 1,
    statusCode: (latest?.status as DocItem['statusCode']) || 'draft',
  }
}

async function loadDocs() {
  loading.value = true
  error.value = ''
  try {
    const res = await specsV2Api.list()
    docs.value = (res.specs || []).map(toDocItem)
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '加载失败'
    docs.value = []
  } finally {
    loading.value = false
  }
}

const totalCount = computed(() => docs.value.length)
const publishedCount = computed(() => docs.value.filter((d) => d.statusCode === 'prod').length)
const draftCount = computed(() => docs.value.filter((d) => d.statusCode === 'draft').length)

const counts = computed(() => {
  const grouped: Record<SubCode, number> = { spec: 0, general: 0, self_dev: 0, page_design: 0 }
  for (const d of docs.value) {
    const c = mapDocType(d.docType).code
    grouped[c]++
  }
  return grouped
})

const SUB_TABS = computed<{ code: SubCode; label: string; count: number }[]>(() => [
  { code: 'spec', label: 'SPEC', count: counts.value.spec },
  { code: 'general', label: '需求', count: counts.value.general },
  { code: 'self_dev', label: 'API 文档', count: counts.value.self_dev },
  { code: 'page_design', label: '用户手册', count: counts.value.page_design },
])

const filteredDocs = computed(() => {
  return docs.value.filter((d) => mapDocType(d.docType).code === subTab.value)
})

function statusClass(s: DocItem['statusCode']): string {
  if (s === 'prod') return 'ok'
  if (s === 'archived') return 'unverified'
  if (s === 'test') return 'warn'
  return 'unverified'
}
function statusLabel(s: DocItem['statusCode']): string {
  if (s === 'prod') return '已发布'
  if (s === 'test') return '测试'
  if (s === 'archived') return '归档'
  return '草稿'
}

function openDoc(d: DocItem) {
  // 跳到应用聊天页 doc tab — 复用现有 ChatPage doc 视图
  router.push({ path: '/chat', query: { app_id: String(d.appId) } })
}

function goCreateApp() {
  router.push('/landing')
}

onMounted(() => {
  loadDocs()
})
</script>

<style scoped>
.ds-page {
  font-family: var(--font-sans);
  color: var(--text);
  padding: 28px 36px;
  background: var(--bg);
  min-height: 100%;
  overflow-y: auto;
  font-feature-settings: 'cv11', 'ss01';
}

.ds-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 18px;
  padding-bottom: 18px;
  border-bottom: 1px solid var(--line);
}
.ds-head-meta { flex: 1; min-width: 0; }
.ds-title {
  margin: 0 0 8px;
  font-size: 32px;
  font-weight: 600;
  color: var(--text);
  letter-spacing: -0.5px;
  line-height: 1.2;
}
.ds-stats {
  margin: 0;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-3);
  flex-wrap: wrap;
}
.ds-stat-sep { color: var(--text-4); }
.ds-stat-muted { color: var(--text-4); }
.ds-head-actions { display: flex; gap: 8px; flex-shrink: 0; }

.ds-btn {
  height: 32px;
  padding: 0 14px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  border: 1px solid transparent;
  white-space: nowrap;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  transition: background 0.12s, border-color 0.12s, color 0.12s;
}
.ds-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.ds-btn-ghost {
  background: var(--surface);
  border-color: var(--line-strong);
  color: var(--text);
}
.ds-btn-ghost:hover:not(:disabled) {
  border-color: var(--brand);
  color: var(--brand);
}
.ds-btn-primary { background: var(--brand); color: #fff; }
.ds-btn-primary:hover:not(:disabled) { background: var(--brand-hover); }
.ds-btn-icon { font-size: 13px; line-height: 1; }

.ds-subnav {
  display: flex;
  gap: 4px;
  margin-bottom: 14px;
  border-bottom: 1px solid var(--line);
}
.ds-subnav-tab {
  height: 36px;
  padding: 0 14px;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--text-3);
  font-size: 13px;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  transition: color 0.12s, border-color 0.12s;
  margin-bottom: -1px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.ds-subnav-tab:hover { color: var(--text); }
.ds-subnav-tab.active {
  color: var(--brand);
  border-bottom-color: var(--brand);
}
.ds-subnav-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 18px;
  min-width: 18px;
  padding: 0 6px;
  background: var(--surface-2);
  color: var(--text-3);
  border-radius: 9px;
  font-size: 11px;
  font-weight: 600;
  font-family: var(--font-mono);
}
.ds-subnav-tab.active .ds-subnav-count {
  background: var(--brand-soft);
  color: var(--brand);
}

.ds-section { min-height: 200px; }
.ds-state {
  padding: 48px 0;
  text-align: center;
  color: var(--text-3);
  font-size: 13.5px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}
.ds-state-err { color: var(--err); }
.ds-empty {
  padding: 64px 24px;
  text-align: center;
  color: var(--text-3);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}
.ds-empty-icon { font-size: 48px; line-height: 1; }
.ds-empty h3 { margin: 0; font-size: 18px; font-weight: 600; color: var(--text); }
.ds-empty p { margin: 0; font-size: 13.5px; max-width: 460px; }

.ds-table-wrap {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 10px;
  overflow: hidden;
  box-shadow: var(--sh-1);
}
.ds-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  table-layout: fixed;
}
.ds-table th {
  text-align: left;
  padding: 11px 14px;
  background: var(--surface-2);
  font-weight: 500;
  color: var(--text-3);
  font-size: 12.5px;
  border-bottom: 1px solid var(--line);
  white-space: nowrap;
}
.ds-table th.num { width: 40px; text-align: center; }
.ds-table th.col-title { width: 280px; }
.ds-table th.col-type { width: 110px; }
.ds-table th.col-author { width: 100px; }
.ds-table th.col-time { width: 100px; }
.ds-table th.col-version { width: 60px; text-align: center; }
.ds-table th.col-status { width: 80px; }
.ds-table th.col-ops { width: 80px; text-align: center; }

.ds-table td {
  padding: 12px 14px;
  border-bottom: 1px solid var(--line);
  color: var(--text);
  vertical-align: middle;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ds-table tr:last-child td { border-bottom: none; }
.ds-table tr:hover td { background: var(--surface-2); }
.ds-table .num { color: var(--text-4); text-align: center; }
.ds-table .col-ops { text-align: center; }
.ds-table .col-version { text-align: center; }
.ds-table .mono {
  font-family: var(--font-mono);
  font-size: 12.5px;
  color: var(--text-2);
}
.ds-table .muted { color: var(--text-3); }

.ds-cell-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}
.ds-cell-desc {
  font-size: 11.5px;
  color: var(--text-4);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ds-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 600;
  border-radius: 4px;
  white-space: nowrap;
  letter-spacing: 0.02em;
}
.ds-badge-doc {
  background: var(--brand-soft);
  color: var(--brand);
}

.ds-status-chip {
  display: inline-block;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
  white-space: nowrap;
}
.ds-status-chip.ok       { background: var(--ok-soft);    color: var(--ok); }
.ds-status-chip.warn     { background: var(--warn-soft);  color: var(--warn); }
.ds-status-chip.unverified { background: var(--surface-2); color: var(--text-3); }

.ds-link-btn {
  background: transparent;
  border: none;
  color: var(--brand);
  font-size: 12.5px;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  padding: 4px 6px;
  border-radius: 4px;
  transition: background 0.12s, color 0.12s;
}
.ds-link-btn:hover:not(:disabled) { background: var(--brand-soft); }
.ds-link-btn:disabled { color: var(--text-4); cursor: not-allowed; }
</style>
