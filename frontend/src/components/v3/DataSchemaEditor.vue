<!-- DataSchemaEditor.vue — 数据 schema 编辑器 (design-v4 Phase B + G4).

  2026-05-26 design-v4 Phase B: 设计 tab 内 5th sub "数据 schema".
  跟 design 截图对齐:
    - 表头: 表名 (mono big) + MySQL badge + 主表/子表 badge + 统计行
    - 右上 actions: AI 推荐索引 / 同步 / + 新增字段
    - sub-tabs: Schema (默认) / 数据 / SQL / 关系
    - 字段 table: # / 字段 / 类型 / NULL / 键 (PK/FK/IDX/UNIQ badge) / 默认值 / 注释 / 操作

  数据源: GET /api/applications/{app_id}/section-content/models?with_fields=true
  (复用现有 endpoint, 不新加 backend.)

  通过 form_id 找 main model — 优先 form_id 字段匹配, 兜底取 is_main=true 那条.

  G4 (2026-05-26): 字段 inline 编辑 + 真存 backend.
    - 字段名 / 注释 双击 inline 编辑 → POST /crud/model-field/update
    - 编辑 icon → 弹 dialog (预填) → POST /crud/model-field/update
    - 删除 icon → confirm → POST /crud/model-field/disable (apaas 软删)
    - + 新增字段 → 弹 dialog (空) → POST /crud/model-field/add

  P2 留: AI 推荐索引 / 同步 还 disabled (留 P4).
-->
<template>
  <section class="dse" aria-label="数据 schema 编辑器">
    <div v-if="!menuId" class="dse-empty">
      <div class="dse-empty-icon">🗄️</div>
      <h3>选择一个表单</h3>
      <p>从左侧菜单列表点击某个表单, 这里显该表单关联模型的数据 schema.</p>
    </div>

    <div v-else-if="loading" class="dse-state">加载 schema…</div>
    <div v-else-if="error" class="dse-state dse-state-err">
      {{ error }}
      <button class="dse-btn dse-btn-ghost" @click="reload">重试</button>
    </div>
    <div v-else-if="!currentModel" class="dse-state">
      <p>未找到与该表单关联的数据模型.</p>
      <button class="dse-btn dse-btn-ghost" @click="reload">重新加载</button>
    </div>

    <template v-else>
      <!-- 表头 -->
      <header class="dse-head">
        <div class="dse-head-meta">
          <div class="dse-title-row">
            <h1 class="dse-title mono">{{ currentModel.model_code || '未命名表' }}</h1>
            <span class="dse-badge dse-badge-db">{{ dbType }}</span>
            <span
              class="dse-badge"
              :class="currentModel.is_main ? 'dse-badge-primary' : 'dse-badge-secondary'"
            >
              {{ currentModel.is_main ? '主表' : '子表' }}
            </span>
          </div>
          <p class="dse-stats">
            <span>{{ fieldCount }} 字段</span>
            <span v-if="primaryKeyName" class="dse-stat-sep">·</span>
            <span v-if="primaryKeyName">主键 <code class="mono">{{ primaryKeyName }}</code></span>
            <span v-if="foreignKeyCount > 0" class="dse-stat-sep">·</span>
            <span v-if="foreignKeyCount > 0">{{ foreignKeyCount }} 外键</span>
          </p>
        </div>
        <div class="dse-head-actions">
          <button class="dse-btn dse-btn-ghost" disabled title="P4 接入 - AI 推荐索引">
            <span class="dse-btn-icon">✨</span>
            AI 推荐索引
          </button>
          <button class="dse-btn dse-btn-ghost" disabled title="P4 接入 - 同步表结构">
            <span class="dse-btn-icon">⟲</span>
            同步
          </button>
          <button
            class="dse-btn dse-btn-primary"
            :disabled="!canMutate"
            :title="canMutate ? '新增字段到该模型' : '应用未部署 / 模型缺 model_id 无法新增'"
            @click="openAddDialog"
          >
            + 新增字段
          </button>
        </div>
      </header>

      <!-- 4 sub-tab -->
      <div class="dse-subnav" role="tablist">
        <button
          v-for="sub in SUB_TABS"
          :key="sub.code"
          class="dse-subnav-tab"
          :class="{ active: subTab === sub.code }"
          role="tab"
          :aria-selected="subTab === sub.code"
          @click="subTab = sub.code"
        >
          {{ sub.label }}
        </button>
      </div>

      <!-- Schema tab — 字段 table -->
      <div v-if="subTab === 'schema'" class="dse-table-wrap">
        <table class="dse-table">
          <thead>
            <tr>
              <th class="num">#</th>
              <th class="col-field">字段</th>
              <th class="col-type">类型</th>
              <th class="col-null">NULL</th>
              <th class="col-key">键</th>
              <th class="col-default">默认值</th>
              <th class="col-comment">注释</th>
              <th class="col-ops">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="fields.length === 0">
              <td colspan="8" class="empty">
                <p>该模型暂无字段</p>
                <p class="hint">点击右上「+ 新增字段」, 或用配置助手对话添加</p>
              </td>
            </tr>
            <tr
              v-for="(f, i) in fields"
              :key="getFieldKey(f, i)"
              :class="{ 'dse-row-loading': isRowLoading(f), 'dse-row-error': hasRowError(f) }"
            >
              <td class="num">{{ i + 1 }}</td>
              <td class="mono col-field">
                <span
                  v-if="!isInlineEditing(f, 'field_code')"
                  class="dse-cell-text dse-cell-editable"
                  :class="{ 'dse-cell-disabled': !canMutateField(f) }"
                  :title="canMutateField(f) ? '双击编辑' : '该字段不可编辑 (主键 / 缺 field_id)'"
                  @dblclick="canMutateField(f) && startInlineEdit(f, 'field_code')"
                >
                  {{ getFieldCode(f) || '—' }}
                </span>
                <input
                  v-else
                  ref="inlineInputs"
                  v-model="inlineValue"
                  class="dse-cell-input mono"
                  type="text"
                  :disabled="isRowLoading(f)"
                  @keydown.esc.prevent="cancelInlineEdit"
                  @keydown.enter.prevent="commitInlineEdit(f)"
                  @blur="commitInlineEdit(f)"
                />
              </td>
              <td class="col-type">
                <span class="mono dse-type-text">{{ formatSqlType(f) }}</span>
              </td>
              <td class="col-null">
                <span v-if="!isRequired(f)" class="dse-null-yes" title="允许 NULL">✓</span>
                <span v-else class="dse-null-no" title="不允许 NULL">✗</span>
              </td>
              <td class="col-key">
                <span
                  v-for="badge in computeKeyBadges(f)"
                  :key="badge.kind"
                  class="dse-key-badge"
                  :class="`dse-key-${badge.kind.toLowerCase()}`"
                  :title="badge.title"
                >{{ badge.label }}</span>
                <span v-if="!computeKeyBadges(f).length" class="dse-empty-cell">—</span>
              </td>
              <td class="col-default mono dse-default">{{ getDefaultValue(f) }}</td>
              <td class="col-comment muted">
                <span
                  v-if="!isInlineEditing(f, 'comment')"
                  class="dse-cell-text dse-cell-editable"
                  :class="{ 'dse-cell-disabled': !canMutateField(f) }"
                  :title="canMutateField(f) ? '双击编辑注释' : '该字段不可编辑'"
                  @dblclick="canMutateField(f) && startInlineEdit(f, 'comment')"
                >
                  {{ getComment(f) || '—' }}
                </span>
                <input
                  v-else
                  ref="inlineInputs"
                  v-model="inlineValue"
                  class="dse-cell-input"
                  type="text"
                  :disabled="isRowLoading(f)"
                  placeholder="注释 (可空)"
                  @keydown.esc.prevent="cancelInlineEdit"
                  @keydown.enter.prevent="commitInlineEdit(f)"
                  @blur="commitInlineEdit(f)"
                />
              </td>
              <td class="col-ops">
                <span v-if="isRowLoading(f)" class="dse-row-spinner" title="保存中…">⟳</span>
                <template v-else>
                  <button
                    class="dse-icon-btn"
                    :disabled="!canMutateField(f)"
                    :title="canMutateField(f) ? '编辑字段' : '该字段不可编辑'"
                    @click="openEditDialog(f)"
                  >
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                      <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                    </svg>
                  </button>
                  <button
                    class="dse-icon-btn dse-icon-btn-danger"
                    :disabled="!canMutateField(f)"
                    :title="canMutateField(f) ? '删除字段' : '该字段不可删除 (主键 / 缺 field_id)'"
                    @click="confirmDeleteField(f)"
                  >
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M3 6h18"/>
                      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/>
                      <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                    </svg>
                  </button>
                </template>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 数据 tab — 业务数据查询 placeholder -->
      <div v-else-if="subTab === 'data'" class="dse-placeholder">
        <div class="dse-placeholder-icon">📊</div>
        <h3>业务数据预览</h3>
        <p>P2 接入 — 当前请用配置助手对话查询.</p>
        <p class="hint">例: "查询 {{ currentModel.model_code }} 表最近 20 条数据"</p>
      </div>

      <!-- SQL tab — 只读 SQL 片段示例 -->
      <div v-else-if="subTab === 'sql'" class="dse-sql-wrap">
        <div class="dse-sql-head">
          <span class="dse-sql-label">SQL 预览 (只读)</span>
          <button class="dse-btn dse-btn-ghost" disabled title="P2 接入">复制</button>
        </div>
        <pre class="dse-sql"><code class="mono">{{ sqlSnippet }}</code></pre>
        <p class="dse-sql-hint">
          aPaaS 平台默认建表语句 (只显结构, 不真跑). 改字段请用配置助手对话.
        </p>
      </div>

      <!-- 关系 tab — 显当前模型的 FK list -->
      <div v-else-if="subTab === 'relations'" class="dse-rel-wrap">
        <div v-if="foreignKeyFields.length === 0" class="dse-placeholder">
          <div class="dse-placeholder-icon">🔗</div>
          <h3>无外键关联</h3>
          <p>该模型未定义引用其他模型的字段.</p>
          <p class="hint">若需关联, 用配置助手对话新加引用字段 (类型 = 引用).</p>
        </div>
        <ul v-else class="dse-rel-list">
          <li v-for="(f, i) in foreignKeyFields" :key="getFieldKey(f, i)" class="dse-rel-item">
            <div class="dse-rel-from">
              <span class="mono">{{ currentModel.model_code }}</span>.<span class="mono dse-rel-col">{{ getFieldCode(f) }}</span>
            </div>
            <span class="dse-rel-arrow">→</span>
            <div class="dse-rel-to">
              <span class="mono dse-rel-ref">{{ getRefModelCode(f) }}</span>
              <span class="dse-rel-target">{{ getComment(f) || getFieldName(f) }}</span>
            </div>
          </li>
        </ul>
      </div>
    </template>

    <!-- ─── 新增 / 编辑 字段 dialog ───────────────────────────────────────── -->
    <Teleport to="body">
      <div
        v-if="dialogOpen"
        class="dse-modal-backdrop"
        role="dialog"
        aria-modal="true"
        :aria-label="dialogMode === 'add' ? '新增字段' : '编辑字段'"
        @click.self="closeDialog"
        @keydown.esc.stop="closeDialog"
      >
        <div class="dse-modal" tabindex="-1">
          <header class="dse-modal-head">
            <h3 class="dse-modal-title">
              {{ dialogMode === 'add' ? '新增字段' : `编辑字段 · ${dialogForm.original_field_code || ''}` }}
            </h3>
            <button class="dse-modal-close" type="button" aria-label="关闭" @click="closeDialog">×</button>
          </header>
          <div class="dse-modal-body">
            <div class="dse-form-row">
              <label class="dse-form-label">
                字段 Key
                <span class="dse-req">*</span>
              </label>
              <input
                v-model="dialogForm.field_code"
                class="dse-form-input mono"
                type="text"
                placeholder="例: order_amount (lower_snake_case)"
                autocomplete="off"
                :disabled="dialogSaving"
                maxlength="64"
              />
              <p v-if="fieldCodeWarn" class="dse-form-hint dse-form-warn">{{ fieldCodeWarn }}</p>
              <p v-else class="dse-form-hint">英文小写 + 下划线, 不超过 64 字符. 创建后不建议改 (会影响 apaas 数据).</p>
            </div>
            <div class="dse-form-row">
              <label class="dse-form-label">
                字段名称
                <span class="dse-req">*</span>
              </label>
              <input
                v-model="dialogForm.field_name"
                class="dse-form-input"
                type="text"
                placeholder="例: 订单金额"
                autocomplete="off"
                :disabled="dialogSaving"
                maxlength="64"
              />
            </div>
            <div class="dse-form-row dse-form-row-2col">
              <div>
                <label class="dse-form-label">类型</label>
                <select
                  v-model="dialogForm.field_type"
                  class="dse-form-input"
                  :disabled="dialogSaving || dialogMode === 'edit'"
                  :title="dialogMode === 'edit' ? 'apaas 平台不支持改字段类型, 留 P4' : ''"
                >
                  <option v-for="opt in DATA_TYPE_OPTIONS" :key="opt.code" :value="opt.code">
                    {{ opt.label }}
                  </option>
                </select>
              </div>
              <div v-if="showMaxLength">
                <label class="dse-form-label">长度</label>
                <input
                  v-model.number="dialogForm.max_length"
                  class="dse-form-input mono"
                  type="number"
                  min="1"
                  max="4000"
                  :disabled="dialogSaving"
                />
              </div>
              <div v-else>
                <label class="dse-form-label">必填</label>
                <label class="dse-switch">
                  <input
                    v-model="dialogForm.required"
                    type="checkbox"
                    :disabled="dialogSaving"
                  />
                  <span class="dse-switch-track"></span>
                  <span class="dse-switch-text">{{ dialogForm.required ? '必填' : '可空' }}</span>
                </label>
              </div>
            </div>
            <div v-if="showMaxLength" class="dse-form-row">
              <label class="dse-form-label">必填</label>
              <label class="dse-switch">
                <input
                  v-model="dialogForm.required"
                  type="checkbox"
                  :disabled="dialogSaving"
                />
                <span class="dse-switch-track"></span>
                <span class="dse-switch-text">{{ dialogForm.required ? '必填' : '可空' }}</span>
              </label>
            </div>
            <div class="dse-form-row">
              <label class="dse-form-label">注释 / 描述</label>
              <textarea
                v-model="dialogForm.comment"
                class="dse-form-input dse-form-textarea"
                rows="2"
                placeholder="字段用途说明 (可空)"
                :disabled="dialogSaving"
                maxlength="200"
              ></textarea>
            </div>
            <p v-if="dialogError" class="dse-modal-err">{{ dialogError }}</p>
          </div>
          <footer class="dse-modal-foot">
            <button
              class="dse-btn dse-btn-ghost"
              type="button"
              :disabled="dialogSaving"
              @click="closeDialog"
            >取消</button>
            <button
              class="dse-btn dse-btn-primary"
              type="button"
              :disabled="!dialogValid || dialogSaving"
              @click="submitDialog"
            >
              <span v-if="dialogSaving" class="dse-row-spinner">⟳</span>
              {{ dialogSaving ? '保存中…' : (dialogMode === 'add' ? '创建' : '保存') }}
            </button>
          </footer>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '@/utils/request'

interface FieldRow {
  field_id?: string
  field_code?: string
  code?: string
  field_name?: string
  name?: string
  data_type?: string
  field_type?: string
  type?: string
  max_length?: number | string
  length?: number | string
  size?: number | string
  required?: boolean
  nullable?: boolean
  description?: string
  comment?: string
  note?: string
  dictionary_code?: string
  ref_model_code?: string
  default_value?: string
  default?: string
  is_primary?: boolean
  is_index?: boolean
  is_unique?: boolean
  [k: string]: any
}

interface ModelDetail {
  model_id?: string
  model_code?: string
  model_name?: string
  model_type?: string
  is_main?: boolean
  fields?: FieldRow[]
  field_count?: number
  form_id?: string
  [k: string]: any
}

const props = defineProps<{
  appId: number
  menuId?: string
  menuName?: string
  formId?: string
}>()

const SUB_TABS = [
  { code: 'schema', label: 'Schema' },
  { code: 'data', label: '数据' },
  { code: 'sql', label: 'SQL' },
  { code: 'relations', label: '关系' },
] as const
type SubTabCode = (typeof SUB_TABS)[number]['code']

const subTab = ref<SubTabCode>('schema')
const allModels = ref<ModelDetail[]>([])
const loading = ref(false)
const error = ref('')

// ─── 选当前 model: 优先 form_id 匹配, 兜底 is_main=true, 再兜底第一个 ─────────
const currentModel = computed<ModelDetail | null>(() => {
  const list = allModels.value
  if (!list.length) return null
  // 1) form_id 匹配
  if (props.formId) {
    const byForm = list.find(m =>
      String(m.form_id || '') === String(props.formId)
      || String((m as any).extra?.form_id || '') === String(props.formId),
    )
    if (byForm) return byForm
  }
  // 2) is_main
  const mainModel = list.find(m => m.is_main === true)
  if (mainModel) return mainModel
  // 3) menu name 匹配 (兜底)
  if (props.menuName) {
    const byName = list.find(m => (m.model_name || '').includes(props.menuName || ''))
    if (byName) return byName
  }
  // 4) 第一个
  return list[0] || null
})

const fields = computed<FieldRow[]>(() => {
  const m = currentModel.value
  if (!m) return []
  return Array.isArray(m.fields) ? m.fields : []
})

const fieldCount = computed(() => fields.value.length)

// ─── DB type badge: DATABASE → MySQL, 其他显原值 ──────────────────────────────
const dbType = computed(() => {
  const t = String(currentModel.value?.model_type || '').toUpperCase()
  if (!t || t === 'DATABASE') return 'MySQL'
  return t
})

// ─── 主键名: field_code='id' 或 field_name 含'主键' 或 is_primary=true ───────
const primaryKeyName = computed(() => {
  const pk = fields.value.find(f => isPrimaryKey(f))
  if (!pk) return ''
  return getFieldCode(pk) || 'id'
})

// ─── 外键数: ref_model_code 非空的字段 ───────────────────────────────────────
const foreignKeyCount = computed(
  () => fields.value.filter(f => isForeignKey(f)).length,
)

const foreignKeyFields = computed(() => fields.value.filter(f => isForeignKey(f)))

// ─── SQL 片段 (只读, cosmetic) ──────────────────────────────────────────────
const sqlSnippet = computed(() => {
  const m = currentModel.value
  if (!m) return ''
  const tbl = m.model_code || 'unknown_table'
  const cols = fields.value.map(f => {
    const name = getFieldCode(f) || 'unknown'
    const type = formatSqlType(f)
    const nullStr = isRequired(f) ? 'NOT NULL' : 'NULL'
    const comment = getComment(f)
    const commentStr = comment ? ` COMMENT '${comment.replace(/'/g, "\\'")}'` : ''
    return `  \`${name}\` ${type} ${nullStr}${commentStr}`
  }).join(',\n')
  const pk = primaryKeyName.value
  const pkStr = pk ? `,\n  PRIMARY KEY (\`${pk}\`)` : ''
  return `-- ${m.model_name || tbl}\nCREATE TABLE \`${tbl}\` (\n${cols}${pkStr}\n) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;`
})

// ─── helper: field 字段 normalization ─────────────────────────────────────────
function getFieldKey(f: FieldRow, i: number): string {
  return String(f.field_id || f.field_code || f.code || i)
}
function getFieldCode(f: FieldRow): string {
  return String(f.field_code || f.code || '')
}
function getFieldName(f: FieldRow): string {
  return String(f.field_name || f.name || '')
}
function getComment(f: FieldRow): string {
  return String(f.description || f.comment || f.note || '')
}
function getDefaultValue(f: FieldRow): string {
  const v = f.default_value ?? f.default
  if (v == null || v === '') return '-'
  return String(v)
}
function isRequired(f: FieldRow): boolean {
  if (typeof f.required === 'boolean') return f.required
  if (typeof f.nullable === 'boolean') return !f.nullable
  return false
}

// 主键判断: is_primary 字段 / field_code='id' / field_name 含'主键'
function isPrimaryKey(f: FieldRow): boolean {
  if (f.is_primary === true) return true
  const code = getFieldCode(f).toLowerCase()
  if (code === 'id') return true
  const name = getFieldName(f)
  if (name === '主键' || name.includes('主键')) return true
  return false
}

function isForeignKey(f: FieldRow): boolean {
  return !!(f.ref_model_code && String(f.ref_model_code).trim())
}

function isIndex(f: FieldRow): boolean {
  return f.is_index === true
}

function isUnique(f: FieldRow): boolean {
  return f.is_unique === true
}

function getRefModelCode(f: FieldRow): string {
  return String(f.ref_model_code || '')
}

// 类型显示: data_type + max_length 拼成 SQL-style (VARCHAR(200), BIGINT, DATE, TEXT)
function formatSqlType(f: FieldRow): string {
  const raw = String(f.data_type || f.field_type || f.type || '').toUpperCase()
  if (!raw) return '—'
  const len = f.max_length || f.length || f.size
  // 映射到 SQL 类型 + length
  switch (raw) {
    case 'STRING':
      return len ? `VARCHAR(${len})` : 'VARCHAR(255)'
    case 'TEXT':
    case 'LONG_TEXT':
    case 'BIG_TEXT':
      return 'TEXT'
    case 'INTEGER':
    case 'INT':
      return 'BIGINT'
    case 'NUMBER':
      return 'DECIMAL(10,2)'
    case 'DECIMAL':
      return len ? `DECIMAL(${len})` : 'DECIMAL(10,2)'
    case 'DATE':
      return 'DATE'
    case 'DATETIME':
      return 'DATETIME'
    case 'TIMESTAMP':
      return 'TIMESTAMP'
    case 'BOOLEAN':
    case 'BOOL':
      return 'TINYINT(1)'
    case 'JSON':
      return 'JSON'
    case 'DICT':
      return len ? `VARCHAR(${len})` : 'VARCHAR(64)'
    case 'REF':
      return 'BIGINT'
    default:
      return len ? `${raw}(${len})` : raw
  }
}

// 键 badge 计算: PK / FK / IDX / UNIQ — 同一字段可叠加
interface KeyBadge {
  kind: 'PK' | 'FK' | 'IDX' | 'UNIQ'
  label: string
  title: string
}
function computeKeyBadges(f: FieldRow): KeyBadge[] {
  const out: KeyBadge[] = []
  if (isPrimaryKey(f)) {
    out.push({ kind: 'PK', label: 'PK', title: '主键 Primary Key' })
  }
  if (isForeignKey(f)) {
    out.push({
      kind: 'FK',
      label: 'FK',
      title: `外键 → ${getRefModelCode(f)}`,
    })
  }
  if (isUnique(f)) {
    out.push({ kind: 'UNIQ', label: 'UNIQ', title: '唯一索引 Unique' })
  }
  if (isIndex(f) && !isPrimaryKey(f) && !isUnique(f)) {
    out.push({ kind: 'IDX', label: 'IDX', title: '普通索引 Index' })
  }
  return out
}

// ─── 加载 ───────────────────────────────────────────────────────────────────
async function reload() {
  if (!props.appId || !props.menuId) {
    allModels.value = []
    return
  }
  loading.value = true
  error.value = ''
  try {
    // 优先: form_id → /forms/{form_id}/detail (跟 FormDesignerPanel 一致, 拿 form 真关联 model)
    if (props.formId) {
      const respFD = await request.get<any, any>(
        `/applications/${props.appId}/forms/${props.formId}/detail`,
      )
      if (respFD?.ok && Array.isArray(respFD.models) && respFD.models.length > 0) {
        const mainCode = String(respFD.main_model_code || '')
        allModels.value = respFD.models.map((m: any) => ({
          model_id: m.model_id,
          model_code: m.model_code,
          model_name: m.model_name,
          model_type: m.model_type,
          is_main: m.is_main === true || m.model_code === mainCode,
          fields: Array.isArray(m.fields) ? m.fields : [],
          field_count: m.field_count,
          form_id: props.formId,
        }))
        return
      }
    }
    // 兜底: 走 list_apaas_app_models (应用主表 list)
    const resp = await request.get<any, any>(
      `/applications/${props.appId}/section-content/models?with_fields=true`,
    )
    if (resp?.ok) {
      const items: any[] = resp.items || []
      allModels.value = items.map(it => {
        const raw = it.extra || {}
        return {
          model_id: raw.model_id || it.id,
          model_code: raw.model_code || it.code,
          model_name: raw.model_name || it.name,
          model_type: raw.model_type,
          is_main: raw.is_main === true,
          fields: Array.isArray(raw.fields) ? raw.fields : [],
          field_count: raw.field_count,
          form_id: raw.form_id,
          ...raw,
        }
      })
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

// ─── G4: 字段 CRUD ────────────────────────────────────────────────────────────

const DATA_TYPE_OPTIONS = [
  { code: 'STRING',      label: 'STRING (短文本)' },
  { code: 'BIG_TEXT',    label: 'BIG_TEXT (长文本)' },
  { code: 'BIGINT',      label: 'BIGINT (整数)' },
  { code: 'DECIMAL',     label: 'DECIMAL (小数)' },
  { code: 'DATE',        label: 'DATE (日期)' },
  { code: 'DATETIME',    label: 'DATETIME (日期时间)' },
  { code: 'BOOLEAN',     label: 'BOOLEAN (布尔)' },
  { code: 'DICT_SINGLE', label: 'DICT_SINGLE (字典单选)' },
  { code: 'REF',         label: 'REF (引用)' },
] as const

// 类型有 max_length 的: STRING / BIG_TEXT / DECIMAL
const TYPES_WITH_LENGTH = new Set(['STRING', 'BIG_TEXT', 'DECIMAL'])

// ─── canMutate: 应用是否已部署 + currentModel 有 model_id ──────────────────────
const canMutate = computed(() => {
  const m = currentModel.value
  if (!m) return false
  if (!m.model_id) return false
  return true
})

// 字段是否可编辑/删: 主键 + 缺 field_id 的不可
function canMutateField(f: FieldRow): boolean {
  if (!canMutate.value) return false
  if (!f.field_id) return false
  if (isPrimaryKey(f)) return false
  return true
}

// ─── row loading / error state ────────────────────────────────────────────────
const rowLoadingSet = ref<Set<string>>(new Set())
const rowErrorSet = ref<Set<string>>(new Set())

function rowKey(f: FieldRow): string {
  return String(f.field_id || f.field_code || f.code || '')
}
function isRowLoading(f: FieldRow): boolean {
  return rowLoadingSet.value.has(rowKey(f))
}
function hasRowError(f: FieldRow): boolean {
  return rowErrorSet.value.has(rowKey(f))
}
function markRowLoading(f: FieldRow, on: boolean) {
  const k = rowKey(f)
  const s = new Set(rowLoadingSet.value)
  if (on) s.add(k); else s.delete(k)
  rowLoadingSet.value = s
}
function markRowError(f: FieldRow, on: boolean) {
  const k = rowKey(f)
  const s = new Set(rowErrorSet.value)
  if (on) s.add(k); else s.delete(k)
  rowErrorSet.value = s
  if (on) {
    // 3s 自动清错误高亮
    setTimeout(() => {
      const s2 = new Set(rowErrorSet.value)
      s2.delete(k)
      rowErrorSet.value = s2
    }, 3000)
  }
}

// ─── inline 编辑 (字段 Key / 注释) ────────────────────────────────────────────
type InlineCol = 'field_code' | 'comment'

const editingFieldKey = ref('')
const editingCol = ref<InlineCol | ''>('')
const inlineValue = ref('')
const inlineInputs = ref<HTMLInputElement[] | null>(null)
let cancelInProgress = false  // ESC 后 blur 抑制

function isInlineEditing(f: FieldRow, col: InlineCol): boolean {
  return editingFieldKey.value === rowKey(f) && editingCol.value === col
}

function startInlineEdit(f: FieldRow, col: InlineCol) {
  if (!canMutateField(f)) return
  editingFieldKey.value = rowKey(f)
  editingCol.value = col
  inlineValue.value = col === 'field_code' ? getFieldCode(f) : getComment(f)
  nextTick(() => {
    const el = inlineInputs.value?.[0]
    if (el) {
      el.focus()
      el.select()
    }
  })
}

function cancelInlineEdit() {
  cancelInProgress = true
  editingFieldKey.value = ''
  editingCol.value = ''
  inlineValue.value = ''
  setTimeout(() => { cancelInProgress = false }, 50)
}

async function commitInlineEdit(f: FieldRow) {
  if (cancelInProgress) return
  if (editingFieldKey.value !== rowKey(f)) return
  const col = editingCol.value
  if (!col) return
  const newVal = String(inlineValue.value || '').trim()
  const oldVal = col === 'field_code' ? getFieldCode(f) : getComment(f)
  // 退出 inline mode
  editingFieldKey.value = ''
  editingCol.value = ''
  inlineValue.value = ''
  if (newVal === oldVal) return  // 无改动, 不调 endpoint
  if (col === 'field_code' && !newVal) {
    ElMessage.warning('字段 Key 不能为空')
    return
  }
  // 字段 Key 校验
  if (col === 'field_code' && !/^[a-z][a-z0-9_]{0,63}$/.test(newVal)) {
    ElMessage.warning('字段 Key 必须以小写字母开头, 仅含小写字母/数字/下划线')
    return
  }
  await callUpdateField(f, {
    field_code: col === 'field_code' ? newVal : getFieldCode(f),
    field_name: getFieldName(f),
    comment: col === 'comment' ? newVal : getComment(f),
  })
}

// ─── update endpoint 串 ───────────────────────────────────────────────────────
async function callUpdateField(
  f: FieldRow,
  patch: { field_code: string; field_name: string; comment: string; field_type?: string; max_length?: number },
) {
  const m = currentModel.value
  if (!m || !m.model_id) {
    ElMessage.error('当前模型缺 model_id, 无法保存')
    return
  }
  if (!f.field_id) {
    ElMessage.error('字段缺 field_id, 无法保存')
    return
  }
  markRowLoading(f, true)
  try {
    const resp = await request.post<any, any>(
      `/applications/${props.appId}/crud/model-field/update`,
      {
        model_id: String(m.model_id),
        field_id: String(f.field_id),
        field_code: patch.field_code,
        field_name: patch.field_name,
        field_type: patch.field_type || '',
        max_length: patch.max_length || 0,
        comment: patch.comment,
      },
    )
    if (resp?.ok) {
      ElMessage.success('字段已更新')
      await reload()
    } else {
      markRowError(f, true)
      ElMessage.error(resp?.message || resp?.error_code || '更新字段失败')
    }
  } catch (e: any) {
    markRowError(f, true)
    ElMessage.error(e?.response?.data?.detail || e?.message || '网络错误')
  } finally {
    markRowLoading(f, false)
  }
}

// ─── dialog state (add / edit) ────────────────────────────────────────────────
const dialogOpen = ref(false)
const dialogMode = ref<'add' | 'edit'>('add')
const dialogSaving = ref(false)
const dialogError = ref('')

interface DialogForm {
  field_code: string
  field_name: string
  field_type: string
  max_length: number
  required: boolean
  comment: string
  // edit only:
  field_id: string
  original_field_code: string
}
const dialogForm = reactive<DialogForm>({
  field_code: '',
  field_name: '',
  field_type: 'STRING',
  max_length: 255,
  required: false,
  comment: '',
  field_id: '',
  original_field_code: '',
})

const showMaxLength = computed(() => TYPES_WITH_LENGTH.has(dialogForm.field_type))

const fieldCodeWarn = computed(() => {
  const v = dialogForm.field_code.trim()
  if (!v) return ''
  if (!/^[a-z][a-z0-9_]{0,63}$/.test(v)) {
    return '需以小写字母开头, 仅含小写字母 / 数字 / 下划线'
  }
  return ''
})

const dialogValid = computed(() => {
  if (!dialogForm.field_code.trim() || !dialogForm.field_name.trim()) return false
  if (fieldCodeWarn.value) return false
  return true
})

function resetDialogForm() {
  dialogForm.field_code = ''
  dialogForm.field_name = ''
  dialogForm.field_type = 'STRING'
  dialogForm.max_length = 255
  dialogForm.required = false
  dialogForm.comment = ''
  dialogForm.field_id = ''
  dialogForm.original_field_code = ''
  dialogError.value = ''
}

function openAddDialog() {
  if (!canMutate.value) return
  resetDialogForm()
  dialogMode.value = 'add'
  dialogOpen.value = true
}

function openEditDialog(f: FieldRow) {
  if (!canMutateField(f)) return
  resetDialogForm()
  dialogMode.value = 'edit'
  dialogForm.field_id = String(f.field_id || '')
  dialogForm.field_code = getFieldCode(f)
  dialogForm.original_field_code = getFieldCode(f)
  dialogForm.field_name = getFieldName(f)
  // 反向映射: SQL type → enum (formatSqlType 输出近似 VARCHAR(255), 我们用 raw)
  const raw = String(f.data_type || f.field_type || f.type || '').toUpperCase()
  // 把老 alias 归到注册 type
  const mapped = mapRawToEnum(raw)
  dialogForm.field_type = mapped
  const len = Number(f.max_length || f.length || f.size || 0)
  dialogForm.max_length = len > 0 ? len : (TYPES_WITH_LENGTH.has(mapped) ? 255 : 0)
  dialogForm.required = isRequired(f)
  dialogForm.comment = getComment(f)
  dialogOpen.value = true
}

function mapRawToEnum(raw: string): string {
  switch (raw) {
    case 'STRING': return 'STRING'
    case 'TEXT':
    case 'LONG_TEXT':
    case 'BIG_TEXT': return 'BIG_TEXT'
    case 'INTEGER':
    case 'INT':
    case 'BIGINT': return 'BIGINT'
    case 'NUMBER':
    case 'DECIMAL': return 'DECIMAL'
    case 'DATE': return 'DATE'
    case 'DATETIME':
    case 'TIMESTAMP': return 'DATETIME'
    case 'BOOLEAN':
    case 'BOOL': return 'BOOLEAN'
    case 'DICT':
    case 'DICT_SINGLE': return 'DICT_SINGLE'
    case 'REF': return 'REF'
    default: return 'STRING'
  }
}

function closeDialog() {
  if (dialogSaving.value) return
  dialogOpen.value = false
}

async function submitDialog() {
  if (!dialogValid.value || dialogSaving.value) return
  const m = currentModel.value
  if (!m || !m.model_id) {
    dialogError.value = '当前模型缺 model_id, 无法保存'
    return
  }
  const payloadCommon = {
    model_id: String(m.model_id),
    field_code: dialogForm.field_code.trim(),
    field_name: dialogForm.field_name.trim(),
    field_type: dialogForm.field_type,
    max_length: TYPES_WITH_LENGTH.has(dialogForm.field_type) ? (dialogForm.max_length || 255) : 0,
    comment: dialogForm.comment.trim(),
  }
  dialogSaving.value = true
  dialogError.value = ''
  try {
    if (dialogMode.value === 'add') {
      const resp = await request.post<any, any>(
        `/applications/${props.appId}/crud/model-field/add`,
        {
          ...payloadCommon,
          model_code: String(m.model_code || ''),
        },
      )
      if (resp?.ok) {
        ElMessage.success(`字段 ${payloadCommon.field_code} 已创建`)
        dialogOpen.value = false
        await reload()
      } else {
        dialogError.value = resp?.message || resp?.error_code || '创建字段失败'
      }
    } else {
      // edit
      if (!dialogForm.field_id) {
        dialogError.value = '字段缺 field_id, 无法保存'
        return
      }
      const resp = await request.post<any, any>(
        `/applications/${props.appId}/crud/model-field/update`,
        {
          ...payloadCommon,
          field_id: dialogForm.field_id,
          // 不改类型 (apaas 不支持), 留空让 backend 跳过
          field_type: '',
          max_length: 0,
        },
      )
      if (resp?.ok) {
        ElMessage.success('字段已更新')
        dialogOpen.value = false
        await reload()
      } else {
        dialogError.value = resp?.message || resp?.error_code || '更新字段失败'
      }
    }
  } catch (e: any) {
    dialogError.value = e?.response?.data?.detail || e?.message || '网络错误'
  } finally {
    dialogSaving.value = false
  }
}

// ─── 删除字段 (apaas 软删) ─────────────────────────────────────────────────────
async function confirmDeleteField(f: FieldRow) {
  if (!canMutateField(f)) return
  const fieldDisplayName = getFieldName(f) || getFieldCode(f) || '该字段'
  try {
    await ElMessageBox.confirm(
      `删除字段 "${fieldDisplayName}" — 真存到 apaas (apaas 软删, 数据保留, 可后续恢复)?`,
      '确认删除字段',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning',
        confirmButtonClass: 'el-button--danger',
      },
    )
  } catch {
    return  // user cancel
  }
  const m = currentModel.value
  if (!m || !m.model_id || !f.field_id) {
    ElMessage.error('缺 model_id / field_id, 无法删除')
    return
  }
  markRowLoading(f, true)
  try {
    const resp = await request.post<any, any>(
      `/applications/${props.appId}/crud/model-field/disable`,
      {
        model_id: String(m.model_id),
        field_id: String(f.field_id),
        field_code: getFieldCode(f),
        field_name: getFieldName(f) || getFieldCode(f),
      },
    )
    if (resp?.ok) {
      ElMessage.success(`字段 ${getFieldCode(f)} 已删除`)
      await reload()
    } else {
      markRowError(f, true)
      ElMessage.error(resp?.message || resp?.error_code || '删除失败')
    }
  } catch (e: any) {
    markRowError(f, true)
    ElMessage.error(e?.response?.data?.detail || e?.message || '网络错误')
  } finally {
    markRowLoading(f, false)
  }
}
</script>

<style scoped>
.dse {
  font-family: var(--font-sans);
  color: var(--text);
  padding: 28px 36px;
  background: var(--bg);
  height: 100%;
  overflow-y: auto;
  font-feature-settings: 'cv11', 'ss01';
}

.dse-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  height: 100%;
  color: var(--text-3);
  gap: 12px;
}
.dse-empty-icon { font-size: 48px; line-height: 1; }
.dse-empty h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--text);
}
.dse-empty p {
  margin: 0;
  font-size: 13.5px;
}

/* ─── 表头 ─────────────────────────────────────────────────────────────── */
.dse-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 18px;
  padding-bottom: 18px;
  border-bottom: 1px solid var(--line);
}

.dse-head-meta {
  flex: 1;
  min-width: 0;
}

.dse-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.dse-title {
  margin: 0;
  font-size: 24px;
  font-weight: 600;
  color: var(--text);
  letter-spacing: -0.3px;
  font-family: var(--font-mono);
}

.dse-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  font-size: 12px;
  font-weight: 500;
  border-radius: 4px;
  white-space: nowrap;
}
.dse-badge-db {
  background: var(--brand-soft);
  color: var(--brand);
  font-family: var(--font-mono);
}
.dse-badge-primary {
  background: var(--brand-soft);
  color: var(--brand);
}
.dse-badge-secondary {
  background: var(--surface-3);
  color: var(--text-3);
}

.dse-stats {
  margin: 0;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-3);
}
.dse-stats code {
  padding: 1px 6px;
  background: var(--surface-2);
  border-radius: 3px;
  font-size: 12px;
  color: var(--text-2);
}
.dse-stat-sep { color: var(--text-4); }

.dse-head-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.dse-btn {
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
.dse-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.dse-btn-ghost {
  background: var(--surface);
  border-color: var(--line-strong);
  color: var(--text);
}
.dse-btn-ghost:hover:not(:disabled) {
  border-color: var(--brand);
  color: var(--brand);
}
.dse-btn-primary {
  background: var(--brand);
  color: #fff;
}
.dse-btn-primary:hover:not(:disabled) {
  background: var(--brand-hover);
}
.dse-btn-icon {
  font-size: 13px;
  line-height: 1;
}

/* ─── sub-tab nav ──────────────────────────────────────────────────────── */
.dse-subnav {
  display: flex;
  gap: 4px;
  margin-bottom: 14px;
  border-bottom: 1px solid var(--line);
}
.dse-subnav-tab {
  height: 34px;
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
}
.dse-subnav-tab:hover { color: var(--text); }
.dse-subnav-tab.active {
  color: var(--brand);
  border-bottom-color: var(--brand);
}

/* ─── 字段 table ───────────────────────────────────────────────────────── */
.dse-table-wrap {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 10px;
  overflow: hidden;
  box-shadow: var(--sh-1);
}

.dse-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  table-layout: fixed;
}

.dse-table th {
  text-align: left;
  padding: 11px 14px;
  background: var(--surface-2);
  font-weight: 500;
  color: var(--text-3);
  font-size: 12.5px;
  border-bottom: 1px solid var(--line);
  white-space: nowrap;
}
.dse-table th.num { width: 40px; text-align: center; }
.dse-table th.col-field { width: 180px; }
.dse-table th.col-type { width: 180px; }
.dse-table th.col-null { width: 60px; text-align: center; }
.dse-table th.col-key { width: 130px; }
.dse-table th.col-default { width: 120px; }
.dse-table th.col-comment { /* flex */ }
.dse-table th.col-ops { width: 80px; text-align: center; }

.dse-table td {
  padding: 12px 14px;
  border-bottom: 1px solid var(--line);
  color: var(--text);
  vertical-align: middle;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dse-table tr:last-child td { border-bottom: none; }
.dse-table tr:hover td:not(.empty) { background: var(--surface-2); }
.dse-table .num { color: var(--text-4); text-align: center; }
.dse-table .mono {
  font-family: var(--font-mono);
  font-size: 12.5px;
  color: var(--text-2);
}
.dse-table .muted { color: var(--text-3); }
.dse-table .col-null { text-align: center; }
.dse-table .col-ops { text-align: center; }
.dse-table .empty {
  text-align: center;
  padding: 48px 14px;
  color: var(--text-4);
}
.dse-table .empty .hint {
  margin-top: 8px;
  font-size: 12px;
}

.dse-type-text {
  color: var(--text-2);
  font-size: 12.5px;
}

.dse-null-yes {
  color: var(--ok);
  font-weight: 600;
  font-size: 14px;
}
.dse-null-no {
  color: var(--text-4);
  font-weight: 500;
  font-size: 14px;
}

/* 键 badges */
.dse-key-badge {
  display: inline-block;
  padding: 1px 6px;
  margin-right: 4px;
  font-size: 10.5px;
  font-weight: 600;
  font-family: var(--font-mono);
  border-radius: 3px;
  letter-spacing: 0.3px;
  vertical-align: middle;
}
.dse-key-pk {
  background: var(--brand-soft);
  color: var(--brand);
}
.dse-key-fk {
  /* token 没紫色, 用 brand-soft-2 区分 */
  background: var(--brand-soft-2);
  color: var(--brand-hover);
}
.dse-key-idx {
  background: var(--warn-soft);
  color: var(--warn);
}
.dse-key-uniq {
  background: var(--ok-soft);
  color: var(--ok);
}
.dse-empty-cell {
  color: var(--text-4);
}

.dse-default {
  color: var(--text-3);
  font-size: 12.5px;
}

.dse-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  margin-right: 4px;
  padding: 0;
  background: transparent;
  border: 1px solid var(--line);
  border-radius: 4px;
  color: var(--text-3);
  cursor: pointer;
  transition: background 0.12s, color 0.12s, border-color 0.12s;
}
.dse-icon-btn:hover:not(:disabled) {
  background: var(--brand-soft);
  color: var(--brand);
  border-color: var(--brand);
}
.dse-icon-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.dse-icon-btn:last-child { margin-right: 0; }

/* ─── 数据 tab placeholder ─────────────────────────────────────────────── */
.dse-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 64px 24px;
  color: var(--text-3);
  gap: 10px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 10px;
}
.dse-placeholder-icon { font-size: 40px; line-height: 1; }
.dse-placeholder h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--text);
}
.dse-placeholder p {
  margin: 0;
  font-size: 13px;
}
.dse-placeholder .hint {
  font-size: 12px;
  color: var(--text-4);
  font-family: var(--font-mono);
}

/* ─── SQL tab ──────────────────────────────────────────────────────────── */
.dse-sql-wrap {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 10px;
  overflow: hidden;
  box-shadow: var(--sh-1);
}
.dse-sql-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  background: var(--surface-2);
  border-bottom: 1px solid var(--line);
}
.dse-sql-label {
  font-size: 12.5px;
  color: var(--text-3);
  font-weight: 500;
}
.dse-sql {
  margin: 0;
  padding: 18px 22px;
  font-family: var(--font-mono);
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--text-2);
  white-space: pre;
  overflow-x: auto;
  background: var(--surface);
}
.dse-sql-hint {
  margin: 0;
  padding: 10px 16px;
  font-size: 12px;
  color: var(--text-4);
  background: var(--surface-2);
  border-top: 1px solid var(--line);
}

/* ─── 关系 tab ─────────────────────────────────────────────────────────── */
.dse-rel-wrap {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 10px;
  overflow: hidden;
  box-shadow: var(--sh-1);
}
.dse-rel-list {
  list-style: none;
  margin: 0;
  padding: 0;
}
.dse-rel-item {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 14px 18px;
  border-bottom: 1px solid var(--line);
}
.dse-rel-item:last-child { border-bottom: none; }
.dse-rel-from, .dse-rel-to {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.dse-rel-col {
  color: var(--brand);
}
.dse-rel-arrow {
  color: var(--text-4);
  font-size: 18px;
  font-weight: 300;
}
.dse-rel-ref {
  color: var(--brand-hover);
  background: var(--brand-soft);
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12.5px;
}
.dse-rel-target {
  color: var(--text-3);
  font-size: 12.5px;
}

/* ─── state (loading / error) ──────────────────────────────────────────── */
.dse-state {
  padding: 48px;
  text-align: center;
  color: var(--text-3);
  font-size: 14px;
}
.dse-state-err { color: var(--err); }
.dse-state-err .dse-btn { margin-top: 12px; margin-left: 8px; }

/* mono 类全局 */
.mono {
  font-family: var(--font-mono);
}

/* ─── G4: row loading / error ──────────────────────────────────────────── */
.dse-row-loading td {
  background: var(--surface-2) !important;
  opacity: 0.55;
  pointer-events: none;
  cursor: progress;
}
.dse-row-error td {
  border-left: 3px solid var(--err);
}
.dse-row-error td:first-child {
  border-left: 3px solid var(--err);
}

.dse-row-spinner {
  display: inline-block;
  font-size: 14px;
  color: var(--brand);
  animation: dse-spin 0.9s linear infinite;
  font-family: var(--font-mono);
}
@keyframes dse-spin {
  to { transform: rotate(360deg); }
}

/* ─── G4: inline 编辑 cell ─────────────────────────────────────────────── */
.dse-cell-text {
  display: inline-block;
  width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dse-cell-editable {
  cursor: text;
  border-radius: 3px;
  padding: 2px 4px;
  margin: -2px -4px;
  transition: background 0.12s;
}
.dse-cell-editable:hover:not(.dse-cell-disabled) {
  background: var(--brand-soft);
}
.dse-cell-disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.dse-cell-input {
  width: 100%;
  height: 28px;
  padding: 2px 6px;
  font-size: 12.5px;
  font-family: inherit;
  color: var(--text);
  background: var(--surface);
  border: 1.5px solid var(--brand);
  border-radius: 4px;
  outline: none;
  box-shadow: 0 0 0 2px var(--brand-soft);
}
.dse-cell-input.mono {
  font-family: var(--font-mono);
}

.dse-icon-btn-danger:hover:not(:disabled) {
  background: var(--err-soft, #fef0f0);
  color: var(--err);
  border-color: var(--err);
}

/* ─── G4: modal dialog ─────────────────────────────────────────────────── */
.dse-modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  backdrop-filter: blur(2px);
  animation: dse-fadein 0.14s ease-out;
}
@keyframes dse-fadein {
  from { opacity: 0; }
  to { opacity: 1; }
}

.dse-modal {
  width: 100%;
  max-width: 480px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 14px;
  box-shadow: var(--sh-3, 0 25px 50px -12px rgba(0,0,0,0.25));
  font-family: var(--font-sans);
  color: var(--text);
  display: flex;
  flex-direction: column;
  max-height: calc(100vh - 48px);
  outline: none;
  animation: dse-modal-in 0.18s cubic-bezier(.16,1,.3,1);
}
@keyframes dse-modal-in {
  from { opacity: 0; transform: translateY(8px) scale(0.98); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}

.dse-modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px 12px;
  border-bottom: 1px solid var(--line);
}
.dse-modal-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
}
.dse-modal-close {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  background: transparent;
  border: none;
  color: var(--text-3);
  font-size: 22px;
  line-height: 1;
  cursor: pointer;
  transition: background 0.12s, color 0.12s;
}
.dse-modal-close:hover {
  background: var(--surface-2);
  color: var(--text);
}

.dse-modal-body {
  padding: 18px 20px;
  overflow-y: auto;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.dse-form-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.dse-form-row-2col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.dse-form-row-2col > div {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.dse-form-label {
  font-size: 12.5px;
  font-weight: 500;
  color: var(--text-2);
}
.dse-req {
  color: var(--err);
  margin-left: 2px;
}
.dse-form-input {
  width: 100%;
  height: 34px;
  padding: 0 10px;
  font-size: 13px;
  font-family: inherit;
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--line-strong);
  border-radius: 6px;
  outline: none;
  transition: border-color 0.12s, box-shadow 0.12s;
}
.dse-form-input:focus {
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft);
}
.dse-form-input:disabled {
  background: var(--surface-2);
  color: var(--text-3);
  cursor: not-allowed;
}
.dse-form-input.mono {
  font-family: var(--font-mono);
}
select.dse-form-input {
  cursor: pointer;
  appearance: none;
  padding-right: 28px;
  background-image: url("data:image/svg+xml,%3Csvg width='10' height='6' viewBox='0 0 10 6' fill='none' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M1 1L5 5L9 1' stroke='%23666' stroke-width='1.5'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 10px center;
}
.dse-form-textarea {
  height: auto;
  padding: 8px 10px;
  font-family: inherit;
  resize: vertical;
  min-height: 56px;
}
.dse-form-hint {
  margin: 0;
  font-size: 11.5px;
  color: var(--text-4);
  line-height: 1.4;
}
.dse-form-warn {
  color: var(--warn);
}

.dse-switch {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 34px;
  cursor: pointer;
  user-select: none;
}
.dse-switch input {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}
.dse-switch-track {
  display: inline-block;
  position: relative;
  width: 36px;
  height: 20px;
  background: var(--surface-3, var(--surface-2));
  border-radius: 999px;
  transition: background 0.18s;
}
.dse-switch-track::after {
  content: '';
  position: absolute;
  top: 2px;
  left: 2px;
  width: 16px;
  height: 16px;
  background: #fff;
  border-radius: 50%;
  box-shadow: 0 1px 2px rgba(0,0,0,0.15);
  transition: transform 0.18s;
}
.dse-switch input:checked + .dse-switch-track {
  background: var(--brand);
}
.dse-switch input:checked + .dse-switch-track::after {
  transform: translateX(16px);
}
.dse-switch input:disabled + .dse-switch-track {
  opacity: 0.5;
  cursor: not-allowed;
}
.dse-switch-text {
  font-size: 12.5px;
  color: var(--text-2);
}

.dse-modal-err {
  margin: 0;
  padding: 8px 12px;
  background: var(--err-soft, #fef0f0);
  color: var(--err);
  font-size: 12.5px;
  border-radius: 6px;
  border: 1px solid var(--err);
}

.dse-modal-foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 20px 16px;
  border-top: 1px solid var(--line);
}
.dse-modal-foot .dse-row-spinner {
  margin-right: 4px;
}
</style>
