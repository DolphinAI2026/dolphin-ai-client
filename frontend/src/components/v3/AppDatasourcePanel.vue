<!-- AppDatasourcePanel.vue — design-v4 Q2: 应用数据源 tab.

  替 ChatPage.vue 顶部 4 tab 中 "数据源" tab 的内容.
  纯只读 — 列出本应用关联的数据源 (拉自 backend /applications/{id}/datasources).

  设计:
  - 顶部 header: 应用名 + 描述
  - 主表格: 数据源名 / 类型 / host:port / 关联模型数 / 状态 / 操作
  - 空态 + 加载 + 错误重试齐全
  - "切换 / 关联" 是 P5 (写权限) — 当前 read-only 只显查看详情按钮 (placeholder)

  ⚠️ backend endpoint 不一定已上线 — 加 fallback 兜底:
     - 404 / TOOL_NOT_AVAILABLE → 友好空态 + 文案提示
     - APP_NOT_DEPLOYED → 友好空态 "应用未部署到平台"

  视觉对齐 design-v3 token 系 (--brand / --surface / --line / var(--text*)).
-->
<template>
  <section class="ads" aria-label="应用数据源">
    <header class="ads-head">
      <div class="ads-head-meta">
        <h1 class="ads-title">数据源</h1>
        <p class="ads-desc">
          管理「<strong>{{ appDisplayName }}</strong>」用到的数据源 — 切换 / 关联 / 表结构.
        </p>
      </div>
      <div class="ads-head-actions">
        <button class="ads-btn ads-btn-ghost" :disabled="loading" @click="reload">
          <span class="ads-btn-icon">⟲</span> 刷新
        </button>
      </div>
    </header>

    <!-- loading -->
    <div v-if="loading" class="ads-state">
      <div class="ads-spinner" /> 加载中…
    </div>

    <!-- error (网络 / 5xx) -->
    <div v-else-if="error" class="ads-state ads-state-err">
      <div class="ads-state-icon"><AppIcon name="warning" :size="40" /></div>
      <p>{{ error }}</p>
      <button class="ads-btn ads-btn-ghost" @click="reload">重试</button>
    </div>

    <!-- 业务降级 (app_not_deployed / tool_not_available / 4xx) — 友好空态 + 提示 -->
    <div v-else-if="businessNote" class="ads-state">
      <div class="ads-state-icon"><AppIcon :name="businessNoteIcon" :size="40" /></div>
      <p>{{ businessNote }}</p>
      <div class="ads-empty-actions">
        <button class="ads-btn ads-btn-primary" @click="goPlatformAdmin">
          去 平台管理 → 数据源
        </button>
        <button class="ads-btn ads-btn-ghost" @click="reload">重试</button>
      </div>
    </div>

    <!-- 空态: 真没数据源 -->
    <div v-else-if="items.length === 0" class="ads-state">
      <div class="ads-state-icon"><AppIcon name="database" :size="40" /></div>
      <p>该应用还未关联任何数据源</p>
      <p class="hint">部署应用 / 配置模型后会显示这里关联的数据源.</p>
      <div class="ads-empty-actions">
        <button class="ads-btn ads-btn-primary" @click="goPlatformAdmin">
          去 平台管理 → 数据源
        </button>
      </div>
    </div>

    <!-- 主表格 -->
    <template v-else>
      <div class="ads-table-wrap">
        <table class="ads-table">
          <thead>
            <tr>
              <th class="col-name">数据源名称</th>
              <th class="col-type">类型</th>
              <th class="col-conn">连接</th>
              <th class="col-models">关联模型</th>
              <th class="col-status">状态</th>
              <th class="col-actions">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(it, i) in items"
              :key="(it.datasource_id || `unknown-${i}`) + '-' + i"
              class="ads-row"
            >
              <td class="col-name">
                <div class="ads-name">{{ it.name || '—' }}</div>
                <div class="ads-name-id mono">{{ it.datasource_id }}</div>
              </td>
              <td class="col-type">
                <span class="ads-type-chip" :class="`ads-type-${typeKey(it.type)}`">
                  {{ it.type || '未知' }}
                </span>
              </td>
              <td class="col-conn mono">
                <template v-if="it.host">
                  {{ it.host }}<template v-if="it.port">:{{ it.port }}</template>
                </template>
                <span v-else class="ads-dim">—</span>
              </td>
              <td class="col-models">
                <span class="ads-count">{{ it.model_count }}</span>
              </td>
              <td class="col-status">
                <span
                  class="ads-status-chip"
                  :class="onlineClass(it.is_online)"
                >{{ onlineLabel(it.is_online) }}</span>
              </td>
              <td class="col-actions">
                <button
                  class="ads-btn ads-btn-link"
                  title="查看数据源详情 (P5 — 当前跳平台管理)"
                  @click="goPlatformAdmin"
                >
                  查看详情
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="ads-footer">
        <span class="ads-footer-hint">
          共 <b>{{ total }}</b> 个数据源 · 编辑 / 新建请去
          <a class="ads-link" href="#" @click.prevent="goPlatformAdmin">平台管理</a>
        </span>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import request from '@/utils/request'
import { usePreviewStore } from '@/stores/preview'
import AppIcon from '@/components/common/AppIcon.vue'

interface DatasourceItem {
  datasource_id: string
  name: string
  type: string  // MySQL / PostgreSQL / Mongo / ...
  host: string | null
  port: number | null
  model_count: number
  is_online: boolean | null
}

const props = defineProps<{
  appId: number
}>()

const store = usePreviewStore()
const router = useRouter()

const items = ref<DatasourceItem[]>([])
const total = ref(0)
const loading = ref(false)
const error = ref('')                  // 网络 / 5xx 系统错
const businessNote = ref('')           // app_not_deployed / tool_not_available 等业务降级
const businessNoteIcon = ref('bulb')

const appDisplayName = computed(() =>
  store.preview.appName || `应用 ${props.appId}`,
)

function typeKey(t: string): string {
  const lo = (t || '').toLowerCase()
  if (lo.includes('mysql')) return 'mysql'
  if (lo.includes('postgres') || lo === 'pg') return 'pg'
  if (lo.includes('mongo')) return 'mongo'
  if (lo.includes('oracle')) return 'oracle'
  if (lo.includes('sqlserver') || lo.includes('mssql')) return 'mssql'
  if (lo.includes('dameng') || lo.includes('kingbase')) return 'cn-db'
  return 'other'
}

function onlineClass(v: boolean | null): string {
  if (v === true) return 'ads-status-ok'
  if (v === false) return 'ads-status-err'
  return 'ads-status-neutral'
}
function onlineLabel(v: boolean | null): string {
  if (v === true) return '在线'
  if (v === false) return '离线'
  return '未知'
}

async function reload() {
  if (!props.appId) return
  loading.value = true
  error.value = ''
  businessNote.value = ''
  try {
    const resp = await request.get<any, any>(
      `/applications/${props.appId}/datasources`,
    )
    if (resp?.ok) {
      items.value = (resp.items || []) as DatasourceItem[]
      total.value = resp.total || items.value.length
    } else {
      // 业务降级 — 不当 error 显, 走 friendly 空态.
      const code = String(resp?.error_code || '')
      const msg = String(resp?.message || '未知失败')
      items.value = []
      total.value = 0
      if (code === 'APP_NOT_DEPLOYED') {
        businessNote.value = msg || '应用尚未部署到 aPaaS 平台 — 部署后才能拉数据源'
        businessNoteIcon.value = 'warning'
      } else if (code === 'TOOL_NOT_AVAILABLE' || code === 'TOOL_SIGNATURE_MISMATCH') {
        businessNote.value = '后端数据源 API 尚未就绪 — 请到平台管理查看完整数据源.'
        businessNoteIcon.value = 'wrench'
      } else {
        businessNote.value = msg
        businessNoteIcon.value = 'warning'
      }
    }
  } catch (e: any) {
    const status = e?.response?.status
    if (status === 404) {
      // backend endpoint 还没部署 — friendly fallback
      items.value = []
      total.value = 0
      businessNote.value = '后端数据源接口未上线 — 请到平台管理查看数据源.'
      businessNoteIcon.value = 'wrench'
    } else {
      error.value = e?.response?.data?.detail || e?.message || '网络错误'
    }
  } finally {
    loading.value = false
  }
}

function goPlatformAdmin() {
  router.push('/platform-admin').catch(() => {})
}

watch(() => props.appId, () => { reload() }, { immediate: true })
</script>

<style scoped>
.ads {
  font-family: var(--font-sans);
  color: var(--text);
  background: var(--bg);
  height: 100%;
  display: flex;
  flex-direction: column;
  font-feature-settings: 'cv11', 'ss01';
  overflow: hidden;
}

/* ── header ──────────────────────────────────────────────────────────── */
.ads-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 20px 32px;
  border-bottom: 1px solid var(--line);
  background: var(--surface);
}
.ads-title {
  margin: 0 0 4px;
  font-size: 22px;
  font-weight: 600;
  color: var(--text);
}
.ads-desc {
  margin: 0;
  font-size: 12.5px;
  color: var(--text-3);
}
.ads-desc strong {
  color: var(--text);
  font-weight: 600;
}
.ads-head-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

/* ── states ──────────────────────────────────────────────────────────── */
.ads-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--text-3);
  font-size: 13px;
  padding: 48px 16px;
}
.ads-state-icon { font-size: 40px; opacity: 0.75; }
.ads-state .hint { font-size: 12px; color: var(--text-4); margin: 0; }
.ads-state-err { color: var(--err); }
.ads-empty-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}
.ads-spinner {
  width: 18px; height: 18px;
  border: 2px solid var(--line-strong);
  border-top-color: var(--brand);
  border-radius: 50%;
  animation: ads-spin 0.9s linear infinite;
}
@keyframes ads-spin { to { transform: rotate(360deg); } }

/* ── table ───────────────────────────────────────────────────────────── */
.ads-table-wrap {
  flex: 1;
  overflow: auto;
  padding: 16px 32px;
}
.ads-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: hidden;
}
.ads-table th {
  text-align: left;
  padding: 11px 14px;
  background: var(--surface-2);
  font-weight: 500;
  color: var(--text-3);
  font-size: 12px;
  border-bottom: 1px solid var(--line);
  position: sticky;
  top: 0;
}
.ads-table td {
  padding: 11px 14px;
  border-bottom: 1px solid var(--line);
  vertical-align: middle;
}
.ads-row:hover td { background: var(--surface-2); }

.col-name { width: 26%; }
.col-type { width: 110px; }
.col-conn { width: 28%; }
.col-models { width: 100px; text-align: center; }
.col-status { width: 90px; text-align: center; }
.col-actions { width: 110px; text-align: right; }

.ads-name {
  font-weight: 500;
  color: var(--text);
}
.ads-name-id {
  font-size: 11px;
  color: var(--text-4);
  margin-top: 2px;
}
.mono {
  font-family: var(--font-mono);
  font-size: 12px;
}
.ads-dim {
  color: var(--text-4);
}

/* type chip — color-coded per db type */
.ads-type-chip {
  display: inline-block;
  padding: 1.5px 8px;
  border-radius: 4px;
  font-size: 11.5px;
  font-weight: 500;
  background: var(--brand-soft);
  color: var(--brand);
}
.ads-type-mysql   { background: rgba(0, 117, 143, 0.10); color: #00758f; }
.ads-type-pg      { background: rgba(50, 100, 165, 0.10); color: #336791; }
.ads-type-mongo   { background: rgba(76, 154, 71, 0.10); color: #4ca64c; }
.ads-type-oracle  { background: rgba(193, 31, 38, 0.10); color: #c11f26; }
.ads-type-mssql   { background: rgba(165, 89, 0, 0.10); color: #a55900; }
.ads-type-cn-db   { background: rgba(110, 60, 160, 0.10); color: #6e3ca0; }
.ads-type-other   { background: var(--surface-2); color: var(--text-3); }

.ads-count {
  display: inline-block;
  min-width: 28px;
  padding: 1.5px 8px;
  border-radius: 999px;
  background: var(--surface-2);
  color: var(--text-2);
  font-size: 12px;
  font-weight: 500;
  font-family: var(--font-mono);
}

.ads-status-chip {
  display: inline-block;
  padding: 1.5px 10px;
  border-radius: 999px;
  font-size: 11.5px;
  font-weight: 500;
}
.ads-status-ok { background: var(--ok-soft); color: var(--ok); }
.ads-status-err { background: var(--err-soft); color: var(--err); }
.ads-status-neutral { background: var(--surface-2); color: var(--text-3); }

/* ── buttons ─────────────────────────────────────────────────────────── */
.ads-btn {
  height: 30px;
  padding: 0 14px;
  border-radius: 6px;
  font-size: 12.5px;
  font-family: inherit;
  cursor: pointer;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--text);
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.ads-btn:disabled { opacity: 0.55; cursor: not-allowed; }
.ads-btn-ghost:hover:not(:disabled) {
  border-color: var(--brand);
  color: var(--brand);
}
.ads-btn-primary {
  background: var(--brand);
  color: #fff;
  border-color: var(--brand);
}
.ads-btn-primary:hover:not(:disabled) {
  filter: brightness(1.06);
}
.ads-btn-link {
  height: auto;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--brand);
  font-weight: 500;
}
.ads-btn-link:hover { text-decoration: underline; }
.ads-btn-icon { font-size: 13px; line-height: 1; }

/* ── footer ──────────────────────────────────────────────────────────── */
.ads-footer {
  padding: 12px 32px;
  border-top: 1px solid var(--line);
  background: var(--surface);
  font-size: 12px;
  color: var(--text-3);
  text-align: right;
}
.ads-footer-hint b {
  color: var(--text);
  font-weight: 600;
}
.ads-link {
  color: var(--brand);
  text-decoration: none;
}
.ads-link:hover { text-decoration: underline; }
</style>
