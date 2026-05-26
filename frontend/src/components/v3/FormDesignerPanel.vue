<!-- FormDesignerPanel.vue — Native 表单设计器面板 (替 apaas form designer iframe).

  2026-05-26 design-v3 P1-N2: 设计 tab + 表单/菜单 sub-tab 点选某个 menu 后,
  右侧主区域显该 menu 对应模型的字段表格. 视觉跟 design 截图对齐:
    - 标题: 申请表单 + 描述
    - 字段表 (字段名 / Key / 类型 / 必填 / AI 校验 / 操作)
    - 添加字段 / 批量编辑 CTA

  数据源: list_apaas_app_models with_fields=True (通过 /section-content/models?with_fields=true,
  这里我们前端先简化复用 list_apaas_app_menus 的 form_id + 自己 fetch).

  CRUD 暂未接入 (P2): + 新增字段 / 编辑字段 都 disabled, 提示用配置助手.
-->
<template>
  <section class="fdp" aria-label="表单设计">
    <div v-if="!menuId" class="fdp-empty">
      <div class="fdp-empty-icon">📝</div>
      <h3>选择一个表单</h3>
      <p>从左侧菜单列表点击某个表单, 这里显该表单的字段设计.</p>
    </div>

    <template v-else>
      <header class="fdp-head">
        <div class="fdp-head-meta">
          <h1 class="fdp-title">{{ menuName || '表单设计' }}</h1>
          <p v-if="modelCode" class="fdp-sub">
            <span class="fdp-code">{{ modelCode }}</span>
            <span v-if="fields.length" class="fdp-stat">{{ fields.length }} 字段</span>
          </p>
        </div>
        <div class="fdp-head-actions">
          <button class="fdp-btn fdp-btn-ghost" :disabled="!fields.length" @click="onBatchEdit">批量编辑</button>
          <button class="fdp-btn fdp-btn-primary" @click="onAddField">+ 新增字段</button>
        </div>
      </header>

      <div v-if="loading" class="fdp-state">加载字段…</div>
      <div v-else-if="error" class="fdp-state fdp-state-err">
        {{ error }}
        <button class="fdp-btn fdp-btn-ghost" @click="reload">重试</button>
      </div>
      <template v-else>
        <div class="fdp-toolbar">
          <div class="fdp-search">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>
            </svg>
            <input v-model="searchKw" placeholder="搜索字段名 / Key" />
          </div>
        </div>

        <div class="fdp-table-wrap">
          <table class="fdp-table">
            <thead>
              <tr>
                <th class="num">#</th>
                <th>字段名</th>
                <th>Key</th>
                <th>类型</th>
                <th class="center">必填</th>
                <th>注释</th>
                <th class="ops">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="filteredFields.length === 0">
                <td colspan="7" class="empty">
                  <p v-if="searchKw">无匹配「{{ searchKw }}」</p>
                  <template v-else>
                    <p>该表单暂无字段</p>
                    <p class="hint">点击右上「+ 新增字段」, 或用配置助手对话添加</p>
                  </template>
                </td>
              </tr>
              <tr v-for="(f, i) in filteredFields" :key="f.field_code || i">
                <td class="num">{{ i + 1 }}</td>
                <td>{{ f.field_name || '—' }}</td>
                <td class="mono">{{ f.field_code || '—' }}</td>
                <td>
                  <span class="fdp-type-chip">{{ formatType(f.data_type || f.field_type) }}</span>
                </td>
                <td class="center">
                  <span v-if="f.required" class="fdp-req">●</span>
                  <span v-else class="fdp-req fdp-req-off">○</span>
                </td>
                <td class="muted">{{ f.description || f.note || '—' }}</td>
                <td class="ops">
                  <button class="fdp-icon-btn" :disabled="true" title="P2 接入 - 编辑字段">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                      <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                    </svg>
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </template>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import request from '@/utils/request'

interface FieldRow {
  field_code?: string
  field_name?: string
  data_type?: string
  field_type?: string
  required?: boolean
  description?: string
  note?: string
  length?: number | string
}

const props = defineProps<{
  appId: number
  menuId?: string
  menuName?: string
  formId?: string
}>()

const fields = ref<FieldRow[]>([])
const modelCode = ref('')
const loading = ref(false)
const error = ref('')
const searchKw = ref('')

const filteredFields = computed(() => {
  const kw = searchKw.value.trim().toLowerCase()
  if (!kw) return fields.value
  return fields.value.filter(f =>
    (f.field_code || '').toLowerCase().includes(kw)
    || (f.field_name || '').toLowerCase().includes(kw),
  )
})

const TYPE_LABEL: Record<string, string> = {
  string: '文本', text: '文本', long_text: '大文本', textarea: '大文本',
  integer: '整数', int: '整数', number: '数字', decimal: '小数',
  date: '日期', datetime: '日期时间', daterange: '日期区间',
  boolean: '是/否', dict: '字典', select: '下拉', ref: '引用',
  user: '人员', file: '附件', image: '图片', json: 'JSON',
}

function formatType(t: string | undefined): string {
  if (!t) return '—'
  return TYPE_LABEL[String(t).toLowerCase()] || t
}

function onAddField() {
  // P2 接入. 当前提示走 AI 助手.
  alert('新增字段 — 当前请用右侧配置助手对话:\n"给当前表单加个字段叫XX"')
}

function onBatchEdit() {
  alert('批量编辑 — 当前请用右侧配置助手对话:\n"把所有金额字段加 max 校验 50000"')
}

async function reload() {
  if (!props.appId || !props.menuId) {
    fields.value = []
    modelCode.value = ''
    return
  }
  loading.value = true
  error.value = ''
  try {
    // 走 section-content/models with_fields=true (复用现有 endpoint)
    const resp = await request.get<any, any>(
      `/applications/${props.appId}/section-content/models?with_fields=true`,
    )
    if (resp?.ok) {
      const items: any[] = resp.items || []
      // 匹配规则: menu_id 通常等于 model_id, 或通过 form_id; 兜底取 name 匹配
      const target = items.find(it => {
        const raw = it.extra || {}
        return String(raw.model_id) === String(props.menuId)
          || String(raw.form_id) === String(props.formId)
          || (props.menuName && raw.model_name === props.menuName)
      })
      if (target) {
        const raw = target.extra || {}
        modelCode.value = raw.model_code || target.code || ''
        fields.value = Array.isArray(raw.fields) ? raw.fields : []
      } else {
        fields.value = []
        modelCode.value = ''
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

watch(() => [props.appId, props.menuId, props.formId], () => reload(), { immediate: true })
</script>

<style scoped>
.fdp {
  font-family: var(--font-sans);
  color: var(--text);
  padding: 28px 36px;
  background: var(--bg);
  height: 100%;
  overflow-y: auto;
  font-feature-settings: 'cv11', 'ss01';
}

.fdp-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  height: 100%;
  color: var(--text-3);
  gap: 12px;
}
.fdp-empty-icon { font-size: 48px; line-height: 1; }
.fdp-empty h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--text);
}
.fdp-empty p {
  margin: 0;
  font-size: 13.5px;
}

.fdp-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 20px;
  padding-bottom: 20px;
  border-bottom: 1px solid var(--line);
}

.fdp-title {
  margin: 0 0 6px;
  font-size: 22px;
  font-weight: 600;
  color: var(--text);
  letter-spacing: -0.3px;
}
.fdp-sub {
  margin: 0;
  display: inline-flex;
  align-items: center;
  gap: 10px;
}
.fdp-code {
  display: inline-block;
  padding: 2px 8px;
  font-size: 12px;
  font-family: var(--font-mono);
  background: var(--surface-2);
  border-radius: 4px;
  color: var(--text-3);
}
.fdp-stat {
  font-size: 12.5px;
  color: var(--text-3);
}

.fdp-head-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.fdp-btn {
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
.fdp-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.fdp-btn-ghost {
  background: var(--surface);
  border-color: var(--line-strong);
  color: var(--text);
}
.fdp-btn-ghost:hover:not(:disabled) {
  border-color: var(--brand);
  color: var(--brand);
}
.fdp-btn-primary {
  background: var(--brand);
  color: #fff;
}
.fdp-btn-primary:hover:not(:disabled) {
  background: var(--brand-hover);
}

.fdp-toolbar {
  display: flex;
  margin-bottom: 14px;
}
.fdp-search {
  position: relative;
  display: inline-flex;
  align-items: center;
}
.fdp-search input {
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
.fdp-search input:focus { border-color: var(--brand); }
.fdp-search input::placeholder { color: var(--text-4); }
.fdp-search svg {
  position: absolute;
  left: 10px;
  color: var(--text-4);
  pointer-events: none;
}

.fdp-table-wrap {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 10px;
  overflow: hidden;
  box-shadow: var(--sh-1);
}

.fdp-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.fdp-table th {
  text-align: left;
  padding: 11px 16px;
  background: var(--surface-2);
  font-weight: 500;
  color: var(--text-3);
  font-size: 12.5px;
  border-bottom: 1px solid var(--line);
  white-space: nowrap;
}
.fdp-table th.center { text-align: center; }
.fdp-table th.ops { width: 80px; text-align: center; }
.fdp-table th.num { width: 50px; }

.fdp-table td {
  padding: 12px 16px;
  border-bottom: 1px solid var(--line);
  color: var(--text);
  vertical-align: middle;
}
.fdp-table tr:last-child td { border-bottom: none; }
.fdp-table tr:hover td:not(.empty) { background: var(--surface-2); }
.fdp-table .num { color: var(--text-4); }
.fdp-table .mono {
  font-family: var(--font-mono);
  font-size: 12.5px;
  color: var(--text-2);
}
.fdp-table .center { text-align: center; }
.fdp-table .ops { text-align: center; }
.fdp-table .muted { color: var(--text-3); }
.fdp-table .empty {
  text-align: center;
  padding: 48px 16px;
  color: var(--text-4);
}
.fdp-table .empty .hint {
  margin-top: 8px;
  font-size: 12px;
}

.fdp-type-chip {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 999px;
  background: var(--brand-soft);
  color: var(--brand);
  font-size: 12px;
  font-weight: 500;
}

.fdp-req {
  display: inline-block;
  font-size: 13px;
  color: var(--err);
}
.fdp-req.fdp-req-off {
  color: var(--text-4);
}

.fdp-icon-btn {
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
  transition: background 0.12s, color 0.12s, border-color 0.12s;
}
.fdp-icon-btn:hover:not(:disabled) {
  background: var(--brand-soft);
  color: var(--brand);
  border-color: var(--brand);
}
.fdp-icon-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.fdp-state {
  padding: 48px;
  text-align: center;
  color: var(--text-3);
  font-size: 14px;
}
.fdp-state-err { color: var(--err); }
.fdp-state-err .fdp-btn { margin-top: 12px; margin-left: 8px; }
</style>
