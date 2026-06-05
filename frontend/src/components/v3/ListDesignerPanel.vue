<!-- ListDesignerPanel.vue — 业务列表 view 设计器.

  2026-05-27 design-v4 O2-List: 重写为"业务视角预览" 默认.

  产品方向: 业务视角 — 用户看真列表 (像最终用户用应用), 编辑走对话.

  视图结构:
    顶部 toolbar: [👁 预览] [✏️ 编辑]  [刷新]
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
    <EmptyState
      v-if="!menuId"
      title="选择一个列表"
      desc="从左侧菜单点击某个列表视图, 这里显该列表的业务数据."
    >
      <template #icon>📋</template>
    </EmptyState>

    <template v-else>
      <!-- 顶部 toolbar — 刷新 + 打开低代码后台 (只读, 编辑去后台) -->
      <header class="ldp-toolbar">
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
      <ErrorCard
        v-if="error"
        level="err"
        title="加载失败"
        :message="error"
        :actions="[{ label: '重试', onClick: reload }]"
      />

      <!-- =========================================================== -->
      <!-- preview mode — 业务视角真列表 -->
      <!-- =========================================================== -->
      <div v-else class="ldp-pv">
        <!-- 标题区 — 2026-05-27 S: 删 title 重复 (mdsh-subnav 已显), 只留 stats -->
        <div class="ldp-pv-title-row">
          <p class="ldp-pv-sub">
            <span v-if="modelCode" class="ldp-code">{{ modelCode }}</span>
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
        <SkeletonCard v-if="loading" :lines="5" />
        <template v-else>
          <!-- 真没表可显 (列表未配置 / 无列字段) → 独立空态 -->
          <div v-if="isListConfigured === false || !visibleColumns.length" class="ldp-pv-empty">
            <div class="ldp-pv-empty-icon">📦</div>
            <template v-if="isListConfigured === false">
              <p>列表预览待对接 apaas 列表配置 API</p>
              <p class="hint">apaas 上配的查询条件 / 列字段当前拉不到 (P5: 探明独立 API 后补),
                              切到"编辑"模式可直接在 apaas 原生编辑器查看 / 修改</p>
            </template>
            <template v-else>
              <p>该列表尚未配置可显字段</p>
            </template>
          </div>
          <!-- 有列字段 → 表头常显; 0 条/筛选空时空态放进表体 (列结构始终可见, 对齐 apaas) -->
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
                <template v-if="filteredRows.length > 0">
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
                </template>
                <tr v-else class="ldp-pv-empty-row">
                  <td :colspan="visibleColumns.length + 2">
                    <div class="ldp-pv-empty-inline">
                      <div class="ldp-pv-empty-icon">📦</div>
                      <p>{{ hasActiveFilter ? '无匹配筛选条件的数据' : '暂无业务数据' }}</p>
                      <template v-if="!hasActiveFilter">
                        <p class="hint">数据由最终用户在前台录入</p>
                        <button
                          class="ldp-btn ldp-btn-primary ldp-btn-sm"
                          style="margin-top: 12px"
                          @click="openApaasApp()"
                        >打开应用录入数据</button>
                      </template>
                    </div>
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

        <!-- 行详情抽屉 (复用已拉行数据, 零新端点) -->
        <el-drawer v-model="detailVisible" title="数据详情" direction="rtl" size="420px">
          <div v-if="detailRow" class="ldp-detail">
            <div v-for="c in visibleColumns" :key="c.code" class="ldp-detail-row">
              <span class="ldp-detail-label">{{ c.label }}</span>
              <span class="ldp-detail-value">{{ renderCell(detailRow, c) }}</span>
            </div>
          </div>
        </el-drawer>
      </div>

    </template>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, watch, reactive } from 'vue'
import request from '@/utils/request'
import EmptyState from '@/components/states/EmptyState.vue'
import ErrorCard from '@/components/states/ErrorCard.vue'
import SkeletonCard from '@/components/states/SkeletonCard.vue'

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

// ---------- 共享 state ----------
const modelCode = ref('')
const loading = ref(false)
const error = ref('')

// ---------- preview state ----------
const previewColumns = ref<PreviewColumn[]>([])
const filterFields = ref<FilterField[]>([])
const filterValues = reactive<Record<string, string>>({})
const allRows = ref<Record<string, any>[]>([])
const dataSource = ref<'real' | 'empty' | 'error'>('empty')
// 行详情抽屉 — 直接复用列表已拉到的 row, 零新端点
const detailVisible = ref(false)
const detailRow = ref<Record<string, any> | null>(null)
// 2026-05-27 T: apaas 列表设计 tab 真实配置状态 — 区分"未配置"与"已配置但空".
// null = 未拉到 detail (老 fallback 路径); true = apaas 上配过 query/columns;
// false = apaas list_page_view 返了但 query_conditions/query_list 都是空数组.
const isListConfigured = ref<boolean | null>(null)
const totalRows = ref(0)
const currentPage = ref(1)
const pageSize = ref(10)

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
// 状态选项 (renderCell / 筛选条件用)
// ----------------------------------------------------------
const STATUS_OPTIONS = [
  { value: 'pending', label: '待审批' },
  { value: 'approved', label: '已通过' },
  { value: 'rejected', label: '已拒绝' },
]

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

// 打开 apaas 真实运行态应用 (空态 CTA + 行编辑共用). 应用级 URL, 记录级深链留后续.
async function openApaasApp() {
  try {
    const resp = await request.get<any, any>(
      `/applications/${props.appId}/apaas-access-url`,
    )
    if (resp?.ok && resp.access_url) {
      window.open(resp.access_url, '_blank')
    } else {
      alert(resp?.message || '应用尚未部署到 aPaaS, 无法打开')
    }
  } catch (e: any) {
    alert(`打开应用失败: ${e?.message || '网络错误'}`)
  }
}

function onRowClick(row: Record<string, any>, _i: number) {
  detailRow.value = row
  detailVisible.value = true
}

function onRowView(row: Record<string, any>) {
  onRowClick(row, 0)
}

function onRowEdit(_row: Record<string, any>) {
  // v1: 打开应用级运行态 URL (记录级深链留后续)
  openApaasApp()
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
          .filter((x): x is NonNullable<typeof x> => x !== null) as FilterField[]
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
    previewColumns.value = []
    modelCode.value = ''
    return
  }
  const raw = target.extra || {}
  modelCode.value = raw.model_code || target.code || ''
  const rawFields: any[] = Array.isArray(raw.fields) ? raw.fields : []
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
    dataSource.value = 'empty'
    return
  }
  try {
    const resp = await request.get<any, any>(
      `/applications/${props.appId}/forms/${props.formId}/business-data?page=1&page_size=50`,
    )
    if (resp?.ok && Array.isArray(resp.items)) {
      allRows.value = resp.items
      totalRows.value = resp.total || resp.items.length
      // 真实拉取成功: 有数据→real, 0 条→empty (显诚实空态, 不再造假行)
      dataSource.value = resp.items.length > 0 ? 'real' : 'empty'
      return
    }
    // ok=false (未部署等) → 空态, 不编造数据
    allRows.value = []
    totalRows.value = 0
    dataSource.value = 'empty'
  } catch (_e) {
    allRows.value = []
    totalRows.value = 0
    dataSource.value = 'error'
  }
}

async function reload() {
  if (!props.appId || !props.menuId) {
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
</script>

<style scoped>
.ldp {
  font-family: var(--font-sans);
  color: var(--text);
  padding: var(--s-5) var(--s-8);
  background: var(--bg);
  height: 100%;
  overflow-y: auto;
  font-feature-settings: 'cv11', 'ss01';
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
.ldp-toolbar-right {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  margin-left: auto;
}

.ldp-tb-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 30px;
  padding: 0 var(--s-3);
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
  gap: var(--s-4);
}
.ldp-pv-banner {
  display: flex;
  align-items: center;
  gap: var(--s-2);
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
  background: var(--warn-soft);
  color: var(--warn);
  border-radius: 999px;
  border: 1px solid var(--warn);
}

.ldp-pv-title-row {
  display: flex;
  align-items: baseline;
  gap: 14px;
  margin-bottom: var(--s-1);
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
  gap: var(--s-3) var(--s-4);
  align-items: flex-end;
  padding: 14px 16px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
}
.ldp-pv-filter-item {
  display: flex;
  flex-direction: column;
  gap: var(--s-1);
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
  padding: 0 var(--s-4);
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
  color: var(--text-inverse);
}
.ldp-btn-primary:hover:not(:disabled) {
  background: var(--brand-hover);
}

.ldp-pv-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--s-2);
  padding: 60px 16px;
  background: var(--surface);
  border: 1px dashed var(--line);
  border-radius: 8px;
  color: var(--text-3);
}
.ldp-pv-empty-icon { font-size: 40px; }

/* 表体内空态 (0 条/筛选空时, 表头仍显, 空态居中铺整行) */
.ldp-pv-empty-row td { padding: 0; cursor: default; }
.ldp-pv-empty-row:hover td { background: transparent; }
.ldp-pv-empty-inline {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--s-2, 8px);
  padding: 44px 16px;
}
.ldp-pv-empty-inline p { margin: 0; font-size: 13px; color: var(--text); }
.ldp-pv-empty-inline .hint { font-size: 12px; color: var(--text-3); }
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
  background: color-mix(in srgb, var(--ok) 14%, transparent);
  color: var(--ok);
}
.ldp-pv-chip-warning {
  background: var(--warn-soft);
  color: var(--warn);
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
  padding: var(--s-1) var(--s-1) 0;
}
.ldp-pv-paging-info {
  font-size: 12.5px;
  color: var(--text-3);
}
.ldp-pv-paging-ctl {
  display: inline-flex;
  gap: var(--s-1);
  align-items: center;
}
.ldp-pv-page-btn {
  min-width: 28px;
  height: 28px;
  padding: 0 var(--s-2);
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
  color: var(--text-inverse);
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
  gap: var(--s-6);
  margin-bottom: var(--s-5);
  padding-bottom: var(--s-5);
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
  gap: var(--s-2);
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
  padding: var(--s-12) var(--s-4);
  color: var(--text-4);
}
.ldp-table .empty .hint {
  margin-top: var(--s-2);
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

/* 行详情抽屉 */
.ldp-detail { display: flex; flex-direction: column; }
.ldp-detail-row {
  display: flex;
  gap: 12px;
  padding: 10px 4px;
  border-bottom: 1px solid var(--line);
  font-size: 13px;
}
.ldp-detail-label { flex: 0 0 120px; color: var(--text-3); }
.ldp-detail-value { flex: 1; color: var(--text); word-break: break-all; }
</style>
