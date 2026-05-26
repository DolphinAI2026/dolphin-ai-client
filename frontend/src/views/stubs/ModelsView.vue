<!-- ModelsView.vue — 数据模型统一管理 (design-v4 Phase I1, 2026-05-26).

  替换 G3 stub. 复用 /api/applications/{id}/section-content/models endpoint.

  数据源决策:
    - 列当前 tenant 所有应用 (applicationApi.list).
    - 用户从顶部 dropdown 选应用 (default: 第一个有 apaas_app_id 的).
    - 拉该应用的 model list (list_apaas_app_models MCP).
    - 跨应用聚合留 P6 (要 backend 新加 /all-models endpoint, 现阶段 dropdown 选择已足够).

  视觉对齐 DatasourcesView.vue (H3 pattern).

  4 sub-tab: 全部 / 主表 / 子表 / 关联模型 (按 model 元数据区分).

  点 row → 跳到 /chat?app_id=X&design_sub=data (数据 schema 编辑器).

  P6 留尾: backend 加 /all-models 跨应用聚合 endpoint.
-->
<template>
  <main class="ds-page">
    <header class="ds-head">
      <div class="ds-head-meta">
        <h1 class="ds-title">数据模型</h1>
        <p class="ds-stats">
          <span>{{ totalCount }} 个模型</span>
          <span class="ds-stat-sep">·</span>
          <span>{{ mainCount }} 主表</span>
          <span class="ds-stat-sep">·</span>
          <span>{{ subCount }} 子表</span>
        </p>
      </div>
      <div class="ds-head-actions">
        <select
          v-model.number="selectedAppId"
          class="ds-app-select"
          :disabled="apps.length === 0"
          @change="loadModels"
        >
          <option v-if="apps.length === 0" :value="0">无应用</option>
          <option v-for="a in apps" :key="a.id" :value="a.id">
            {{ a.app_name }}{{ !a.apaas_app_id ? ' (未部署)' : '' }}
          </option>
        </select>
        <button class="ds-btn ds-btn-ghost" @click="goToSchemaEditor" :disabled="!selectedAppId">
          <span class="ds-btn-icon">+</span>
          新建模型
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
      <div v-if="loading" class="ds-state">加载中…</div>
      <div v-else-if="error" class="ds-state ds-state-err">
        {{ error }}
        <button class="ds-btn ds-btn-ghost" @click="loadModels">重试</button>
      </div>
      <div v-else-if="!selectedAppId" class="ds-empty">
        <div class="ds-empty-icon">🗂️</div>
        <h3>选择应用查看模型</h3>
        <p>右上选应用 dropdown 拉模型 list. 跨应用聚合 P6 接入.</p>
      </div>
      <div v-else-if="filteredModels.length === 0" class="ds-empty">
        <div class="ds-empty-icon">🗂️</div>
        <h3>{{ currentAppHasNoApaas ? '应用未部署' : '暂无模型' }}</h3>
        <p>
          {{ currentAppHasNoApaas
            ? '该应用尚未部署到 apaas 平台, 部署后才能列模型.'
            : '前往设计页用 FormBuilder 创建模型.' }}
        </p>
        <button v-if="!currentAppHasNoApaas" class="ds-btn ds-btn-primary" @click="goToSchemaEditor">前往新建</button>
      </div>
      <div v-else class="ds-table-wrap">
        <table class="ds-table">
          <thead>
            <tr>
              <th class="num">#</th>
              <th class="col-name">名称</th>
              <th class="col-code">Code</th>
              <th class="col-type">类型</th>
              <th class="col-fields">字段数</th>
              <th class="col-relation">关联表</th>
              <th class="col-status">状态</th>
              <th class="col-ops">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(m, i) in filteredModels" :key="m.id" class="clickable" @click="openSchemaEditor(m)">
              <td class="num">{{ i + 1 }}</td>
              <td class="col-name">
                <div class="ds-cell-name">{{ m.name }}</div>
                <div v-if="m.description" class="ds-cell-desc">{{ m.description }}</div>
              </td>
              <td class="col-code mono">{{ m.code || '—' }}</td>
              <td class="col-type">
                <span class="ds-badge ds-badge-db mono">{{ m.typeLabel }}</span>
              </td>
              <td class="col-fields mono">{{ m.fieldCount }}</td>
              <td class="col-relation mono muted">{{ m.relationLabel }}</td>
              <td class="col-status">
                <span class="ds-status-chip ok">已部署</span>
              </td>
              <td class="col-ops" @click.stop>
                <button class="ds-link-btn" @click="openSchemaEditor(m)" title="进入 schema 编辑器">编辑</button>
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
import { applicationApi } from '@/api/application'
import request from '@/utils/request'
import type { MergedApplication } from '@/types'
import { ElMessage } from 'element-plus'

type SubCode = 'all' | 'main' | 'sub' | 'relation'

interface ModelItem {
  id: string
  name: string
  code: string
  description?: string
  /** sub_table => 'sub'; relation => 'relation'; else 'main' */
  category: 'main' | 'sub' | 'relation'
  typeLabel: string
  fieldCount: number
  relationLabel: string
}

const router = useRouter()
const subTab = ref<SubCode>('all')
const loading = ref(false)
const error = ref('')

const apps = ref<MergedApplication[]>([])
const selectedAppId = ref<number>(0)
const models = ref<ModelItem[]>([])

async function loadApps() {
  try {
    const list = await applicationApi.list()
    apps.value = (list || []).filter((a: any) => !isNaN(Number(a.id)))
    // 默认选第一个有 apaas_app_id 的应用 (能拉真模型)
    const firstDeployed = apps.value.find((a) => a.apaas_app_id) || apps.value[0]
    if (firstDeployed) {
      selectedAppId.value = Number(firstDeployed.id)
      await loadModels()
    }
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '加载应用失败'
  }
}

function classifyModel(extra: any): { category: 'main' | 'sub' | 'relation'; typeLabel: string } {
  // 推断主表/子表: apaas extra 字段可能是 sub_table_flag / model_type / parent_id
  const isSubTable = !!(extra?.sub_table_flag || extra?.parent_model_id || extra?.is_sub_table)
  const isRelation = !!(extra?.relation_type || extra?.model_type === 'RELATION')
  if (isRelation) return { category: 'relation', typeLabel: 'RELATION' }
  if (isSubTable) return { category: 'sub', typeLabel: 'SUB' }
  return { category: 'main', typeLabel: 'DATABASE' }
}

function toModelItem(raw: any): ModelItem {
  const extra = raw.extra || {}
  const cls = classifyModel(extra)
  const fieldsArr: any[] = Array.isArray(extra.fields) ? extra.fields : []
  const relations: any[] = Array.isArray(extra.relations) ? extra.relations : []
  return {
    id: String(raw.id || ''),
    name: raw.name || '',
    code: raw.code || '',
    description: extra.description || extra.remark || '',
    category: cls.category,
    typeLabel: cls.typeLabel,
    fieldCount: fieldsArr.length || (typeof extra.field_count === 'number' ? extra.field_count : 0),
    relationLabel: relations.length > 0 ? `${relations.length} 个` : '—',
  }
}

async function loadModels() {
  if (!selectedAppId.value) {
    models.value = []
    return
  }
  loading.value = true
  error.value = ''
  try {
    const res: any = await request.get(
      `/applications/${selectedAppId.value}/section-content/models`,
      { params: { with_fields: false } },
    )
    if (res && res.ok && Array.isArray(res.items)) {
      models.value = res.items.map(toModelItem)
    } else {
      models.value = []
      if (res?.error_code) {
        // 应用未部署等友好提示
        if (res.error_code !== 'APP_NOT_DEPLOYED') {
          ElMessage.warning(res.message || `加载失败 (${res.error_code})`)
        }
      }
    }
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '加载失败'
    models.value = []
  } finally {
    loading.value = false
  }
}

const currentApp = computed(() => apps.value.find((a) => Number(a.id) === selectedAppId.value))
const currentAppHasNoApaas = computed(() => !!currentApp.value && !currentApp.value.apaas_app_id)

const totalCount = computed(() => models.value.length)
const mainCount = computed(() => models.value.filter((m) => m.category === 'main').length)
const subCount = computed(() => models.value.filter((m) => m.category === 'sub').length)
const relationCount = computed(() => models.value.filter((m) => m.category === 'relation').length)

const filteredModels = computed(() => {
  if (subTab.value === 'all') return models.value
  return models.value.filter((m) => m.category === subTab.value)
})

const SUB_TABS = computed<{ code: SubCode; label: string; count: number }[]>(() => [
  { code: 'all', label: '全部', count: totalCount.value },
  { code: 'main', label: '主表', count: mainCount.value },
  { code: 'sub', label: '子表', count: subCount.value },
  { code: 'relation', label: '关联模型', count: relationCount.value },
])

function openSchemaEditor(m: ModelItem) {
  if (!selectedAppId.value) return
  // 跳到 ChatPage 的数据 schema 编辑器
  router.push({
    path: '/chat',
    query: {
      app_id: String(selectedAppId.value),
      design_sub: 'data',
      model_id: m.id,
    },
  })
}

function goToSchemaEditor() {
  if (!selectedAppId.value) return
  router.push({
    path: '/chat',
    query: { app_id: String(selectedAppId.value), design_sub: 'data' },
  })
}

onMounted(() => {
  loadApps()
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
.ds-head-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
  align-items: center;
}

.ds-app-select {
  height: 32px;
  padding: 0 10px;
  border-radius: 6px;
  border: 1px solid var(--line-strong);
  background: var(--surface);
  color: var(--text);
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
  min-width: 180px;
  max-width: 260px;
  transition: border-color 0.12s;
}
.ds-app-select:hover { border-color: var(--brand); }
.ds-app-select:focus { outline: 1px solid var(--brand); outline-offset: -1px; }
.ds-app-select:disabled { opacity: 0.5; cursor: not-allowed; }

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
.ds-table th.col-name { width: 240px; }
.ds-table th.col-code { width: 140px; }
.ds-table th.col-type { width: 110px; }
.ds-table th.col-fields { width: 70px; text-align: center; }
.ds-table th.col-relation { width: 90px; text-align: center; }
.ds-table th.col-status { width: 90px; }
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
.ds-table tr.clickable { cursor: pointer; }
.ds-table tr:hover td { background: var(--surface-2); }
.ds-table .num { color: var(--text-4); text-align: center; }
.ds-table .col-ops { text-align: center; }
.ds-table .col-fields { text-align: center; }
.ds-table .col-relation { text-align: center; }
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
.ds-badge-db {
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
.ds-status-chip.ok { background: var(--ok-soft); color: var(--ok); }

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
