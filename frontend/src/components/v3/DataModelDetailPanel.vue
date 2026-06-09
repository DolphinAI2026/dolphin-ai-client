<!-- DataModelDetailPanel.vue — Native 模型详情面板 (替代 apaas iframe).

  PR2b-followup D-1 (2026-05-26): SectionNav 数据/数据模型 点击模型后, 右侧主区域
  显本面板, 不再走 apaas iframe. 视觉跟 supperagent Claude design 对齐:
    - Geist 字体 + 蓝色 (#1f72d4 系)
    - 卡片 + 透明背景 + 细 border
    - 顶部模型名 + 元信息 + 编辑按钮
    - 表格: 字段 (编码/名称/类型/长度/注释/状态/操作)

  数据源: GET /api/applications/{app_id}/section-content/models?with_fields=true
  (P0 复用现有 endpoint — 暂时全字段 fetch, 后续若需 detail-only 单独 endpoint 再加)

  CRUD: P0 仅支持查看; P1 接 add_apaas_model_field / update_apaas_model_field /
  delete_apaas_model_field MCP 工具.
-->
<template>
  <section class="dmd" aria-label="数据模型详情">
    <!-- 顶部: 模型名 + 编辑 + 创建时间 -->
    <header class="dmd-head">
      <button class="dmd-back" @click="$emit('back')" title="返回模型列表">
        <span class="dmd-back-icon">‹</span>
        <span>数据模型详情</span>
      </button>
    </header>

    <div v-if="loading" class="dmd-state">加载中…</div>
    <div v-else-if="error" class="dmd-state dmd-state-err">
      {{ error }}
      <button class="dmd-btn" @click="() => reload()">重试</button>
    </div>
    <template v-else>
      <!-- 模型卡片 -->
      <div class="dmd-card">
        <div class="dmd-badge">
          <span class="dmd-badge-text">{{ shortBadge }}</span>
        </div>
        <div class="dmd-meta">
          <h2 class="dmd-name">
            {{ model.model_name || '未命名' }}
            <button class="dmd-edit-btn" title="编辑模型名" @click="onEditName">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
              </svg>
            </button>
          </h2>
          <div class="dmd-chips">
            <span class="dmd-chip">创建人: {{ model.created_by || '管理' }}</span>
            <span class="dmd-chip">创建时间: {{ formatTime(model.created_at) || '—' }}</span>
            <span v-if="model.model_code" class="dmd-chip mono">{{ model.model_code }}</span>
          </div>
        </div>
      </div>

      <!-- 字段区 -->
      <div class="dmd-fields-head">
        <h3 class="dmd-fields-title">模型字段</h3>
        <div class="dmd-fields-actions">
          <div class="dmd-search">
            <svg class="dmd-search-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="11" cy="11" r="7"/>
              <path d="m21 21-4.3-4.3"/>
            </svg>
            <input v-model="searchKw" placeholder="输入字段编码和名称 回车进行搜索" />
          </div>
          <button class="dmd-btn dmd-btn-ghost" disabled title="P1 接入 — 当前请用 AI 助手批量改">批量编辑</button>
          <button class="dmd-btn dmd-btn-primary" disabled title="P1 接入 — 当前请用 AI 助手新增">+ 新增字段</button>
        </div>
      </div>

      <div class="dmd-table-wrap">
        <table class="dmd-table">
          <thead>
            <tr>
              <th class="num">#</th>
              <th>编码</th>
              <th>名称</th>
              <th>类型</th>
              <th>长度</th>
              <th>注释</th>
              <th>状态</th>
              <th class="ops">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="filteredFields.length === 0">
              <td colspan="8" class="empty">
                <p v-if="searchKw">无匹配「{{ searchKw }}」</p>
                <template v-else>
                  <p>该模型暂无字段</p>
                  <p class="hint">用配置助手新建字段</p>
                </template>
              </td>
            </tr>
            <tr v-for="(f, i) in filteredFields" :key="f.field_id || f.field_code || i">
              <td class="num">{{ i + 1 }}</td>
              <td class="mono">{{ f.field_code || f.code || '—' }}</td>
              <td>{{ f.field_name || f.name || '—' }}</td>
              <td>{{ formatFieldType(f) }}</td>
              <td>{{ f.length || f.size || '—' }}</td>
              <td>{{ f.description || f.comment || f.note || '—' }}</td>
              <td>
                <span class="dmd-state-chip" :class="isEnabled(f) ? 'on' : 'off'">
                  {{ isEnabled(f) ? '启用' : '停用' }}
                </span>
              </td>
              <td class="ops">
                <button class="dmd-icon-btn" disabled title="P1: 编辑字段">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                  </svg>
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="dmd-foot">
        <span class="dmd-foot-count">共 {{ fields.length }} 条</span>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import request from '@/utils/request'

const props = defineProps<{
  appId: number
  modelId: string
  refreshNonce?: number
}>()

defineEmits<{
  (e: 'back'): void
}>()

interface FieldRow {
  field_id?: string
  field_code?: string
  code?: string
  field_name?: string
  name?: string
  field_type?: string
  type?: string
  length?: number | string
  size?: number | string
  description?: string
  comment?: string
  note?: string
  enabled?: boolean
  status?: string
  [k: string]: any
}

interface ModelDetail {
  model_id: string
  model_name: string
  model_code: string
  created_by?: string
  created_at?: string
  fields?: FieldRow[]
  [k: string]: any
}

const model = ref<ModelDetail>({ model_id: '', model_name: '', model_code: '' })
const fields = ref<FieldRow[]>([])
const loading = ref(false)
const error = ref('')
const searchKw = ref('')

const shortBadge = computed(() => {
  const n = (model.value.model_name || '').slice(0, 4)
  return n || 'M'
})

const filteredFields = computed(() => {
  const kw = searchKw.value.trim().toLowerCase()
  if (!kw) return fields.value
  return fields.value.filter(f =>
    (f.field_code || f.code || '').toLowerCase().includes(kw)
    || (f.field_name || f.name || '').toLowerCase().includes(kw),
  )
})

function isEnabled(f: FieldRow): boolean {
  if (typeof f.enabled === 'boolean') return f.enabled
  const s = (f.status || '').toUpperCase()
  return s !== 'DISABLED' && s !== 'OFF'
}

function formatFieldType(f: FieldRow): string {
  const t = String(f.field_type || f.type || '').toUpperCase()
  const map: Record<string, string> = {
    'STRING': '字符串',
    'TEXT': '大文本',
    'LONG_TEXT': '大文本',
    'INTEGER': '整数',
    'INT': '整数',
    'NUMBER': '数字',
    'DECIMAL': '小数',
    'DATE': '日期',
    'DATETIME': '日期时间',
    'BOOLEAN': '布尔',
    'DICT': '字典',
    'REF': '引用',
    'JSON': 'JSON',
  }
  return map[t] || (t || '—')
}

function formatTime(ts: string | undefined | null): string {
  if (!ts) return ''
  try {
    const d = new Date(ts)
    if (isNaN(d.getTime())) return String(ts)
    const pad = (n: number) => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  } catch {
    return String(ts)
  }
}

function onEditName() {
  // P1: 接 update_apaas_model_field 类工具 (或 update_apaas_app_info 改名层级不对)
  alert('编辑模型名 — P1 接入. 当前请用配置助手对话改名.')
}

async function reload(opts: { force?: boolean } = {}) {
  if (!props.appId || !props.modelId) return
  loading.value = true
  error.value = ''
  try {
    const resp = await request.get<any, any>(
      `/applications/${props.appId}/section-content/models?with_fields=true${opts.force ? '&force=true' : ''}`,
    )
    if (resp?.ok) {
      const items: any[] = resp.items || []
      // 找当前 modelId 对应的 item; extra 里是原始 MCP 数据
      const found = items.find(it => String(it.id) === String(props.modelId)
        || String(it.extra?.model_id) === String(props.modelId))
      if (found) {
        const raw = found.extra || {}
        model.value = {
          model_id: String(raw.model_id || found.id || ''),
          model_name: String(raw.model_name || found.name || ''),
          model_code: String(raw.model_code || found.code || ''),
          created_by: raw.created_by || raw.creator || '',
          created_at: raw.created_at || raw.create_time || '',
          ...raw,
        }
        fields.value = Array.isArray(raw.fields) ? raw.fields : []
      } else {
        error.value = '未找到该模型'
      }
    } else {
      error.value = resp?.message || resp?.error_code || '加载失败'
    }
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '网络错误'
  } finally {
    loading.value = false
  }
}

watch(() => [props.appId, props.modelId], () => reload(), { immediate: true })

// 写后刷新: refreshNonce 变 → 绕过 180s 后端缓存重拉最新模型字段（对齐 FormDesignerPanel）。
watch(() => props.refreshNonce, (n, o) => {
  if (n === o || n == null) return
  void reload({ force: true })
})
</script>

<style scoped>
.dmd {
  font-family: var(--font-sans);
  color: var(--text);
  padding: 24px 32px;
  background: var(--bg);
  height: 100%;
  overflow-y: auto;
  font-feature-settings: 'cv11', 'ss01';
}

.dmd-head {
  margin-bottom: 24px;
}

.dmd-back {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: transparent;
  border: none;
  color: var(--text-2);
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  border-radius: 6px;
  transition: background 0.12s;
}
.dmd-back:hover {
  background: var(--surface-2);
  color: var(--text);
}
.dmd-back-icon {
  font-size: 18px;
  line-height: 1;
  margin-top: -2px;
}

.dmd-card {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 20px 24px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 12px;
  margin-bottom: 24px;
  box-shadow: var(--sh-1);
}

.dmd-badge {
  flex-shrink: 0;
  width: 64px;
  height: 64px;
  border-radius: 12px;
  background: var(--brand);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  font-size: 12px;
  letter-spacing: 0.3px;
  text-align: center;
  padding: 4px;
}

.dmd-badge-text {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}

.dmd-meta {
  flex: 1;
  min-width: 0;
}

.dmd-name {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 10px;
  font-size: 20px;
  font-weight: 600;
  color: var(--text);
  letter-spacing: -0.2px;
}

.dmd-edit-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  background: transparent;
  border: none;
  color: var(--text-3);
  cursor: pointer;
  border-radius: 4px;
  transition: background 0.12s, color 0.12s;
}
.dmd-edit-btn:hover {
  background: var(--surface-2);
  color: var(--brand);
}

.dmd-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.dmd-chip {
  display: inline-block;
  padding: 4px 10px;
  background: var(--surface-2);
  border-radius: 4px;
  font-size: 12.5px;
  color: var(--text-3);
}
.dmd-chip.mono {
  font-family: var(--font-mono);
  font-size: 12px;
}

.dmd-fields-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
  padding-top: 8px;
  border-top: 1px solid var(--line);
  padding-top: 24px;
}

.dmd-fields-title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--text);
}

.dmd-fields-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.dmd-search {
  position: relative;
  display: inline-flex;
  align-items: center;
}
.dmd-search input {
  height: 32px;
  width: 280px;
  padding: 0 12px 0 32px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
  font-size: 13px;
  font-family: inherit;
  outline: none;
  transition: border-color 0.12s;
}
.dmd-search input:focus {
  border-color: var(--brand);
}
.dmd-search input::placeholder {
  color: var(--text-4);
}
.dmd-search-icon {
  position: absolute;
  left: 10px;
  color: var(--text-4);
  pointer-events: none;
}

.dmd-btn {
  height: 32px;
  padding: 0 16px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  border: 1px solid transparent;
  white-space: nowrap;
  transition: background 0.12s, border-color 0.12s, color 0.12s;
}
.dmd-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.dmd-btn-ghost {
  background: var(--surface);
  border-color: var(--line-strong);
  color: var(--brand);
}
.dmd-btn-ghost:hover:not(:disabled) {
  background: var(--brand-soft);
  border-color: var(--brand);
}
.dmd-btn-primary {
  background: var(--brand);
  color: #fff;
  border-color: var(--brand);
}
.dmd-btn-primary:hover:not(:disabled) {
  background: var(--brand-hover);
}

.dmd-table-wrap {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 10px;
  overflow: hidden;
  box-shadow: var(--sh-1);
}

.dmd-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.dmd-table th {
  text-align: left;
  padding: 12px 16px;
  background: var(--surface-2);
  font-weight: 500;
  color: var(--text-3);
  border-bottom: 1px solid var(--line);
  white-space: nowrap;
}

.dmd-table td {
  padding: 12px 16px;
  border-bottom: 1px solid var(--line);
  color: var(--text);
  vertical-align: middle;
}

.dmd-table tr:last-child td {
  border-bottom: none;
}

.dmd-table tr:hover td {
  background: var(--surface-2);
}

.dmd-table .num {
  width: 60px;
  color: var(--text-4);
}

.dmd-table .ops {
  width: 80px;
  text-align: center;
}

.dmd-table .mono {
  font-family: var(--font-mono);
  font-size: 12.5px;
  color: var(--text-2);
}

.dmd-table .empty {
  text-align: center;
  padding: 48px 16px;
  color: var(--text-4);
}
.dmd-table .empty .hint {
  margin-top: 6px;
  font-size: 12px;
  color: var(--text-4);
}

.dmd-state-chip {
  display: inline-block;
  padding: 3px 12px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 500;
}
.dmd-state-chip.on {
  background: var(--ok-soft);
  color: var(--ok);
}
.dmd-state-chip.off {
  background: var(--surface-3);
  color: var(--text-3);
}

.dmd-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  background: transparent;
  border: 1px solid var(--line);
  border-radius: 4px;
  color: var(--text-3);
  cursor: pointer;
  transition: background 0.12s, color 0.12s;
}
.dmd-icon-btn:hover:not(:disabled) {
  background: var(--brand-soft);
  color: var(--brand);
  border-color: var(--brand);
}
.dmd-icon-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.dmd-state {
  padding: 32px;
  text-align: center;
  color: var(--text-3);
  font-size: 14px;
}
.dmd-state-err {
  color: var(--err);
}
.dmd-state-err .dmd-btn {
  margin-top: 12px;
  margin-left: 8px;
}

.dmd-foot {
  margin-top: 12px;
  text-align: right;
  font-size: 12.5px;
  color: var(--text-3);
}
</style>
