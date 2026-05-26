<!-- ApisView.vue — 接口统一管理 (design-v4 Phase I1, 2026-05-26).

  替换 G3 stub. 复用现有 endpoint:
    - 平台内接口 → /api/applications/{id}/section-content/business-events (per-app)
    - HTTP / Webhook → P6 接入 (apaas 平台 raw API 复杂, 暂用 mock 示例)

  视觉对齐 DatasourcesView.vue (H3 pattern):
    - 顶部 header + stats line
    - 4 sub-tab (active 蓝 border-bottom)
    - table (var(--surface) bg + var(--line) border)
    - 严格 design-v3 token

  P6 留尾: 跨应用业务事件聚合 + 真 HTTP 接口管理.
-->
<template>
  <main class="ds-page">
    <!-- 顶部 header -->
    <header class="ds-head">
      <div class="ds-head-meta">
        <h1 class="ds-title">接口</h1>
        <p class="ds-stats">
          <span>{{ totalCount }} 个接口</span>
          <span class="ds-stat-sep">·</span>
          <span>{{ externalCount }} 个外部</span>
          <span class="ds-stat-sep">·</span>
          <span>{{ internalCount }} 个内部</span>
        </p>
      </div>
      <div class="ds-head-actions">
        <button class="ds-btn ds-btn-ghost" disabled title="P6 接入 — 通用新增接口入口">
          <span class="ds-btn-icon">+</span>
          新增接口
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
      <div v-else-if="filteredApis.length === 0" class="ds-empty">
        <div class="ds-empty-icon">🔌</div>
        <h3>暂无接口</h3>
        <p>P6 接入 — 真接口数据从「平台内业务事件 / 外部 HTTP / Webhook」汇聚.</p>
        <p class="ds-empty-hint">配置助手: 选「接口」面板创建</p>
      </div>
      <div v-else class="ds-table-wrap">
        <table class="ds-table">
          <thead>
            <tr>
              <th class="num">#</th>
              <th class="col-name">名称</th>
              <th class="col-path">路径</th>
              <th class="col-method">方法</th>
              <th class="col-kind">类型</th>
              <th class="col-app">所属应用</th>
              <th class="col-status">状态</th>
              <th class="col-ops">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(api, i) in filteredApis" :key="api.id">
              <td class="num">{{ i + 1 }}</td>
              <td class="col-name">
                <div class="ds-cell-name">{{ api.name }}</div>
                <div v-if="api.description" class="ds-cell-desc">{{ api.description }}</div>
              </td>
              <td class="col-path mono">{{ api.path }}</td>
              <td class="col-method">
                <span class="ds-method-chip" :class="`m-${api.method.toLowerCase()}`">
                  {{ api.method }}
                </span>
              </td>
              <td class="col-kind">
                <span class="ds-badge ds-badge-kind mono">{{ api.kindLabel }}</span>
              </td>
              <td class="col-app mono muted">{{ api.appName || '—' }}</td>
              <td class="col-status">
                <span class="ds-status-chip" :class="api.status === 'active' ? 'ok' : 'unverified'">
                  {{ api.status === 'active' ? '正常' : '草稿' }}
                </span>
              </td>
              <td class="col-ops">
                <button class="ds-link-btn" disabled title="P6 接入">详情</button>
                <button class="ds-link-btn" disabled title="P6 接入">测试</button>
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
import { ElMessage } from 'element-plus'

type SubCode = 'all' | 'http' | 'internal' | 'webhook'

interface ApiItem {
  id: string
  name: string
  description?: string
  path: string
  method: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH'
  kind: 'http' | 'internal' | 'webhook'
  kindLabel: string
  appName?: string
  status: 'active' | 'draft'
}

const subTab = ref<SubCode>('all')
const loading = ref(true)
const apis = ref<ApiItem[]>([])

// 数据源决策: P6 接入真 endpoint 前用 mock 5 条 — 让 UI 有实物可见.
// 跨应用真业务事件聚合需要先列 N 个 app 再逐个调 /section-content/business-events,
// 留 P6 做 (任务说 "mock 3-5 行示例数据" 现阶段 ok).
const MOCK_APIS: ApiItem[] = [
  {
    id: 'mock-1',
    name: '提交借阅申请',
    description: '图书借阅业务事件',
    path: '/api/business-event/borrow-apply/submit',
    method: 'POST',
    kind: 'internal',
    kindLabel: 'EVENT',
    appName: '图书借阅管理',
    status: 'active',
  },
  {
    id: 'mock-2',
    name: '审批通过回调',
    description: '流程节点完成回调',
    path: '/api/business-event/approve/callback',
    method: 'POST',
    kind: 'internal',
    kindLabel: 'EVENT',
    appName: '图书借阅管理',
    status: 'active',
  },
  {
    id: 'mock-3',
    name: '查询用户角色',
    description: '调外部 SSO 系统',
    path: 'https://sso.example.com/api/role',
    method: 'GET',
    kind: 'http',
    kindLabel: 'HTTP',
    appName: '—',
    status: 'draft',
  },
  {
    id: 'mock-4',
    name: '钉钉消息推送',
    description: '事件触发 webhook',
    path: 'https://oapi.dingtalk.com/robot/send',
    method: 'POST',
    kind: 'webhook',
    kindLabel: 'WEBHOOK',
    appName: '—',
    status: 'active',
  },
  {
    id: 'mock-5',
    name: '同步外部 ERP 库存',
    description: '定时拉取库存',
    path: 'https://erp.example.com/api/inventory',
    method: 'GET',
    kind: 'http',
    kindLabel: 'HTTP',
    appName: '—',
    status: 'draft',
  },
]

function loadApis() {
  loading.value = true
  // P6 接入: 真数据从 /api/applications/{id}/section-content/business-events
  // + apaas 平台 raw HTTP API list 汇聚. 当前用 mock.
  setTimeout(() => {
    apis.value = MOCK_APIS
    loading.value = false
  }, 80)
}

const totalCount = computed(() => apis.value.length)
const internalCount = computed(() => apis.value.filter((a) => a.kind === 'internal').length)
const externalCount = computed(
  () => apis.value.filter((a) => a.kind === 'http' || a.kind === 'webhook').length,
)
const httpCount = computed(() => apis.value.filter((a) => a.kind === 'http').length)
const webhookCount = computed(() => apis.value.filter((a) => a.kind === 'webhook').length)

const filteredApis = computed(() => {
  if (subTab.value === 'all') return apis.value
  return apis.value.filter((a) => a.kind === subTab.value)
})

const SUB_TABS = computed<{ code: SubCode; label: string; count: number }[]>(() => [
  { code: 'all', label: '全部', count: totalCount.value },
  { code: 'http', label: 'HTTP', count: httpCount.value },
  { code: 'internal', label: '平台内', count: internalCount.value },
  { code: 'webhook', label: 'Webhook', count: webhookCount.value },
])

onMounted(() => {
  loadApis()
  // 友好提示: 当前是 mock 数据 (避免误导)
  setTimeout(() => {
    ElMessage.info({
      message: '接口管理 P6 接入 — 当前为示例数据, 真接口走「业务事件」配置.',
      duration: 3500,
    })
  }, 500)
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

/* ─── 表头 ─────────────────────────────────────────────────────────────── */
.ds-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 18px;
  padding-bottom: 18px;
  border-bottom: 1px solid var(--line);
}
.ds-head-meta {
  flex: 1;
  min-width: 0;
}
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
.ds-head-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

/* ─── btn ─────────────────────────────────────────────────────────────── */
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
.ds-btn-icon { font-size: 13px; line-height: 1; }

/* ─── sub-tab nav ──────────────────────────────────────────────────────── */
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

/* ─── section ──────────────────────────────────────────────────────────── */
.ds-section { min-height: 200px; }
.ds-state {
  padding: 48px 0;
  text-align: center;
  color: var(--text-3);
  font-size: 13.5px;
}
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
.ds-empty h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--text);
}
.ds-empty p { margin: 0; font-size: 13.5px; max-width: 460px; }
.ds-empty-hint {
  font-size: 12px !important;
  color: var(--text-4);
  margin-top: 6px;
}

/* ─── table ────────────────────────────────────────────────────────────── */
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
.ds-table th.col-name { width: 180px; }
.ds-table th.col-path { width: 280px; }
.ds-table th.col-method { width: 80px; text-align: center; }
.ds-table th.col-kind { width: 100px; }
.ds-table th.col-app { width: 140px; }
.ds-table th.col-status { width: 80px; }
.ds-table th.col-ops { width: 110px; text-align: center; }

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
.ds-table .col-method { text-align: center; }
.ds-table .col-ops { text-align: center; }
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

/* ─── method chip (色按 HTTP verb) ─────────────────────────────────────── */
.ds-method-chip {
  display: inline-block;
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: 4px;
  letter-spacing: 0.04em;
}
.ds-method-chip.m-get    { background: var(--ok-soft);    color: var(--ok); }
.ds-method-chip.m-post   { background: var(--brand-soft); color: var(--brand); }
.ds-method-chip.m-put    { background: var(--warn-soft);  color: var(--warn); }
.ds-method-chip.m-delete { background: var(--err-soft);   color: var(--err); }
.ds-method-chip.m-patch  { background: var(--warn-soft);  color: var(--warn); }

/* ─── kind badge ────────────────────────────────────────────────────────── */
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
.ds-badge-kind {
  background: var(--surface-2);
  color: var(--text-3);
  border: 1px solid var(--line);
}

/* ─── status chip ──────────────────────────────────────────────────────── */
.ds-status-chip {
  display: inline-block;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
  white-space: nowrap;
}
.ds-status-chip.ok       { background: var(--ok-soft);   color: var(--ok); }
.ds-status-chip.unverified { background: var(--warn-soft); color: var(--warn); }

/* ─── link-style 操作 btn ──────────────────────────────────────────────── */
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
.ds-link-btn + .ds-link-btn { margin-left: 4px; }
</style>
