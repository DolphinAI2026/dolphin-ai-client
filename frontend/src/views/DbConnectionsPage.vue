<template>
  <BuilderFrame :breadcrumbs="[{ label: '设置' }, { label: '数据源' }]">
    <template #actions>
      <button class="new-btn" @click="openCreate">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        新增连接
      </button>
    </template>
    <div class="db-main builder-page">
      <div class="page-header">
        <div class="page-title">数据源</div>
        <div class="page-summary">{{ connections.length }} 个数据源</div>
      </div>

      <div class="content-wrap">
        <div v-if="loading" class="empty-state">
          <SkeletonCard :lines="4" with-footer />
        </div>
        <div v-else-if="connections.length === 0" class="empty-state">
          <EmptyState
            title="暂无数据源"
            desc="添加一个连接，让 AI 直接读你的存量数据。支持 MYSQL / PostgreSQL / Oracle 等 6 种。"
          >
            <template #icon>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>
            </template>
            <template #cta>
              <button class="empty-add-btn" @click="openCreate">添加第一个连接</button>
            </template>
          </EmptyState>
        </div>

        <el-table
          v-else
          :data="connections"
          stripe
          class="db-table"
          row-key="id"
          :header-cell-style="{ background: 'var(--b-bg-sub)', color: 'var(--b-text-muted)', fontWeight: '700', fontSize: '12px' }"
        >
          <el-table-column prop="name" label="名称" min-width="160">
            <template #default="{ row }">
              <span class="cell-name">{{ row.name }}</span>
              <div v-if="row.description" class="cell-desc">{{ row.description }}</div>
            </template>
          </el-table-column>
          <el-table-column prop="db_type" label="类型" width="130">
            <template #default="{ row }">
              <span class="db-type-tag">{{ row.db_type }}</span>
            </template>
          </el-table-column>
          <el-table-column label="连接地址" min-width="220">
            <template #default="{ row }">
              <span class="cell-mono">{{ row.host }}:{{ row.port }}</span>
              <div class="cell-database">/{{ row.database }}</div>
            </template>
          </el-table-column>
          <el-table-column prop="username" label="用户名" width="140">
            <template #default="{ row }">
              <span class="cell-mono">{{ row.username }}</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <span class="status-chip" :class="statusClass(row)">{{ statusLabel(row) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="表数" width="80" align="right">
            <template #default="{ row }">
              <span v-if="row.status === 'active' && row.table_count >= 0" class="cell-mono">{{ row.table_count }}</span>
              <span v-else class="cell-faint">-</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="100" align="center" fixed="right">
            <template #default="{ row }">
              <el-dropdown trigger="click" @command="(cmd: string) => onCommand(cmd, row)">
                <button class="more-btn" type="button">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="1"/><circle cx="12" cy="5" r="1"/><circle cx="12" cy="19" r="1"/></svg>
                </button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="test" :disabled="row._testing">
                      {{ row._testing ? '测试中...' : '测试连接' }}
                    </el-dropdown-item>
                    <el-dropdown-item command="edit">编辑</el-dropdown-item>
                    <el-dropdown-item command="tables">查看表清单</el-dropdown-item>
                    <el-dropdown-item command="delete" divided class="danger-item">删除</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <!-- ==================== 新增 / 编辑 Dialog ==================== -->
      <el-dialog
        v-model="dialogVisible"
        :title="editing ? '编辑数据源' : '新增数据源'"
        width="560px"
        :close-on-click-modal="false"
        class="env-dialog"
        :append-to-body="true"
      >
        <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="env-form">
          <el-form-item label="名称" prop="name" required>
            <el-input v-model="form.name" placeholder="如：生产 ERP、测试 aiagent" />
          </el-form-item>

          <div class="row-2cols">
            <el-form-item label="类型" prop="db_type" required class="col-grow">
              <el-select v-model="form.db_type" placeholder="选择数据库类型" style="width: 100%" @change="onTypeChange">
                <el-option v-for="t in DB_TYPES" :key="t" :label="t" :value="t" />
              </el-select>
            </el-form-item>
            <el-form-item label="端口" prop="port" required class="col-port">
              <el-input-number v-model="form.port" :min="1" :max="65535" controls-position="right" style="width: 100%" />
            </el-form-item>
          </div>

          <el-form-item label="主机" prop="host" required>
            <el-input v-model="form.host" placeholder="如：10.0.0.5 或 mysql.internal" />
          </el-form-item>

          <el-form-item label="数据库" prop="database" required>
            <el-input v-model="form.database" placeholder="数据库名称" />
          </el-form-item>

          <el-form-item label="用户名" prop="username" required>
            <el-input v-model="form.username" placeholder="登录用户名" />
          </el-form-item>

          <el-form-item label="密码" :prop="editing ? '' : 'password'" :required="!editing">
            <el-input
              v-model="form.password"
              type="password"
              show-password
              :placeholder="editing ? '保留原密码（留空即不更新）' : '登录密码'"
            />
          </el-form-item>

          <el-form-item label="描述">
            <el-input v-model="form.description" type="textarea" :rows="2" placeholder="可选，方便识别用途" />
          </el-form-item>
        </el-form>

        <template #footer>
          <el-button @click="dialogVisible = false">取消</el-button>
          <el-button type="primary" @click="handleSave" :loading="saving">
            {{ editing ? '保存' : '添加' }}
          </el-button>
        </template>
      </el-dialog>

      <!-- ==================== 表清单 Dialog ==================== -->
      <el-dialog
        v-model="tablesDialogVisible"
        :title="`表清单 — ${tablesDialogName}`"
        width="640px"
        :close-on-click-modal="false"
        class="env-dialog"
        :append-to-body="true"
      >
        <div v-if="tablesLoading" class="empty-state" style="padding: 16px 0">
          <SkeletonCard :lines="4" />
        </div>
        <div v-else-if="tablesList.length === 0" class="empty-state" style="padding: 16px 0">
          <EmptyState
            variant="filtered"
            title="未发现可读取的表"
            desc="这个数据库里没有用户级表，或者权限不够列出表。换个数据库或检查账号权限。"
          >
            <template #icon>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
            </template>
          </EmptyState>
        </div>
        <template v-else>
          <div class="tables-summary">共 {{ tablesList.length }} 张表</div>
          <el-table :data="tablesList" stripe max-height="420" class="db-table">
            <el-table-column prop="name" label="表名" min-width="240">
              <template #default="{ row }">
                <span class="cell-mono">{{ row.name }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="fields" label="字段数" width="120" align="right">
              <template #default="{ row }">
                <span class="cell-mono">{{ row.fields }}</span>
              </template>
            </el-table-column>
          </el-table>
        </template>
        <template #footer>
          <el-button type="primary" @click="tablesDialogVisible = false">关闭</el-button>
        </template>
      </el-dialog>
    </div>
  </BuilderFrame>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { handleError } from '@/utils/errorHandler'
import { dbConnectionApi, type DbConnection, type DbType, type DbTableSummary } from '@/api/dbConnections'
import BuilderFrame from '@/components/BuilderFrame.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import SkeletonCard from '@/components/states/SkeletonCard.vue'

const DB_TYPES: DbType[] = ['MYSQL', 'PostgreSQL', 'SQLServer', 'ORACLE', 'DAMENG', 'KingBase']

const PORT_DEFAULTS: Record<DbType, number> = {
  MYSQL: 3306,
  PostgreSQL: 5432,
  SQLServer: 1433,
  ORACLE: 1521,
  DAMENG: 5236,
  KingBase: 54321,
}

interface DbConnectionWithUI extends DbConnection {
  _testing?: boolean
}

const connections = ref<DbConnectionWithUI[]>([])
const loading = ref(true)
const dialogVisible = ref(false)
const editing = ref<DbConnection | null>(null)
const saving = ref(false)
const formRef = ref<FormInstance>()

const form = reactive({
  name: '',
  db_type: 'MYSQL' as DbType,
  host: '',
  port: 3306,
  database: '',
  username: '',
  password: '',
  description: '',
})

const rules = reactive<FormRules>({
  name: [{ required: true, message: '请填写名称', trigger: 'blur' }],
  db_type: [{ required: true, message: '请选择类型', trigger: 'change' }],
  host: [{ required: true, message: '请填写主机', trigger: 'blur' }],
  port: [{ required: true, message: '请填写端口', trigger: 'blur' }],
  database: [{ required: true, message: '请填写数据库名', trigger: 'blur' }],
  username: [{ required: true, message: '请填写用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请填写密码', trigger: 'blur' }],
})

function resetForm() {
  form.name = ''
  form.db_type = 'MYSQL'
  form.host = ''
  form.port = PORT_DEFAULTS.MYSQL
  form.database = ''
  form.username = ''
  form.password = ''
  form.description = ''
  formRef.value?.clearValidate()
}

function openCreate() {
  editing.value = null
  resetForm()
  dialogVisible.value = true
}

function openEdit(c: DbConnection) {
  editing.value = c
  form.name = c.name
  form.db_type = c.db_type
  form.host = c.host
  form.port = c.port
  form.database = c.database
  form.username = c.username
  form.password = ''
  form.description = c.description || ''
  formRef.value?.clearValidate()
  dialogVisible.value = true
}

function onTypeChange(t: DbType) {
  form.db_type = t
  // 端口仍是某个 type 的默认值时，跟随类型切换
  if (Object.values(PORT_DEFAULTS).includes(form.port)) {
    form.port = PORT_DEFAULTS[t]
  }
}

function statusClass(c: DbConnection): string {
  if (!c.last_tested_at) return 'unverified'
  return c.status === 'active' ? 'active' : 'disconnected'
}

function statusLabel(c: DbConnection): string {
  if (!c.last_tested_at) return '未验证'
  return c.status === 'active' ? '已连接' : '断开'
}

async function loadConnections() {
  loading.value = true
  try {
    const list = await dbConnectionApi.list()
    connections.value = Array.isArray(list) ? list : []
  } catch {
    connections.value = []
  }
  loading.value = false
}

async function handleSave() {
  if (!formRef.value) return
  try {
    await formRef.value.validate()
  } catch {
    return
  }
  saving.value = true
  try {
    if (editing.value) {
      const data: any = {
        name: form.name,
        db_type: form.db_type,
        host: form.host,
        port: form.port,
        database: form.database,
        username: form.username,
        description: form.description,
      }
      if (form.password) data.password = form.password
      await dbConnectionApi.update(editing.value.id, data)
      ElMessage.success('已更新')
    } else {
      await dbConnectionApi.create({
        name: form.name,
        db_type: form.db_type,
        host: form.host,
        port: form.port,
        database: form.database,
        username: form.username,
        password: form.password,
        description: form.description || undefined,
      })
      ElMessage.success('已添加')
    }
    dialogVisible.value = false
    await loadConnections()
  } catch (e: any) {
    handleError(e, { fallback: '操作失败' })
  }
  saving.value = false
}

async function handleTest(c: DbConnectionWithUI) {
  c._testing = true
  try {
    const res = await dbConnectionApi.test(c.id)
    if (res.ok) {
      ElMessage.success(`连接成功，发现 ${res.table_count} 张表`)
      c.status = 'active'
      c.table_count = res.table_count
      c.last_tested_at = new Date().toISOString()
    } else {
      ElMessage.error(res.error || '连接失败')
      c.status = 'disconnected'
    }
  } catch (e: any) {
    handleError(e, { fallback: '测试失败' })
  }
  c._testing = false
}

async function handleDelete(c: DbConnection) {
  try {
    await ElMessageBox.confirm(
      `确定删除「${c.name}」？该操作不可恢复，但如有应用引用该连接将不受影响。`,
      '删除数据源',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
  } catch {
    return
  }
  try {
    await dbConnectionApi.delete(c.id)
    ElMessage.success('已删除')
    await loadConnections()
  } catch (e: any) {
    handleError(e, { fallback: '删除失败' })
  }
}

// ── 表清单 ──
const tablesDialogVisible = ref(false)
const tablesDialogName = ref('')
const tablesLoading = ref(false)
const tablesList = ref<DbTableSummary[]>([])

async function handleViewTables(c: DbConnection) {
  tablesDialogName.value = c.name
  tablesDialogVisible.value = true
  tablesLoading.value = true
  tablesList.value = []
  try {
    const res = await dbConnectionApi.tables(c.id)
    tablesList.value = Array.isArray(res?.tables) ? res.tables : []
  } catch (e: any) {
    handleError(e, { fallback: '获取表清单失败' })
  }
  tablesLoading.value = false
}

function onCommand(cmd: string, row: DbConnectionWithUI) {
  if (cmd === 'test') handleTest(row)
  else if (cmd === 'edit') openEdit(row)
  else if (cmd === 'tables') handleViewTables(row)
  else if (cmd === 'delete') handleDelete(row)
}

onMounted(() => {
  loadConnections()
})
</script>

<style scoped>
/* v3 redesign · 2026-05-20 — visual refresh only, template/script untouched.
   Preserved (don't change):
     - All selector names (.db-main / .new-btn / .db-type-tag / .status-chip / .more-btn ...)
     - Layout topology, grid, scroll behavior, BuilderFrame slot wiring
     - 6 DB type pills (one chip style, mono font — not 6 colors)
     - 3-state status chip mapping (active / disconnected / unverified)
     - :global(html[data-theme="dark"]) override hook for unverified amber lift
   Refreshed:
     - --b-* tokens → v3 (--brand / --brand-soft / --ok / --ok-soft / --warn-soft / --line / --text / --text-2 / --text-3)
     - Solid ink button → brand fill (matches design spec 06.1.A "新建连接" primary CTA)
     - radius 7 / 8 → --r-2 (6) for chips, --r-3 (8) for buttons, --r-full (999) for status pills
     - transition 0.2s → 0.14s var(--ease) — snappier per v3 motion table
     - shadow added on .new-btn hover via --sh-brand (was opacity-only fade)
     - .db-type-tag: brand-soft + mono font (per spec規範: "6 种 DB 类型用同款灰 chip + 文字区分 mono font，不要给每种 DB 配色")
*/

.db-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
  background: var(--bg);
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  max-width: 1180px;
  margin: 0 auto 2px;
  width: 100%;
  padding: 0;
  flex-shrink: 0;
  box-sizing: border-box;
}

.page-title {
  font-size: 15px;
  font-weight: var(--fw-semibold, 600);
  color: var(--text);
  letter-spacing: -0.005em;
}

.page-summary {
  color: var(--text-3);
  font-size: 12px;
  font-family: var(--font-mono);
}

.new-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  height: 30px;
  background: var(--brand);
  color: var(--text-inverse, #fff);
  border: 1px solid var(--brand);
  padding: 0 12px;
  border-radius: var(--r-2, 6px);
  font-size: 12px;
  font-weight: var(--fw-semibold, 600);
  cursor: pointer;
  font-family: inherit;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              box-shadow 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.new-btn:hover {
  background: var(--brand-hover);
  border-color: var(--brand-hover);
  box-shadow: var(--sh-brand);
}
.new-btn:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 2px;
}

/* Dark-theme :global override hook — preserved per task contract.
   v3 dark already flips --brand to a lighter blue, so simpler rules suffice. */
:global(html[data-theme="dark"]) .new-btn,
:global(html[data-theme="dark"]) .empty-add-btn {
  background: var(--brand-soft);
  border-color: var(--brand-ring);
  color: var(--brand-text);
  box-shadow: none;
}
:global(html[data-theme="dark"]) .new-btn:hover,
:global(html[data-theme="dark"]) .empty-add-btn:hover {
  background: var(--brand-soft-2);
  border-color: var(--brand);
  color: var(--text);
}

.content-wrap {
  flex: 1;
  overflow-y: auto;
  max-width: 1180px;
  margin: 0 auto;
  width: 100%;
  padding: 0 0 44px;
}

.empty-state {
  text-align: center;
  color: var(--text-3);
  padding: 80px 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  font-size: 14px;
}

.empty-add-btn {
  margin-top: 8px;
  background: var(--brand);
  color: var(--text-inverse, #fff);
  border: 1px solid var(--brand);
  padding: 7px 14px;
  border-radius: var(--r-2, 6px);
  font-size: 12px;
  font-weight: var(--fw-semibold, 600);
  cursor: pointer;
  font-family: inherit;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              box-shadow 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.empty-add-btn:hover {
  background: var(--brand-hover);
  box-shadow: var(--sh-brand);
}

.cell-name {
  font-size: 13px;
  font-weight: var(--fw-semibold, 600);
  color: var(--text);
  letter-spacing: -0.005em;
}
.cell-desc {
  font-size: 11px;
  color: var(--text-4);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 240px;
}
.cell-mono {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-2);
}
.cell-database {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-4);
  margin-top: 2px;
}
.cell-faint {
  color: var(--text-4);
  font-size: 12px;
}

/* Per spec 06.1 規範: "6 种 DB 类型用同款灰 chip + 文字区分（mono font）"
   — one tone (brand-soft) for ALL types; no per-type color. */
.db-type-tag {
  display: inline-block;
  font-size: 10.5px;
  font-weight: var(--fw-semibold, 600);
  padding: 2px 8px;
  border-radius: var(--r-1, 4px);
  background: var(--brand-soft);
  color: var(--brand);
  font-family: var(--font-mono);
  letter-spacing: 0.01em;
}

.status-chip {
  display: inline-block;
  font-size: 11px;
  font-weight: var(--fw-semibold, 600);
  padding: 2px 8px;
  border-radius: var(--r-full, 999px);
}
.status-chip.active {
  background: var(--ok-soft);
  color: var(--ok);
}
.status-chip.disconnected {
  background: var(--err-soft);
  color: var(--err);
}
.status-chip.unverified {
  background: var(--warn-soft);
  color: var(--warn);
}
/* Preserved dark override hook (task contract: keep dark-theme block) */
:global(html[data-theme="dark"]) .status-chip.unverified {
  background: var(--warn-soft);
  color: var(--warn);
}

.more-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: var(--r-2, 6px);
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--text-3);
  cursor: pointer;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.more-btn:hover {
  background: var(--brand-soft);
  border-color: var(--brand-ring);
  color: var(--brand);
}

.tables-summary {
  margin-bottom: 12px;
  font-size: 12px;
  color: var(--text-3);
}

.row-2cols {
  display: grid;
  grid-template-columns: 1fr 140px;
  gap: 12px;
}
.col-grow { min-width: 0; }
.col-port { min-width: 0; }

.content-wrap::-webkit-scrollbar {
  width: 6px;
}
.content-wrap::-webkit-scrollbar-track {
  background: transparent;
}
.content-wrap::-webkit-scrollbar-thumb {
  background: var(--line-strong);
  border-radius: 3px;
}
.content-wrap::-webkit-scrollbar-thumb:hover {
  background: var(--text-4);
}

/* ── Phase 6 · table density + filter UX tightening (append-only) ──
   The existing .db-table.el-table block (in the unscoped <style> below)
   already covers stripe / border / hover. This scoped append adds:
   - header thead font-size 11.5 + fw 600 + letter-spacing
   - cell padding tightened to 10/14
   - row link button font-size 12.5 + brand color
   - sticky thead (template uses inline max-height in the tables modal,
     but the main connections table has no height; safe no-op there)
   Scoped :deep is used so this composes with the unscoped block and
   inherits the existing token overrides without conflict. */

.db-table:deep(.el-table thead th.el-table__cell) {
  background: var(--surface-2) !important;
  color: var(--text-2);
  font-size: 11.5px;
  font-weight: var(--fw-semibold, 600);
  letter-spacing: 0.02em;
  padding: 10px 14px;
  border-bottom: 1px solid var(--line);
}
.db-table:deep(.el-table .cell) {
  padding-left: 14px;
  padding-right: 14px;
}
.db-table:deep(.el-table tbody tr:hover > td.el-table__cell) {
  background: var(--surface-2);
}
/* Kill stripe — overrides the inline stripe attribute via specificity.
   Unscoped block currently leaves stripe ON via --el-table-bg-color;
   here we force the striped row back to surface so the zebra goes away. */
.db-table:deep(.el-table--striped .el-table__body tr.el-table__row--striped td.el-table__cell) {
  background: var(--surface) !important;
}

/* Sticky thead — safety net for future max-height additions. */
.db-table:deep(.el-table--scrollable-y .el-table__header-wrapper),
.db-table:deep(.el-table--scrollable-x .el-table__header-wrapper) {
  position: sticky;
  top: 0;
  z-index: 2;
  background: var(--surface-2);
}
</style>

<style>
/* ── el-table + el-dialog Element Plus token overrides ──
   v3 refresh · 2026-05-20: token swap only (--b-* → v3 vars).
   No new :deep selectors added — only existing EP CSS-var overrides retouched
   so they read the v3 palette instead of the v2 indigo-violet residual. */
.db-table.el-table {
  background: var(--surface) !important;
  color: var(--text);
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  --el-table-border-color: var(--line);
  --el-table-header-bg-color: var(--surface-2);
  --el-table-row-hover-bg-color: var(--surface-2);
  --el-table-tr-bg-color: var(--surface);
  --el-table-bg-color: var(--surface);
}
.db-table.el-table tr,
.db-table.el-table th.el-table__cell,
.db-table.el-table td.el-table__cell {
  background: var(--surface) !important;
}
.db-table.el-table--striped .el-table__body tr.el-table__row--striped td.el-table__cell {
  background: var(--surface-2) !important;
}
.db-table.el-table .el-table__cell {
  border-bottom-color: var(--line) !important;
}

/* ── Dialog 主题（复用 env-dialog 体系）── */
.el-dialog.env-dialog {
  background: var(--surface) !important;
  color: var(--text);
  border: 1px solid var(--line);
  border-radius: var(--r-4, 12px);
  box-shadow: var(--sh-5);
}
.el-dialog.env-dialog .el-dialog__header {
  border-bottom: 1px solid var(--line);
  padding: 16px 20px;
}
.el-dialog.env-dialog .el-dialog__title {
  color: var(--text) !important;
  font-size: 15px;
  font-weight: var(--fw-semibold, 600);
  letter-spacing: -0.005em;
}
.el-dialog.env-dialog .el-dialog__headerbtn .el-dialog__close {
  color: var(--text-3);
}
.el-dialog.env-dialog .el-dialog__body {
  padding: 20px;
}
.el-dialog.env-dialog .el-dialog__footer {
  border-top: 1px solid var(--line);
  padding: 14px 20px;
  background: var(--surface-2);
}
.el-dialog.env-dialog .el-form-item__label {
  color: var(--text-2) !important;
  font-size: 12px;
  font-weight: var(--fw-semibold, 600);
}
.el-dialog.env-dialog .el-input__wrapper,
.el-dialog.env-dialog .el-textarea__inner {
  background: var(--surface) !important;
  box-shadow: 0 0 0 1px var(--line) inset !important;
  border-radius: var(--r-2, 6px) !important;
}
.el-dialog.env-dialog .el-input__inner,
.el-dialog.env-dialog .el-textarea__inner {
  color: var(--text) !important;
  -webkit-text-fill-color: var(--text) !important;
  font-size: 14px !important;
}
.el-dialog.env-dialog .el-input__inner::placeholder,
.el-dialog.env-dialog .el-textarea__inner::placeholder {
  color: var(--text-4) !important;
  -webkit-text-fill-color: var(--text-4) !important;
}
.el-dialog.env-dialog .el-input__wrapper:hover,
.el-dialog.env-dialog .el-textarea__inner:hover {
  box-shadow: 0 0 0 1px var(--line-strong) inset !important;
}
.el-dialog.env-dialog .el-input__wrapper.is-focus,
.el-dialog.env-dialog .el-textarea__inner:focus {
  box-shadow: 0 0 0 1px var(--brand) inset, 0 0 0 3px var(--brand-ring) !important;
}
.el-dialog.env-dialog .el-overlay {
  background-color: rgba(11, 27, 63, 0.5) !important;
}
.el-dialog.env-dialog .el-button--primary {
  background: var(--brand) !important;
  border-color: var(--brand) !important;
  color: var(--text-inverse, #fff) !important;
}
.el-dialog.env-dialog .el-button--primary:hover,
.el-dialog.env-dialog .el-button--primary:focus {
  background: var(--brand-hover) !important;
  border-color: var(--brand-hover) !important;
  color: var(--text-inverse, #fff) !important;
}
.el-dialog.env-dialog .el-button--default {
  background: var(--surface) !important;
  border: 1px solid var(--line) !important;
  color: var(--text-2) !important;
}
.el-dialog.env-dialog .el-button--default:hover {
  background: var(--brand-soft) !important;
  color: var(--brand) !important;
  border-color: var(--brand-ring) !important;
}
.el-dialog.env-dialog .el-button {
  font-size: 13px;
  padding: 8px 18px;
  border-radius: var(--r-2, 6px);
  font-weight: var(--fw-medium, 500);
}
.el-dialog.env-dialog .el-input-number .el-input__wrapper {
  background: var(--surface) !important;
  box-shadow: 0 0 0 1px var(--line) inset !important;
}
.el-dialog.env-dialog .el-input-number__decrease,
.el-dialog.env-dialog .el-input-number__increase {
  background: var(--surface-2) !important;
  color: var(--text-3) !important;
  border-color: var(--line) !important;
}
.el-dialog.env-dialog .el-select .el-input__wrapper {
  background: var(--surface) !important;
  box-shadow: 0 0 0 1px var(--line) inset !important;
}
.el-dialog.env-dialog .el-select .el-input__inner {
  color: var(--text) !important;
  -webkit-text-fill-color: var(--text) !important;
}

/* ── el-dropdown 下拉菜单 danger item ── */
.el-dropdown-menu__item.danger-item,
.el-dropdown-menu__item.danger-item:not(.is-disabled):focus,
.el-dropdown-menu__item.danger-item:not(.is-disabled):hover {
  color: var(--err) !important;
}
</style>
