<!-- ReportsView.vue — 报表统一管理 (design-v4 Phase I1, 2026-05-26).

  替换 G3 stub. apaas 平台 reports / dashboard API 复杂, 当前用 mock 5 行示例数据.

  视觉对齐 DatasourcesView.vue (H3 pattern).

  4 sub-tab: 看板 / 列表报表 / 图表报表 / 数据导出

  P6 留尾: 接 apaas 平台 reports API + 真 dashboard 配置.
-->
<template>
  <main class="ds-page">
    <header class="ds-head">
      <div class="ds-head-meta">
        <h1 class="ds-title">报表</h1>
        <p class="ds-stats">
          <span>{{ totalCount }} 个报表</span>
          <span class="ds-stat-sep">·</span>
          <span>{{ dashboardCount }} 个仪表盘</span>
          <span v-if="exportCount > 0" class="ds-stat-sep">·</span>
          <span v-if="exportCount > 0" class="ds-stat-muted">{{ exportCount }} 个导出任务</span>
        </p>
      </div>
      <div class="ds-head-actions">
        <button class="ds-btn ds-btn-ghost" disabled title="P6 接入 — 创建报表入口">
          <span class="ds-btn-icon">+</span>
          新建报表
        </button>
      </div>
    </header>

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

    <section class="ds-section">
      <div v-if="filteredReports.length === 0" class="ds-empty">
        <div class="ds-empty-icon">📊</div>
        <h3>暂无报表</h3>
        <p>P6 接入 — 接 apaas 平台 reports API. 真 dashboard 编排走配置助手.</p>
        <p class="ds-empty-hint">配置助手: 选「报表」面板创建</p>
      </div>
      <div v-else class="ds-table-wrap">
        <table class="ds-table">
          <thead>
            <tr>
              <th class="num">#</th>
              <th class="col-name">名称</th>
              <th class="col-type">类型</th>
              <th class="col-source">数据源</th>
              <th class="col-owner">所有者</th>
              <th class="col-time">更新时间</th>
              <th class="col-status">状态</th>
              <th class="col-ops">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(r, i) in filteredReports" :key="r.id">
              <td class="num">{{ i + 1 }}</td>
              <td class="col-name">
                <div class="ds-cell-name">{{ r.name }}</div>
                <div v-if="r.description" class="ds-cell-desc">{{ r.description }}</div>
              </td>
              <td class="col-type">
                <span class="ds-badge ds-badge-type mono">{{ r.typeLabel }}</span>
              </td>
              <td class="col-source mono muted">{{ r.dataSource }}</td>
              <td class="col-owner muted">{{ r.owner }}</td>
              <td class="col-time mono muted">{{ r.updatedAt }}</td>
              <td class="col-status">
                <span class="ds-status-chip" :class="r.status === 'published' ? 'ok' : 'unverified'">
                  {{ r.status === 'published' ? '已发布' : '草稿' }}
                </span>
              </td>
              <td class="col-ops">
                <button class="ds-link-btn" disabled title="P6 接入">查看</button>
                <button class="ds-link-btn" disabled title="P6 接入">编辑</button>
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

type SubCode = 'dashboard' | 'list' | 'chart' | 'export'

interface ReportItem {
  id: string
  name: string
  description?: string
  type: SubCode
  typeLabel: string
  dataSource: string
  owner: string
  updatedAt: string
  status: 'published' | 'draft'
}

const subTab = ref<SubCode>('dashboard')

// 数据源决策: P6 接入真 apaas reports API 前用 mock 5 条.
const MOCK_REPORTS: ReportItem[] = [
  {
    id: 'r-1',
    name: '借阅数据看板',
    description: '实时显示借出/归还/逾期数量',
    type: 'dashboard',
    typeLabel: 'DASHBOARD',
    dataSource: '图书借阅',
    owner: '张三',
    updatedAt: '2026-05-26',
    status: 'published',
  },
  {
    id: 'r-2',
    name: '月度借阅明细',
    description: '按月汇总, 支持下钻',
    type: 'list',
    typeLabel: 'LIST',
    dataSource: '图书借阅',
    owner: '李四',
    updatedAt: '2026-05-25',
    status: 'published',
  },
  {
    id: 'r-3',
    name: '热门图书排行',
    description: '柱图 - top 20',
    type: 'chart',
    typeLabel: 'CHART',
    dataSource: '图书借阅',
    owner: '王五',
    updatedAt: '2026-05-24',
    status: 'published',
  },
  {
    id: 'r-4',
    name: '逾期分布饼图',
    description: '按部门统计逾期比例',
    type: 'chart',
    typeLabel: 'CHART',
    dataSource: '图书借阅',
    owner: '王五',
    updatedAt: '2026-05-23',
    status: 'draft',
  },
  {
    id: 'r-5',
    name: '年度导出任务',
    description: '定时导出全年明细到 Excel',
    type: 'export',
    typeLabel: 'EXPORT',
    dataSource: '图书借阅',
    owner: '系统',
    updatedAt: '2026-05-20',
    status: 'published',
  },
]

const reports = ref<ReportItem[]>(MOCK_REPORTS)

const totalCount = computed(() => reports.value.length)
const dashboardCount = computed(() => reports.value.filter((r) => r.type === 'dashboard').length)
const listCount = computed(() => reports.value.filter((r) => r.type === 'list').length)
const chartCount = computed(() => reports.value.filter((r) => r.type === 'chart').length)
const exportCount = computed(() => reports.value.filter((r) => r.type === 'export').length)

const filteredReports = computed(() => reports.value.filter((r) => r.type === subTab.value))

const SUB_TABS = computed<{ code: SubCode; label: string; count: number }[]>(() => [
  { code: 'dashboard', label: '看板', count: dashboardCount.value },
  { code: 'list', label: '列表报表', count: listCount.value },
  { code: 'chart', label: '图表报表', count: chartCount.value },
  { code: 'export', label: '数据导出', count: exportCount.value },
])

onMounted(() => {
  setTimeout(() => {
    ElMessage.info({
      message: '报表管理 P6 接入 — 当前为示例数据, 真 dashboard 走 apaas 平台 reports API.',
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
.ds-empty-hint { font-size: 12px !important; color: var(--text-4); margin-top: 6px; }

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
.ds-table th.col-name { width: 240px; }
.ds-table th.col-type { width: 110px; }
.ds-table th.col-source { width: 140px; }
.ds-table th.col-owner { width: 90px; }
.ds-table th.col-time { width: 110px; }
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
.ds-badge-type {
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
.ds-link-btn + .ds-link-btn { margin-left: 4px; }
</style>
