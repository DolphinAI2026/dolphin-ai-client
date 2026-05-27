<!-- ListDesignerPanel.vue — 业务列表 view 设计器.

  2026-05-27 design-v4 O2-List: 重写为"业务视角预览" 默认.

  产品方向: 业务视角 — 用户看真列表 (像最终用户用应用), 编辑走对话.

  视图结构:
    顶部 toolbar: [👁 预览] [✏️ 编辑]  |  [✨ 用对话改]  [刷新]
    preview mode (默认):
      ✨ 业务视角预览 banner
      查询条件 form (3-4 个 input + 搜索/重置)
      el-table (字段表头 + 行数据 + 操作列)
      el-pagination (共 N 条 · 1 / X 页)
    edit mode: 保留原 503 行 字段表格 + 列配置 (P1 接 MCP 工具).

  数据源:
    - 字段 schema: /applications/{id}/forms/{form_id}/components (复用 FormDesigner endpoint)
    - 真实数据: /applications/{id}/forms/{form_id}/business-data?page=N (新加 O2-List-1 endpoint)
    - fallback mock: 字段名 → 假数据生成 (5 行示例)
-->
<template>
  <section class="ldp" aria-label="列表设计">
    <div v-if="!menuId" class="ldp-empty">
      <div class="ldp-empty-icon">📋</div>
      <h3>选择一个列表</h3>
      <p>从左侧菜单点击某个列表视图, 这里显该列表的业务数据.</p>
    </div>

    <template v-else>
      <!-- 顶部 toolbar — view/edit toggle + reload + 对话 hint -->
      <header class="ldp-toolbar">
        <div class="ldp-toolbar-left">
          <div class="ldp-mode-switch">
            <button
              class="ldp-mode-btn"
              :class="{ active: viewMode === 'preview' }"
              @click="viewMode = 'preview'"
              title="业务视角预览"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                <circle cx="12" cy="12" r="3"/>
              </svg>
              预览
            </button>
            <button
              class="ldp-mode-btn"
              :class="{ active: viewMode === 'edit' }"
              @click="viewMode = 'edit'"
              title="字段 / 列配置 编辑"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
              </svg>
              编辑
            </button>
          </div>
          <div class="ldp-tb-divider" />
          <span class="ldp-hint-chip" @click="onUseAssistant" role="button" tabindex="0">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M12 2l1.5 4.5L18 8l-4.5 1.5L12 14l-1.5-4.5L6 8l4.5-1.5z"/>
            </svg>
            用对话改
          </span>
        </div>
        <div class="ldp-toolbar-right">
          <button class="ldp-tb-btn" @click="reload" :disabled="loading" title="刷新">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                 :class="{ 'ldp-spin': loading }">
              <path d="M21 12a9 9 0 1 1-3-6.7L21 8"/>
              <path d="M21 3v5h-5"/>
            </svg>
            刷新
          </button>
        </div>
      </header>

      <!-- 错误 -->
      <div v-if="error" class="ldp-state ldp-state-err">
        {{ error }}
        <button class="ldp-btn ldp-btn-ghost" @click="reload">重试</button>
      </div>

      <!-- =========================================================== -->
      <!-- preview mode — 业务视角真列表 -->
      <!-- =========================================================== -->
      <div v-else-if="viewMode === 'preview'" class="ldp-pv">
        <!-- banner -->
        <div class="ldp-pv-banner">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 2l1.5 4.5L18 8l-4.5 1.5L12 14l-1.5-4.5L6 8l4.5-1.5z"/>
          </svg>
          <span>
            业务视角预览 — 看到的就是用户看列表的样子. 改列 / 加查询条件用配置助手对话.
          </span>
          <span v-if="dataSource === 'mock'" class="ldp-pv-mock-tag" title="未拉到真实业务数据, 显示 mock 示例">mock 数据</span>
        </div>

        <!-- 标题区 — 2026-05-27 S: 删 title 重复 (mdsh-subnav 已显), 只留 stats -->
        <div class="ldp-pv-title-row">
          <p class="ldp-pv-sub">
            <span v-if="modelCode" class="ldp-code">{{ modelCode }}</span>
            <span v-if="visibleColumns.length" class="ldp-stat">{{ visibleColumns.length }} 列</span>
            <span v-if="totalRows" class="ldp-stat">共 {{ totalRows }} 条</span>
          </p>
        </div>

        <!-- 查询条件 -->
        <div v-if="filterFields.length" class="ldp-pv-filter">
          <div
            v-for="f in filterFields"
            :key="f.code"
            class="ldp-pv-filter-item"
          >
            <label class="ldp-pv-label">{{ f.label }}</label>
            <input
              v-if="f.inputType === 'text'"
              v-model="filterValues[f.code]"
              :placeholder="`请输入${f.label}`"
              class="ldp-pv-input"
              @keydown.enter="onSearch"
            />
            <select
              v-else-if="f.inputType === 'select'"
              v-model="filterValues[f.code]"
              class="ldp-pv-input"
            >
              <option value="">全部</option>
              <option v-for="o in (f.options || [])" :key="o.value" :value="o.value">
                {{ o.label }}
              </option>
            </select>
            <input
              v-else-if="f.inputType === 'date'"
              type="date"
              v-model="filterValues[f.code]"
              class="ldp-pv-input"
            />
          </div>
          <div class="ldp-pv-filter-actions">
            <button class="ldp-btn ldp-btn-primary ldp-btn-sm" @click="onSearch">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>
              </svg>
              搜索
            </button>
            <button class="ldp-btn ldp-btn-ghost ldp-btn-sm" @click="onResetFilter">重置</button>
          </div>
        </div>

        <!-- 表格 -->
        <div v-if="loading" class="ldp-state">加载列表数据…</div>
        <template v-else>
          <div v-if="filteredRows.length === 0" class="ldp-pv-empty">
            <div class="ldp-pv-empty-icon">📦</div>
            <!-- 2026-05-27 T: 区分两种空态 — list_page_view 未配 vs 已配但无数据 -->
            <template v-if="isListConfigured === false">
              <p>列表预览待对接 apaas 列表配置 API</p>
              <p class="hint">apaas 上配的查询条件 / 列字段当前拉不到 (P5: 探明独立 API 后补),
                              切到"编辑"模式可直接在 apaas 原生编辑器查看 / 修改</p>
            </template>
            <template v-else>
              <p v-if="!visibleColumns.length">该列表尚未配置可显字段</p>
              <p v-else-if="hasActiveFilter">无匹配筛选条件的数据</p>
              <p v-else>暂无业务数据</p>
              <p class="hint" v-if="visibleColumns.length">通过左侧菜单内"新增"按钮录入数据, 或让用户在前台提交</p>
            </template>
          </div>
          <div v-else class="ldp-pv-table-wrap">
            <table class="ldp-pv-table">
              <thead>
                <tr>
                  <th class="num">#</th>
                  <th v-for="c in visibleColumns" :key="c.code">{{ c.label }}</th>
                  <th class="ops">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="(row, i) in pagedRows"
                  :key="i"
                  @click="onRowClick(row, i)"
                  class="ldp-pv-tr"
                >
                  <td class="num">{{ (currentPage - 1) * pageSize + i + 1 }}</td>
                  <td v-for="c in visibleColumns" :key="c.code">
                    <span
                      v-if="c.kind === 'status'"
                      class="ldp-pv-chip"
                      :class="statusChipClass(row[c.code])"
                    >
                      {{ renderCell(row, c) }}
                    </span>
                    <span v-else class="ldp-pv-cell" :title="String(renderCell(row, c))">
                      {{ renderCell(row, c) }}
                    </span>
                  </td>
                  <td class="ops" @click.stop>
                    <button class="ldp-pv-link" @click="onRowView(row)">查看</button>
                    <button class="ldp-pv-link" @click="onRowEdit(row)">编辑</button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- 分页 -->
          <div v-if="filteredRows.length > 0" class="ldp-pv-paging">
            <span class="ldp-pv-paging-info">
              共 {{ filteredRows.length }} 条 · {{ currentPage }} / {{ totalPages }} 页
            </span>
            <div class="ldp-pv-paging-ctl">
              <button
                class="ldp-pv-page-btn"
                :disabled="currentPage <= 1"
                @click="currentPage = Math.max(1, currentPage - 1)"
              >‹</button>
              <button
                v-for="p in pageNumbers"
                :key="p"
                class="ldp-pv-page-btn"
                :class="{ active: p === currentPage }"
                @click="currentPage = p"
              >{{ p }}</button>
              <button
                class="ldp-pv-page-btn"
                :disabled="currentPage >= totalPages"
                @click="currentPage = Math.min(totalPages, currentPage + 1)"
              >›</button>
              <select v-model.number="pageSize" class="ldp-pv-page-size">
                <option :value="10">10 / 页</option>
                <option :value="20">20 / 页</option>
                <option :value="50">50 / 页</option>
              </select>
            </div>
          </div>
        </template>
      </div>

      <!-- =========================================================== -->
      <!-- edit mode — 2026-05-27 R: 删自写 503 行字段表格 UI, 改 iframe apaas 原生 -->
      <!-- 用户手动改走 apaas 平台 (data-model-fn-config?embed=1); 业务改用对话 -->
      <!-- =========================================================== -->
      <ApaasEmbedIframe
        v-else
        :app-id="props.appId"
        :menu-id="props.menuId"
        :form-id="props.formId"
        menu-type="MODEL"
        mode="config"
        designer-sub="list"
      />
    </template>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, watch, reactive } from 'vue'
import request from '@/utils/request'
import ApaasEmbedIframe from './ApaasEmbedIframe.vue'

// 字段 → 列定义 (edit mode 用)
interface ColumnRow {
  field_code?: string
  field_name?: string
  data_type?: string
  field_type?: string
  width?: string
  sort_dir?: 'asc' | 'desc' | 'none'
  show_condition?: string
}

// preview mode 表头列
interface PreviewColumn {
  code: string         // row 里取值的 key (uuid 或 field_code)
  label: string        // 表头显示
  kind: 'text' | 'date' | 'number' | 'boolean' | 'status' | 'longtext'
  dataType?: string    // STRING / DATE / INTEGER / BIG_TEXT etc.
}

// preview mode 查询条件 field
interface FilterField {
  code: string
  label: string
  inputType: 'text' | 'select' | 'date'
  options?: Array<{ value: string; label: string }>
}

const props = defineProps<{
  appId: number
  menuId?: string
  menuName?: string
  formId?: string
}>()

// ---------- view mode toggle ----------
const viewMode = ref<'preview' | 'edit'>('preview')

// ---------- 共享 state ----------
const columns = ref<ColumnRow[]>([])
const modelCode = ref('')
const loading = ref(false)
const error = ref('')
const searchKw = ref('')

// ---------- preview state ----------
const previewColumns = ref<PreviewColumn[]>([])
const filterFields = ref<FilterField[]>([])
const filterValues = reactive<Record<string, string>>({})
const allRows = ref<Record<string, any>[]>([])
const dataSource = ref<'real' | 'mock'>('mock')
// 2026-05-27 T: apaas 列表设计 tab 真实配置状态 — 区分"未配置"与"已配置但空".
// null = 未拉到 detail (老 fallback 路径); true = apaas 上配过 query/columns;
// false = apaas list_page_view 返了但 query_conditions/query_list 都是空数组.
const isListConfigured = ref<boolean | null>(null)
const totalRows = ref(0)
const currentPage = ref(1)
const pageSize = ref(10)

const SORT_LABEL: Record<string, string> = {
  asc: '升序',
  desc: '降序',
  none: '无',
}

// edit mode 过滤
const filteredColumns = computed(() => {
  const kw = searchKw.value.trim().toLowerCase()
  if (!kw) return columns.value
  return columns.value.filter(c =>
    (c.field_code || '').toLowerCase().includes(kw)
    || (c.field_name || '').toLowerCase().includes(kw),
  )
})

// preview — 可见列 (头 7 列, 跳过 longtext)
const visibleColumns = computed<PreviewColumn[]>(() => {
  const max = 7
  const out: PreviewColumn[] = []
  for (const c of previewColumns.value) {
    if (out.length >= max) break
    if (c.kind === 'longtext') continue  // 长文本不显
    out.push(c)
  }
  return out
})

const hasActiveFilter = computed(() =>
  Object.values(filterValues).some(v => v && String(v).trim()),
)

// preview — in-memory 筛
const filteredRows = computed(() => {
  if (!hasActiveFilter.value) return allRows.value
  return allRows.value.filter(row => {
    for (const f of filterFields.value) {
      const filterVal = filterValues[f.code]
      if (!filterVal) continue
      const cellVal = String(row[f.code] ?? '').toLowerCase()
      if (!cellVal.includes(String(filterVal).toLowerCase())) return false
    }
    return true
  })
})

const totalPages = computed(() => Math.max(1, Math.ceil(filteredRows.value.length / pageSize.value)))

const pagedRows = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredRows.value.slice(start, start + pageSize.value)
})

const pageNumbers = computed<number[]>(() => {
  const total = totalPages.value
  const cur = currentPage.value
  if (total <= 5) return Array.from({ length: total }, (_, i) => i + 1)
  // 简化分页 — 最多显 5 个数字
  const start = Math.max(1, Math.min(total - 4, cur - 2))
  return Array.from({ length: 5 }, (_, i) => start + i)
})

// ----------------------------------------------------------
// 字段类型 → 渲染 kind 映射
// ----------------------------------------------------------
function classifyField(comp: any): { kind: PreviewColumn['kind']; inputType?: FilterField['inputType'] } {
  const ct = String(comp.component_type || comp.componentType || '').toUpperCase()
  const dt = String(comp.data_type || comp.dataType || comp.extra?.data_type || '').toUpperCase()
  // status 检测 — 名字含 状态 / status / state, 或字典
  const label = String(comp.label || comp.name || '').toLowerCase()
  if (label.includes('状态') || label.includes('status') || label.includes('state')) {
    return { kind: 'status', inputType: 'select' }
  }
  if (ct.includes('DICTIONARY') || ct === 'FORM_RADIO_GROUP' || ct === 'FORM_RADIO' || ct === 'FORM_SELECT_BOX') {
    return { kind: 'text', inputType: 'select' }
  }
  if (ct.includes('DATE') || dt === 'DATE' || dt === 'DATETIME') {
    return { kind: 'date', inputType: 'date' }
  }
  if (ct.includes('NUMBER') || ct.includes('AMOUNT') || dt === 'INTEGER' || dt === 'NUMBER' || dt === 'DECIMAL') {
    return { kind: 'number', inputType: 'text' }
  }
  if (ct === 'FORM_SWITCH' || dt === 'BOOLEAN') {
    return { kind: 'boolean', inputType: 'select' }
  }
  if (ct.includes('TEXTAREA') || ct.includes('RICH_TEXT') || dt === 'BIG_TEXT') {
    return { kind: 'longtext', inputType: 'text' }
  }
  return { kind: 'text', inputType: 'text' }
}

// ----------------------------------------------------------
// Mock 数据生成 — 真业务数据拉不到时兜底
// ----------------------------------------------------------
const MOCK_NAMES = ['张三', '李四', '王五', '赵六', '钱七', '孙八']
const MOCK_BOOKS = ['设计模式', '算法导论', '重构: 改善既有代码的设计', '深入理解计算机系统', 'Clean Code']
const STATUS_OPTIONS = [
  { value: 'pending', label: '待审批' },
  { value: 'approved', label: '已通过' },
  { value: 'rejected', label: '已拒绝' },
]

function genMockRows(cols: PreviewColumn[], count: number): Record<string, any>[] {
  const rows: Record<string, any>[] = []
  for (let i = 0; i < count; i++) {
    const row: Record<string, any> = {}
    for (const c of cols) {
      const label = c.label.toLowerCase()
      if (c.kind === 'status') {
        row[c.code] = STATUS_OPTIONS[i % STATUS_OPTIONS.length].value
      } else if (c.kind === 'date') {
        const d = new Date(2026, 4, 20 + (i % 8))
        row[c.code] = d.toISOString().slice(0, 10)
      } else if (c.kind === 'number') {
        row[c.code] = (i + 1) * 100
      } else if (c.kind === 'boolean') {
        row[c.code] = i % 2 === 0 ? '是' : '否'
      } else if (label.includes('人') || label.includes('user') || label.includes('申请') || label.includes('借阅')) {
        row[c.code] = MOCK_NAMES[i % MOCK_NAMES.length]
      } else if (label.includes('单号') || label.includes('编号') || label.includes('no') || label.includes('code')) {
        row[c.code] = `${(c.code || 'NO').slice(0, 4).toUpperCase()}-${String(i + 1).padStart(3, '0')}`
      } else if (label.includes('图书') || label.includes('物品') || label.includes('book') || label.includes('item') || label.includes('名称')) {
        row[c.code] = MOCK_BOOKS[i % MOCK_BOOKS.length]
      } else if (label.includes('备注') || label.includes('说明') || label.includes('remark')) {
        row[c.code] = `示例 ${c.label} ${i + 1}`
      } else {
        row[c.code] = `${c.label} ${i + 1}`
      }
    }
    rows.push(row)
  }
  return rows
}

// ----------------------------------------------------------
// Cell 渲染
// ----------------------------------------------------------
function renderCell(row: Record<string, any>, col: PreviewColumn): string {
  const v = row[col.code]
  if (v == null || v === '') return '—'
  if (col.kind === 'status') {
    const opt = STATUS_OPTIONS.find(o => o.value === String(v))
    if (opt) return opt.label
    return String(v)
  }
  if (col.kind === 'boolean') {
    if (v === true || v === 'true' || v === 1 || v === '1') return '是'
    if (v === false || v === 'false' || v === 0 || v === '0') return '否'
    return String(v)
  }
  const s = String(v)
  // 长字符串截断
  if (s.length > 50) return s.slice(0, 47) + '…'
  return s
}

function statusChipClass(v: any): string {
  const s = String(v).toLowerCase()
  if (s === 'approved' || s.includes('通过')) return 'ldp-pv-chip-success'
  if (s === 'rejected' || s.includes('拒绝')) return 'ldp-pv-chip-danger'
  if (s === 'pending' || s.includes('待') || s.includes('审')) return 'ldp-pv-chip-warning'
  return 'ldp-pv-chip-default'
}

// ----------------------------------------------------------
// Handlers
// ----------------------------------------------------------
function onSearch() {
  currentPage.value = 1
}

function onResetFilter() {
  for (const k of Object.keys(filterValues)) {
    filterValues[k] = ''
  }
  currentPage.value = 1
}

function onRowClick(row: Record<string, any>, _i: number) {
  const summary = visibleColumns.value
    .slice(0, 3)
    .map(c => `${c.label}: ${renderCell(row, c)}`)
    .join('\n')
  alert(`查看详情 (P1 接入完整 detail 抽屉)\n\n${summary}`)
}

function onRowView(row: Record<string, any>) {
  onRowClick(row, 0)
}

function onRowEdit(_row: Record<string, any>) {
  alert('编辑数据行 — P1 接入. 当前可通过 [运行] tab 进真应用编辑.')
}

function onUseAssistant() {
  alert('用配置助手对话:\n"列表加一列显XX字段 / 删除XX列 / 加搜索条件 XX / 改默认排序"\n\n右侧聊天面板继续.')
}

function onAddColumn() {
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

// ----------------------------------------------------------
// 数据加载
// ----------------------------------------------------------
async function loadComponentsAndFields(): Promise<void> {
  // 优先用 form_id 直查 components (跟 FormDesigner 同源)
  if (props.formId) {
    try {
      // 2026-05-27 T: 并行拉 components (字段池) + detail (含 list_page_view 真配置)
      const [compResp, detailResp] = await Promise.all([
        request.get<any, any>(`/applications/${props.appId}/forms/${props.formId}/components`),
        request.get<any, any>(`/applications/${props.appId}/forms/${props.formId}/detail`).catch(() => null),
      ])
      if (compResp?.ok && Array.isArray(compResp.items)) {
        const items: any[] = compResp.items
        // edit mode columns (用 components 全字段 — apaas iframe 自己用, 我们 edit mode 不显)
        columns.value = items.map(c => {
          const raw = c.extra || {}
          return {
            field_code: c.code || raw.bo_code,
            field_name: c.name || raw.label,
            data_type: String(raw.data_type || raw.dataType || ''),
            field_type: String(raw.component_type || raw.componentType || ''),
            width: 'auto',
            sort_dir: 'none' as const,
            show_condition: '总是显示',
          }
        })
        // 字段池 — 按 uuid + code 索引 (apaas list_page_view 用 fieldComponentUuid 引用)
        const pvPool: PreviewColumn[] = []
        const poolByCode = new Map<string, PreviewColumn>()
        for (const c of items) {
          const raw = c.extra || {}
          const cls = classifyField(raw)
          const code = c.id || c.code || raw.uuid || raw.bo_code
          const col: PreviewColumn = {
            code,
            label: c.name || raw.label || '未命名',
            kind: cls.kind,
            dataType: String(raw.data_type || raw.dataType || ''),
          }
          pvPool.push(col)
          if (code) poolByCode.set(String(code), col)
          // 别名: 字段 code (非 uuid) 也存一份, 提高 list_page_view 引用解析命中
          const fieldCode = raw.bo_code || c.code
          if (fieldCode && fieldCode !== code) poolByCode.set(String(fieldCode), col)
        }

        // T: 用 list_page_view 真配置过滤 — apaas 上没配 → 空列表 (不再瞎猜)
        const lpv = detailResp?.list_page_view || { query_conditions: [], query_list: [] }
        const queryConditions: any[] = Array.isArray(lpv.query_conditions) ? lpv.query_conditions : []
        const queryList: any[] = Array.isArray(lpv.query_list) ? lpv.query_list : []
        isListConfigured.value = (queryConditions.length + queryList.length) > 0

        // T3: apaas listPageConfigById 实测 — 引用字段用 `uuid` (跟 components
        // 的 c.id 对齐); 老字段名 `fieldComponentUuid` 是其他 view 用的, 留兼容.
        // boCode 用 `~` 分隔模型.字段 (e.g. "book_manage~book_title").
        const resolveCol = (q: any): PreviewColumn | null => {
          const candidates = [q.uuid, q.fieldComponentUuid, q.componentUuid, q.boCode, q.fieldCode, q.fieldComponentCode]
          for (const ref of candidates) {
            if (!ref) continue
            const col = poolByCode.get(String(ref))
            if (col) return col
          }
          return null
        }

        // 查询条件 — 严格按 apaas 配置
        filterFields.value = queryConditions
          .map((q: any) => {
            const col = resolveCol(q)
            if (!col) return null
            return {
              code: col.code,
              label: q.label || q.title || col.label,
              inputType:
                col.kind === 'status' || col.kind === 'boolean' ? 'select' as const
                  : col.kind === 'date' ? 'date' as const
                  : 'text' as const,
              options: col.kind === 'status' ? STATUS_OPTIONS : undefined,
            }
          })
          .filter((x): x is FilterField => x !== null)
        for (const f of filterFields.value) {
          if (!(f.code in filterValues)) filterValues[f.code] = ''
        }

        // 列表字段 — 严格按 apaas 配置 + displayFlag=false 过滤
        previewColumns.value = queryList
          .filter((q: any) => q.displayFlag !== false)
          .map((q: any) => resolveCol(q))
          .filter((x): x is PreviewColumn => x !== null)

        // 注: previewColumns 现可能是空, 模板靠 visibleColumns / isListConfigured 渲染空态
        return
      }
    } catch (_e) {
      // 不抛, fallback 走 models 路径
    }
  }
  // fallback: 走 models 拿 (复用原逻辑)
  const resp = await request.get<any, any>(
    `/applications/${props.appId}/section-content/models?with_fields=true`,
  )
  if (!resp?.ok) {
    throw new Error(resp?.message || resp?.error_code || '加载列配置失败')
  }
  const items: any[] = resp.items || []
  const target = items.find(it => {
    const raw = it.extra || {}
    return String(raw.model_id) === String(props.menuId)
      || String(raw.form_id) === String(props.formId)
      || (props.menuName && raw.model_name === props.menuName)
  })
  if (!target) {
    columns.value = []
    previewColumns.value = []
    modelCode.value = ''
    return
  }
  const raw = target.extra || {}
  modelCode.value = raw.model_code || target.code || ''
  const rawFields: any[] = Array.isArray(raw.fields) ? raw.fields : []
  columns.value = rawFields.map(f => ({
    field_code: f.field_code,
    field_name: f.field_name,
    data_type: f.data_type,
    field_type: f.field_type,
    width: 'auto',
    sort_dir: 'none' as const,
    show_condition: '总是显示',
  }))
  // preview columns from model fields
  const pvCols: PreviewColumn[] = rawFields.map(f => {
    const cls = classifyField({
      label: f.field_name,
      data_type: f.data_type,
      component_type: f.field_type,
    })
    return {
      code: f.field_code,
      label: f.field_name || '未命名',
      kind: cls.kind,
      dataType: String(f.data_type || ''),
    }
  })
  previewColumns.value = pvCols
  const candidates = pvCols.filter(c => c.kind !== 'longtext')
  const statusFields = candidates.filter(c => c.kind === 'status')
  const otherFields = candidates.filter(c => c.kind !== 'status')
  const picked = [...statusFields.slice(0, 1), ...otherFields].slice(0, 4)
  filterFields.value = picked.map(c => ({
    code: c.code,
    label: c.label,
    inputType:
      c.kind === 'status' || c.kind === 'boolean' ? 'select'
        : c.kind === 'date' ? 'date'
        : 'text',
    options: c.kind === 'status' ? STATUS_OPTIONS : undefined,
  }))
  for (const f of filterFields.value) {
    if (!(f.code in filterValues)) filterValues[f.code] = ''
  }
}

async function loadBusinessData(): Promise<void> {
  // 真业务数据需要 form_id + 应用已部署
  if (!props.formId || !previewColumns.value.length) {
    allRows.value = []
    totalRows.value = 0
    dataSource.value = 'mock'
    return
  }
  try {
    const resp = await request.get<any, any>(
      `/applications/${props.appId}/forms/${props.formId}/business-data?page=1&page_size=50`,
    )
    if (resp?.ok && Array.isArray(resp.items) && resp.items.length > 0) {
      allRows.value = resp.items
      totalRows.value = resp.total || resp.items.length
      dataSource.value = 'real'
      return
    }
  } catch (_e) {
    // fallback mock
  }
  // mock fallback (5 行)
  allRows.value = genMockRows(previewColumns.value, 5)
  totalRows.value = 5
  dataSource.value = 'mock'
}

async function reload() {
  if (!props.appId || !props.menuId) {
    columns.value = []
    previewColumns.value = []
    allRows.value = []
    modelCode.value = ''
    return
  }
  loading.value = true
  error.value = ''
  try {
    await loadComponentsAndFields()
    await loadBusinessData()
    currentPage.value = 1
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '网络错误'
  } finally {
    loading.value = false
  }
}

watch(() => [props.appId, props.menuId, props.formId], () => reload(), { immediate: true })

// 2026-05-27 S4: edit→preview 时 reload — apaas iframe 内用户可能改了
// queryConditions/queryList, 切回预览自动拉真新配置 (避免显示旧的 mock / 空态).
watch(viewMode, (mode, prev) => {
  if (mode === 'preview' && prev === 'edit') reload()
})
</script>

<style scoped>
.ldp {
  font-family: var(--font-sans);
  color: var(--text);
  padding: 20px 32px;
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

/* ===================== Toolbar ===================== */
.ldp-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 0 14px;
  margin-bottom: 14px;
  border-bottom: 1px solid var(--line);
  position: sticky;
  top: 0;
  background: var(--bg);
  z-index: 5;
}
.ldp-toolbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
}
.ldp-toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
.ldp-mode-switch {
  display: inline-flex;
  border: 1px solid var(--line-strong);
  border-radius: 6px;
  background: var(--surface);
  overflow: hidden;
}
.ldp-mode-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 30px;
  padding: 0 12px;
  background: transparent;
  border: none;
  font-size: 12.5px;
  font-family: inherit;
  color: var(--text-3);
  cursor: pointer;
  transition: background 0.12s, color 0.12s;
  user-select: none;
}
.ldp-mode-btn:hover { color: var(--text); }
.ldp-mode-btn.active {
  background: var(--brand-soft);
  color: var(--brand);
}
.ldp-mode-btn + .ldp-mode-btn { border-left: 1px solid var(--line); }

.ldp-tb-divider {
  width: 1px;
  height: 18px;
  background: var(--line);
}
.ldp-hint-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  font-size: 12px;
  border: 1px dashed var(--brand);
  border-radius: 999px;
  color: var(--brand);
  cursor: pointer;
  background: var(--brand-soft);
  transition: background 0.12s;
}
.ldp-hint-chip:hover, .ldp-hint-chip:focus-visible {
  background: color-mix(in srgb, var(--brand) 14%, transparent);
  outline: none;
}
.ldp-tb-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 30px;
  padding: 0 12px;
  border: 1px solid var(--line-strong);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
  font-size: 12.5px;
  font-family: inherit;
  cursor: pointer;
  transition: border-color 0.12s, color 0.12s;
}
.ldp-tb-btn:hover:not(:disabled) {
  border-color: var(--brand);
  color: var(--brand);
}
.ldp-tb-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.ldp-spin { animation: ldp-spin 0.8s linear infinite; }
@keyframes ldp-spin {
  from { transform: rotate(0); }
  to { transform: rotate(360deg); }
}

/* ===================== Preview mode ===================== */
.ldp-pv {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.ldp-pv-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: var(--brand-soft);
  border-left: 3px solid var(--brand);
  border-radius: 6px;
  font-size: 13px;
  color: var(--text-2);
}
.ldp-pv-banner svg { color: var(--brand); flex-shrink: 0; }
.ldp-pv-mock-tag {
  margin-left: auto;
  padding: 1px 8px;
  font-size: 11px;
  background: var(--warn-soft, #fff7e6);
  color: var(--warn, #d4791f);
  border-radius: 999px;
  border: 1px solid var(--warn, #d4791f);
}

.ldp-pv-title-row {
  display: flex;
  align-items: baseline;
  gap: 14px;
  margin-bottom: 4px;
}
.ldp-pv-title {
  margin: 0;
  font-size: 22px;
  font-weight: 600;
  letter-spacing: -0.3px;
}
.ldp-pv-sub {
  margin: 0;
  display: inline-flex;
  gap: 10px;
  align-items: center;
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

.ldp-pv-filter {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 16px;
  align-items: flex-end;
  padding: 14px 16px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
}
.ldp-pv-filter-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 180px;
  flex: 0 0 auto;
}
.ldp-pv-label {
  font-size: 12px;
  color: var(--text-3);
  font-weight: 500;
}
.ldp-pv-input {
  height: 30px;
  padding: 0 10px;
  font-size: 13px;
  border: 1px solid var(--line);
  border-radius: 5px;
  background: var(--surface);
  color: var(--text);
  font-family: inherit;
  outline: none;
  transition: border-color 0.12s;
}
.ldp-pv-input:focus { border-color: var(--brand); }
select.ldp-pv-input { cursor: pointer; }

.ldp-pv-filter-actions {
  display: inline-flex;
  gap: 6px;
  margin-left: auto;
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
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.ldp-btn-sm { height: 30px; padding: 0 12px; font-size: 12.5px; }
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

.ldp-pv-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 60px 16px;
  background: var(--surface);
  border: 1px dashed var(--line);
  border-radius: 8px;
  color: var(--text-3);
}
.ldp-pv-empty-icon { font-size: 40px; }
.ldp-pv-empty p { margin: 0; font-size: 13.5px; }
.ldp-pv-empty .hint { font-size: 12px; color: var(--text-4); }

.ldp-pv-table-wrap {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: hidden;
  box-shadow: var(--sh-1);
  overflow-x: auto;
}

.ldp-pv-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.ldp-pv-table th {
  text-align: left;
  padding: 11px 14px;
  background: var(--surface-2);
  font-weight: 500;
  color: var(--text-3);
  font-size: 12.5px;
  border-bottom: 1px solid var(--line);
  white-space: nowrap;
  position: sticky;
  top: 0;
  z-index: 2;
}
.ldp-pv-table th.num { width: 50px; text-align: center; }
.ldp-pv-table th.ops { width: 110px; text-align: center; }

.ldp-pv-table td {
  padding: 11px 14px;
  border-bottom: 1px solid var(--line);
  color: var(--text);
  vertical-align: middle;
}
.ldp-pv-table tr:last-child td { border-bottom: none; }
.ldp-pv-tr { cursor: pointer; transition: background 0.12s; }
.ldp-pv-tr:hover td { background: var(--surface-2); }

.ldp-pv-table .num { color: var(--text-4); text-align: center; font-size: 12px; }
.ldp-pv-table .ops { text-align: center; white-space: nowrap; }
.ldp-pv-cell {
  display: inline-block;
  max-width: 220px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: middle;
}

.ldp-pv-chip {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 500;
}
.ldp-pv-chip-success {
  background: color-mix(in srgb, var(--ok, #16a34a) 14%, transparent);
  color: var(--ok, #16a34a);
}
.ldp-pv-chip-warning {
  background: var(--warn-soft, #fff7e6);
  color: var(--warn, #d4791f);
}
.ldp-pv-chip-danger {
  background: var(--err-soft);
  color: var(--err);
}
.ldp-pv-chip-default {
  background: var(--surface-2);
  color: var(--text-3);
}

.ldp-pv-link {
  background: transparent;
  border: none;
  color: var(--brand);
  font-size: 12.5px;
  font-family: inherit;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;
  transition: background 0.12s;
}
.ldp-pv-link:hover { background: var(--brand-soft); }
.ldp-pv-link + .ldp-pv-link { margin-left: 4px; }

.ldp-pv-paging {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 4px 0;
}
.ldp-pv-paging-info {
  font-size: 12.5px;
  color: var(--text-3);
}
.ldp-pv-paging-ctl {
  display: inline-flex;
  gap: 4px;
  align-items: center;
}
.ldp-pv-page-btn {
  min-width: 28px;
  height: 28px;
  padding: 0 8px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 4px;
  color: var(--text-2);
  font-size: 12.5px;
  font-family: inherit;
  cursor: pointer;
  transition: border-color 0.12s, color 0.12s, background 0.12s;
}
.ldp-pv-page-btn:hover:not(:disabled):not(.active) {
  border-color: var(--brand);
  color: var(--brand);
}
.ldp-pv-page-btn.active {
  background: var(--brand);
  color: #fff;
  border-color: var(--brand);
}
.ldp-pv-page-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.ldp-pv-page-size {
  margin-left: 6px;
  height: 28px;
  padding: 0 6px;
  border: 1px solid var(--line);
  border-radius: 4px;
  background: var(--surface);
  color: var(--text-2);
  font-size: 12.5px;
  font-family: inherit;
  cursor: pointer;
}

/* ===================== Edit mode (保留原样) ===================== */
.ldp-edit { display: flex; flex-direction: column; }

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
.ldp-head-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.ldp-search-row {
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
