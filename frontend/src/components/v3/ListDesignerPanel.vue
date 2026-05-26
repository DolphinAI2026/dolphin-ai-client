<!-- ListDesignerPanel.vue — Native 列表视图设计器 (替 apaas list designer iframe).

  2026-05-26 design-v3 P1-N7: 设计 tab + 列表视图 sub-tab 点选某个 menu 后,
  右侧主区域显该 menu 对应列表的**列配置** (而非表单字段表格).

  视觉跟 FormDesignerPanel 同源, 区别在表头列:
    - # / 列名 / 字段绑定 / 宽度 / 排序 / 显示条件 / 操作

  数据源: 复用 /section-content/models?with_fields=true (同 FormDesigner),
  P0 简化 — 列表的 column 直接 = model 字段, 真正列配置 (隐藏列 / 自定义宽度 /
  排序规则 / 显示条件) P1 接 MCP 工具.

  CRUD 暂未接入 (P1): [+ 添加列] / [批量编辑] / [编辑] / [删除] 全 alert
  提示用配置助手对话.
-->
<template>
  <section class="ldp" aria-label="列表设计">
    <div v-if="!menuId" class="ldp-empty">
      <div class="ldp-empty-icon">📋</div>
      <h3>选择一个列表</h3>
      <p>从左侧菜单列表点击某个列表视图, 这里显该列表的列配置.</p>
    </div>

    <template v-else>
      <header class="ldp-head">
        <div class="ldp-head-meta">
          <h1 class="ldp-title">{{ menuName || '列表设计' }}</h1>
          <p class="ldp-sub">
            <span v-if="modelCode" class="ldp-code">{{ modelCode }}</span>
            <span v-if="columns.length" class="ldp-stat">{{ columns.length }} 列</span>
            <span class="ldp-preview-chip" @click="onPreview" role="button" tabindex="0" @keydown.enter="onPreview">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                <circle cx="12" cy="12" r="3"/>
              </svg>
              列表预览
            </span>
          </p>
        </div>
        <div class="ldp-head-actions">
          <button class="ldp-btn ldp-btn-ghost" :disabled="!columns.length" @click="onBatchEdit">批量编辑</button>
          <button class="ldp-btn ldp-btn-primary" @click="onAddColumn">+ 添加列</button>
        </div>
      </header>

      <div v-if="loading" class="ldp-state">加载列配置…</div>
      <div v-else-if="error" class="ldp-state ldp-state-err">
        {{ error }}
        <button class="ldp-btn ldp-btn-ghost" @click="reload">重试</button>
      </div>
      <template v-else>
        <div class="ldp-toolbar">
          <div class="ldp-search">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>
            </svg>
            <input v-model="searchKw" placeholder="搜索列名 / 字段绑定" />
          </div>
        </div>

        <div class="ldp-table-wrap">
          <table class="ldp-table">
            <thead>
              <tr>
                <th class="num">#</th>
                <th>列名</th>
                <th>字段绑定</th>
                <th class="w">宽度</th>
                <th class="center">排序</th>
                <th>显示条件</th>
                <th class="ops">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="filteredColumns.length === 0">
                <td colspan="7" class="empty">
                  <p v-if="searchKw">无匹配「{{ searchKw }}」</p>
                  <template v-else>
                    <p>该列表暂无可显字段</p>
                    <p class="hint">点击右上「+ 添加列」, 或用配置助手对话添加</p>
                  </template>
                </td>
              </tr>
              <tr v-for="(c, i) in filteredColumns" :key="c.field_code || i">
                <td class="num">{{ i + 1 }}</td>
                <td>{{ c.field_name || '—' }}</td>
                <td class="mono">{{ c.field_code || '—' }}</td>
                <td class="w mono">{{ c.width || 'auto' }}</td>
                <td class="center">
                  <span class="ldp-sort-chip" :class="`ldp-sort-${c.sort_dir || 'none'}`">
                    {{ SORT_LABEL[c.sort_dir || 'none'] }}
                  </span>
                </td>
                <td class="muted">{{ c.show_condition || '总是显示' }}</td>
                <td class="ops">
                  <button class="ldp-icon-btn" :disabled="true" title="P1 接入 - 编辑列" @click="onEditColumn(c)">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                      <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                    </svg>
                  </button>
                  <button class="ldp-icon-btn ldp-icon-del" :disabled="true" title="P1 接入 - 删除列" @click="onDeleteColumn(c)">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M3 6h18"/>
                      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/>
                      <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
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

interface ColumnRow {
  field_code?: string
  field_name?: string
  data_type?: string
  field_type?: string
  width?: string
  sort_dir?: 'asc' | 'desc' | 'none'
  show_condition?: string
}

const props = defineProps<{
  appId: number
  menuId?: string
  menuName?: string
  formId?: string
}>()

const columns = ref<ColumnRow[]>([])
const modelCode = ref('')
const loading = ref(false)
const error = ref('')
const searchKw = ref('')

const SORT_LABEL: Record<string, string> = {
  asc: '升序',
  desc: '降序',
  none: '无',
}

const filteredColumns = computed(() => {
  const kw = searchKw.value.trim().toLowerCase()
  if (!kw) return columns.value
  return columns.value.filter(c =>
    (c.field_code || '').toLowerCase().includes(kw)
    || (c.field_name || '').toLowerCase().includes(kw),
  )
})

function onAddColumn() {
  // P1 接入. 当前提示走 AI 助手.
  alert('添加列 — 当前请用右侧配置助手对话:\n"给当前列表加一列显XX字段"')
}

function onBatchEdit() {
  alert('批量编辑 — 当前请用右侧配置助手对话:\n"把所有金额列加千分位格式 / 调宽到 150px"')
}

function onEditColumn(_c: ColumnRow) {
  alert('编辑列 — 当前请用右侧配置助手对话:\n"把XX列宽度改成 200 / 加默认排序"')
}

function onDeleteColumn(_c: ColumnRow) {
  alert('删除列 — 当前请用右侧配置助手对话:\n"列表里不要XX列了"')
}

function onPreview() {
  alert('列表预览 — P1 接入. 当前可在 [运行] tab 看实际列表效果.')
}

async function reload() {
  if (!props.appId || !props.menuId) {
    columns.value = []
    modelCode.value = ''
    return
  }
  loading.value = true
  error.value = ''
  try {
    // 走 section-content/models with_fields=true (P0 复用同 FormDesigner 的源).
    // 真要"列表自定义列配置"需要 list_apaas_app_list_views MCP 工具, 等 P1.
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
        const rawFields: any[] = Array.isArray(raw.fields) ? raw.fields : []
        // P0: 字段→列 映射, 全标 "总是显示", 宽度 auto, 排序无.
        // 真实列配置 (含隐藏列 / 显示条件 / 排序) 等 P1 MCP 工具接入.
        columns.value = rawFields.map(f => ({
          field_code: f.field_code,
          field_name: f.field_name,
          data_type: f.data_type,
          field_type: f.field_type,
          width: 'auto',
          sort_dir: 'none' as const,
          show_condition: '总是显示',
        }))
      } else {
        columns.value = []
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
.ldp {
  font-family: var(--font-sans);
  color: var(--text);
  padding: 28px 36px;
  background: var(--bg);
  height: 100%;
  overflow-y: auto;
  font-feature-settings: 'cv11', 'ss01';
}

.ldp-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  height: 100%;
  color: var(--text-3);
  gap: 12px;
}
.ldp-empty-icon { font-size: 48px; line-height: 1; }
.ldp-empty h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--text);
}
.ldp-empty p {
  margin: 0;
  font-size: 13.5px;
}

.ldp-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 20px;
  padding-bottom: 20px;
  border-bottom: 1px solid var(--line);
}

.ldp-title {
  margin: 0 0 6px;
  font-size: 22px;
  font-weight: 600;
  color: var(--text);
  letter-spacing: -0.3px;
}
.ldp-sub {
  margin: 0;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.ldp-code {
  display: inline-block;
  padding: 2px 8px;
  font-size: 12px;
  font-family: var(--font-mono);
  background: var(--surface-2);
  border-radius: 4px;
  color: var(--text-3);
}
.ldp-stat {
  font-size: 12.5px;
  color: var(--text-3);
}
.ldp-preview-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 10px;
  font-size: 12px;
  border: 1px solid var(--line-strong);
  border-radius: 999px;
  color: var(--text-3);
  cursor: pointer;
  transition: background 0.12s, color 0.12s, border-color 0.12s;
  user-select: none;
}
.ldp-preview-chip:hover, .ldp-preview-chip:focus-visible {
  background: var(--brand-soft);
  color: var(--brand);
  border-color: var(--brand);
  outline: none;
}

.ldp-head-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.ldp-btn {
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
.ldp-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.ldp-btn-ghost {
  background: var(--surface);
  border-color: var(--line-strong);
  color: var(--text);
}
.ldp-btn-ghost:hover:not(:disabled) {
  border-color: var(--brand);
  color: var(--brand);
}
.ldp-btn-primary {
  background: var(--brand);
  color: #fff;
}
.ldp-btn-primary:hover:not(:disabled) {
  background: var(--brand-hover);
}

.ldp-toolbar {
  display: flex;
  margin-bottom: 14px;
}
.ldp-search {
  position: relative;
  display: inline-flex;
  align-items: center;
}
.ldp-search input {
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
.ldp-search input:focus { border-color: var(--brand); }
.ldp-search input::placeholder { color: var(--text-4); }
.ldp-search svg {
  position: absolute;
  left: 10px;
  color: var(--text-4);
  pointer-events: none;
}

.ldp-table-wrap {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 10px;
  overflow: hidden;
  box-shadow: var(--sh-1);
}

.ldp-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.ldp-table th {
  text-align: left;
  padding: 11px 16px;
  background: var(--surface-2);
  font-weight: 500;
  color: var(--text-3);
  font-size: 12.5px;
  border-bottom: 1px solid var(--line);
  white-space: nowrap;
}
.ldp-table th.center { text-align: center; }
.ldp-table th.ops { width: 100px; text-align: center; }
.ldp-table th.num { width: 50px; }
.ldp-table th.w { width: 100px; }

.ldp-table td {
  padding: 12px 16px;
  border-bottom: 1px solid var(--line);
  color: var(--text);
  vertical-align: middle;
}
.ldp-table tr:last-child td { border-bottom: none; }
.ldp-table tr:hover td:not(.empty) { background: var(--surface-2); }
.ldp-table .num { color: var(--text-4); }
.ldp-table .mono {
  font-family: var(--font-mono);
  font-size: 12.5px;
  color: var(--text-2);
}
.ldp-table .w { width: 100px; }
.ldp-table .center { text-align: center; }
.ldp-table .ops { text-align: center; white-space: nowrap; }
.ldp-table .muted { color: var(--text-3); }
.ldp-table .empty {
  text-align: center;
  padding: 48px 16px;
  color: var(--text-4);
}
.ldp-table .empty .hint {
  margin-top: 8px;
  font-size: 12px;
}

.ldp-sort-chip {
  display: inline-block;
  min-width: 36px;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 500;
}
.ldp-sort-none {
  background: var(--surface-2);
  color: var(--text-4);
}
.ldp-sort-asc, .ldp-sort-desc {
  background: var(--brand-soft);
  color: var(--brand);
}

.ldp-icon-btn {
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
.ldp-icon-btn + .ldp-icon-btn { margin-left: 4px; }
.ldp-icon-btn:hover:not(:disabled) {
  background: var(--brand-soft);
  color: var(--brand);
  border-color: var(--brand);
}
.ldp-icon-btn.ldp-icon-del:hover:not(:disabled) {
  background: var(--err-soft);
  color: var(--err);
  border-color: var(--err);
}
.ldp-icon-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.ldp-state {
  padding: 48px;
  text-align: center;
  color: var(--text-3);
  font-size: 14px;
}
.ldp-state-err { color: var(--err); }
.ldp-state-err .ldp-btn { margin-top: 12px; margin-left: 8px; }
</style>
