<template>
  <BuilderFrame :breadcrumbs="[{ label: '设置' }, { label: '数据库连接管理' }]">
    <template #actions>
      <button class="new-btn" @click="openCreate">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        新增连接
      </button>
    </template>
    <div class="db-main builder-page">
      <div class="page-header">
        <div class="page-title">数据库连接管理</div>
        <div class="page-summary">{{ connections.length }} 个数据库连接</div>
      </div>

      <div class="content-wrap">
        <div v-if="loading" class="empty-state">加载中...</div>
        <div v-else-if="connections.length === 0" class="empty-state">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="opacity:0.3"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5"/><path d="M3 12a9 3 0 0 0 18 0"/></svg>
          <span>暂无数据库连接</span>
          <button class="empty-add-btn" @click="openCreate">添加第一个连接</button>
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
        :title="editing ? '编辑数据库连接' : '新增数据库连接'"
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
        <div v-if="tablesLoading" class="empty-state" style="padding: 40px 0">加载中...</div>
        <div v-else-if="tablesList.length === 0" class="empty-state" style="padding: 40px 0">
          <span>未发现可读取的表</span>
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
      '删除数据库连接',
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
.db-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
  background: var(--b-bg);
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
  font-weight: 700;
  color: var(--b-text);
}

.page-summary {
  color: var(--b-text-muted);
  font-size: 12px;
  font-family: var(--b-mono);
}

.new-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  height: 30px;
  background: var(--b-ink);
  color: #fff;
  border: 1px solid var(--b-ink);
  padding: 0 12px;
  border-radius: 7px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  transition: opacity 0.2s;
}
.new-btn:hover { opacity: 0.9; }

:global(html[data-theme="dark"]) .new-btn,
:global(html[data-theme="dark"]) .empty-add-btn {
  background: #151922;
  border-color: rgba(124, 140, 255, 0.34);
  color: #c7d2fe;
  box-shadow: none;
}
:global(html[data-theme="dark"]) .new-btn:hover,
:global(html[data-theme="dark"]) .empty-add-btn:hover {
  opacity: 1;
  background: rgba(124, 140, 255, 0.16);
  border-color: rgba(124, 140, 255, 0.46);
  color: #f8fafc;
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
  color: var(--b-text-muted);
  padding: 80px 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  font-size: 14px;
}

.empty-add-btn {
  margin-top: 8px;
  background: var(--b-ink);
  color: #fff;
  border: 1px solid var(--b-ink);
  padding: 7px 14px;
  border-radius: 7px;
  font-size: 12px;
  cursor: pointer;
  transition: opacity 0.2s;
}
.empty-add-btn:hover { opacity: 0.9; }

.cell-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--b-text);
}
.cell-desc {
  font-size: 11px;
  color: var(--b-text-faint);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 240px;
}
.cell-mono {
  font-family: var(--b-mono);
  font-size: 12px;
  color: var(--b-text-muted);
}
.cell-database {
  font-family: var(--b-mono);
  font-size: 11px;
  color: var(--b-text-faint);
  margin-top: 2px;
}
.cell-faint {
  color: var(--b-text-faint);
  font-size: 12px;
}

.db-type-tag {
  display: inline-block;
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--b-brand-soft);
  color: var(--b-brand-ink);
  font-family: var(--b-mono);
}

.status-chip {
  display: inline-block;
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 999px;
}
.status-chip.active {
  background: var(--b-teal-soft);
  color: var(--b-teal);
}
.status-chip.disconnected {
  background: var(--b-bg-sub);
  color: var(--b-text-muted);
}
.status-chip.unverified {
  background: rgba(245, 158, 11, 0.16);
  color: #b45309;
}
:global(html[data-theme="dark"]) .status-chip.unverified {
  background: rgba(245, 158, 11, 0.22);
  color: #fbbf24;
}

.more-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: 1px solid var(--b-line);
  background: var(--b-panel-soft);
  color: var(--b-text-muted);
  cursor: pointer;
  transition: all 0.2s;
}
.more-btn:hover {
  background: var(--b-bg-sub);
  color: var(--b-text);
}

.tables-summary {
  margin-bottom: 12px;
  font-size: 12px;
  color: var(--b-text-muted);
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
  background: var(--b-line-strong);
  border-radius: 3px;
}
.content-wrap::-webkit-scrollbar-thumb:hover {
  background: var(--b-text-faint);
}
</style>

<style>
/* ── el-table 主题（非 scoped 让 element-plus 渲染层生效）── */
.db-table.el-table {
  background: var(--b-panel) !important;
  color: var(--b-text);
  border: 1px solid var(--b-line);
  border-radius: 8px;
  --el-table-border-color: var(--b-line);
  --el-table-header-bg-color: var(--b-bg-sub);
  --el-table-row-hover-bg-color: var(--b-bg-sub);
  --el-table-tr-bg-color: var(--b-panel);
  --el-table-bg-color: var(--b-panel);
}
.db-table.el-table tr,
.db-table.el-table th.el-table__cell,
.db-table.el-table td.el-table__cell {
  background: var(--b-panel) !important;
}
.db-table.el-table--striped .el-table__body tr.el-table__row--striped td.el-table__cell {
  background: var(--b-bg-sub) !important;
}
.db-table.el-table .el-table__cell {
  border-bottom-color: var(--b-line) !important;
}

/* ── Dialog 主题（复用 env-dialog 体系）── */
.el-dialog.env-dialog {
  background: var(--b-panel) !important;
  color: var(--b-text);
  border: 1px solid var(--b-line);
  border-radius: 8px;
}
.el-dialog.env-dialog .el-dialog__header {
  border-bottom: 1px solid var(--b-line);
  padding: 16px 20px;
}
.el-dialog.env-dialog .el-dialog__title {
  color: var(--b-text) !important;
  font-size: 15px;
  font-weight: 700;
}
.el-dialog.env-dialog .el-dialog__headerbtn .el-dialog__close {
  color: var(--b-text-muted);
}
.el-dialog.env-dialog .el-dialog__body {
  padding: 20px;
}
.el-dialog.env-dialog .el-dialog__footer {
  border-top: 1px solid var(--b-line);
  padding: 14px 20px;
}
.el-dialog.env-dialog .el-form-item__label {
  color: var(--b-text-muted) !important;
  font-size: 13px;
}
.el-dialog.env-dialog .el-input__wrapper,
.el-dialog.env-dialog .el-textarea__inner {
  background: var(--b-panel-soft) !important;
  box-shadow: 0 0 0 1px var(--b-line) inset !important;
}
.el-dialog.env-dialog .el-input__inner,
.el-dialog.env-dialog .el-textarea__inner {
  color: var(--b-text) !important;
  -webkit-text-fill-color: var(--b-text) !important;
  font-size: 14px !important;
}
.el-dialog.env-dialog .el-input__inner::placeholder,
.el-dialog.env-dialog .el-textarea__inner::placeholder {
  color: var(--b-text-faint) !important;
  -webkit-text-fill-color: var(--b-text-faint) !important;
}
.el-dialog.env-dialog .el-input__wrapper:hover,
.el-dialog.env-dialog .el-textarea__inner:hover {
  box-shadow: 0 0 0 1px var(--b-line-strong) inset !important;
}
.el-dialog.env-dialog .el-input__wrapper.is-focus,
.el-dialog.env-dialog .el-textarea__inner:focus {
  box-shadow: 0 0 0 1px var(--b-brand) inset !important;
}
.el-dialog.env-dialog .el-overlay {
  background-color: rgba(0, 0, 0, 0.6) !important;
}
.el-dialog.env-dialog .el-button--primary {
  background: var(--b-brand) !important;
  border-color: var(--b-brand) !important;
  color: #ffffff !important;
}
.el-dialog.env-dialog .el-button--primary:hover,
.el-dialog.env-dialog .el-button--primary:focus {
  background: var(--b-brand-ink) !important;
  border-color: var(--b-brand-ink) !important;
  color: #ffffff !important;
}
.el-dialog.env-dialog .el-button--default {
  background: var(--b-panel-soft) !important;
  border: 1px solid var(--b-line) !important;
  color: var(--b-text-muted) !important;
}
.el-dialog.env-dialog .el-button--default:hover {
  background: var(--b-bg-sub) !important;
  color: var(--b-text) !important;
}
.el-dialog.env-dialog .el-button {
  font-size: 14px;
  padding: 8px 18px;
}
.el-dialog.env-dialog .el-input-number .el-input__wrapper {
  background: var(--b-panel-soft) !important;
  box-shadow: 0 0 0 1px var(--b-line) inset !important;
}
.el-dialog.env-dialog .el-input-number__decrease,
.el-dialog.env-dialog .el-input-number__increase {
  background: var(--b-bg-sub) !important;
  color: var(--b-text-muted) !important;
  border-color: var(--b-line) !important;
}
.el-dialog.env-dialog .el-select .el-input__wrapper {
  background: var(--b-panel-soft) !important;
  box-shadow: 0 0 0 1px var(--b-line) inset !important;
}
.el-dialog.env-dialog .el-select .el-input__inner {
  color: var(--b-text) !important;
  -webkit-text-fill-color: var(--b-text) !important;
}

/* ── el-dropdown 下拉菜单 danger item ── */
.el-dropdown-menu__item.danger-item,
.el-dropdown-menu__item.danger-item:not(.is-disabled):focus,
.el-dropdown-menu__item.danger-item:not(.is-disabled):hover {
  color: var(--b-red) !important;
}
</style>
