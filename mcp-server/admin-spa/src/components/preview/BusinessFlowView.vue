<template>
  <div class="business-flow">
    <div class="stats">
      <div class="stat"><div class="label">角色</div><div class="value">{{ roles.length }}</div></div>
      <div class="stat"><div class="label">字典</div><div class="value">{{ dicts.length }}</div></div>
      <div class="stat"><div class="label">数据模型</div><div class="value">{{ models.length }}</div></div>
      <div class="stat"><div class="label">表单</div><div class="value">{{ forms.length }}</div></div>
      <div class="stat"><div class="label">流程</div><div class="value">{{ workflows.length }}</div></div>
    </div>

    <el-card class="section">
      <template #header>
        <span>主体业务关系</span>
        <el-tag size="small" type="info">平台人员/部门引用</el-tag>
      </template>
      <div class="relation-canvas">
        <div class="relation-group">
          <div class="relation-title">平台参与方</div>
          <div v-for="item in relationMap.participants" :key="item.key" class="relation-node participant">
            <div class="title">{{ item.name }}</div>
            <div class="desc">{{ item.desc }}</div>
          </div>
        </div>
        <div class="relation-group objects">
          <div class="relation-title">核心业务对象</div>
          <div v-for="item in relationMap.objects" :key="item.key" class="relation-node">
            <div class="title">{{ item.name }}</div>
            <code v-if="item.code">{{ item.code }}</code>
          </div>
        </div>
      </div>
      <div class="relation-list">
        <div v-for="rel in relationMap.relations" :key="`${rel.from}-${rel.to}-${rel.label}`" class="relation-line">
          <span>{{ rel.from }}</span>
          <b>{{ rel.label }}</b>
          <span>{{ rel.to }}</span>
        </div>
      </div>
    </el-card>

    <div class="grid">
      <el-card class="section" v-if="forms.length">
        <template #header>表单入口 <el-tag size="small">{{ forms.length }}</el-tag></template>
        <el-table :data="forms" stripe size="small">
          <el-table-column label="表单" min-width="170">
            <template #default="{ row }">
              <div class="strong">{{ row.name || row.formName }}</div>
              <code>{{ row.code || row.formCode }}</code>
            </template>
          </el-table-column>
          <el-table-column label="绑定主表" width="160">
            <template #default="{ row }"><code v-if="mainModel(row)">{{ mainModel(row) }}</code><span v-else class="muted">—</span></template>
          </el-table-column>
          <el-table-column label="能力" min-width="260">
            <template #default="{ row }">
              <el-tag
                v-for="cap in capabilitiesForForm(row)"
                :key="cap.key"
                size="small"
                :type="cap.key === 'import' && cap.on ? 'warning' : cap.on ? 'success' : 'info'"
                effect="plain"
                class="cap"
              >
                {{ cap.label }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-card class="section" v-if="models.length">
        <template #header>业务对象 <el-tag size="small">{{ models.length }}</el-tag></template>
        <div class="object-list">
          <div v-for="model in models" :key="model.code || model.modelCode" class="object-row">
            <div>
              <div class="strong">{{ model.name || model.modelName }}</div>
              <code>{{ model.code || model.modelCode }}</code>
            </div>
            <div class="muted">{{ (model.fields || []).length }} 字段</div>
          </div>
        </div>
      </el-card>
    </div>

    <el-card class="section" v-if="permissionMatrix.length">
      <template #header>权限矩阵 <el-tag size="small">{{ permissionRulesCount }} 条规则</el-tag></template>
      <el-table :data="permissionMatrix" stripe size="small" border>
        <el-table-column prop="form" label="表单" width="180" fixed />
        <el-table-column v-for="role in matrixRoles" :key="role" :prop="role" :label="role" align="center">
          <template #default="{ row }">
            <div v-if="row[role]" class="perm-cell">
              <div class="ops">{{ row[role].ops }}</div>
              <div class="scope">{{ row[role].scope }}</div>
            </div>
            <span v-else class="empty">—</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ spec: any }>()

const roles = computed(() => props.spec?.roles || [])
const dicts = computed(() => props.spec?.dicts || [])
const models = computed(() => props.spec?.models || props.spec?.dataModels || [])
const forms = computed(() => props.spec?.forms || [])
const permissions = computed(() => props.spec?.permissions || [])
const workflows = computed(() => props.spec?.workflows || props.spec?.flows || props.spec?.processes || [])

const permissionRulesCount = computed(() =>
  permissions.value.reduce((sum: number, item: any) => sum + ((item.rules || item.permissionRules || []).length), 0),
)

type RelationNode = { key: string; name: string; code?: string; desc?: string }
type Relation = { from: string; to: string; label: string }

const relationMap = computed(() => {
  const objects = businessObjects()
  const primary = primaryObject(objects)
  const participants: RelationNode[] = [
    { key: 'all_people', name: '全体人员', desc: '平台用户' },
    { key: 'department', name: '所属部门', desc: '平台部门' },
  ]
  const relations: Relation[] = []
  if (primary) {
    relations.push({ from: '全体人员', label: '提交/维护', to: primary.name })
    relations.push({ from: '所属部门', label: '归属', to: primary.name })
    for (const item of objects) {
      if (item.key === primary.key) continue
      relations.push({ from: primary.name, label: relationLabel(item.name), to: item.name })
    }
  }
  return { participants, objects: objects.length ? objects : [{ key: 'empty', name: '业务对象待补充', desc: '' }], relations }
})

function businessObjects(): RelationNode[] {
  const seen = new Set<string>()
  const source = forms.value.length ? forms.value : models.value
  return (source || [])
    .map((item: any) => ({
      key: String(item.code || item.formCode || item.modelCode || item.name || item.formName || item.modelName || ''),
      name: String(item.name || item.formName || item.modelName || item.code || item.formCode || item.modelCode || '').replace(/表单$/, ''),
      code: item.code || item.formCode || item.modelCode || '',
    }))
    .filter((item: RelationNode) => {
      if (!item.key || !item.name || seen.has(item.name)) return false
      seen.add(item.name)
      return true
    })
    .slice(0, 6)
}

function primaryObject(objects: RelationNode[]): RelationNode | null {
  return objects.find(item => /预约|申请|订单|工单|任务|计划|单据|记录/.test(item.name)) || objects[0] || null
}

function relationLabel(name: string): string {
  if (/会议室|房间|场地/.test(name)) return '预订'
  if (/通知|消息/.test(name)) return '生成'
  if (/参会|参与|成员/.test(name)) return '邀请'
  if (/明细|详情|清单/.test(name)) return '包含'
  if (/审批|审核/.test(name)) return '触发'
  return '关联'
}

function mainModel(form: any): string {
  return form.mainModel || form.modelCode || form.bindModel || ''
}

function rulesForForm(form: any): any[] {
  const code = form.code || form.formCode
  const name = form.name || form.formName
  const rules: any[] = []
  for (const item of permissions.value) {
    const key = item.formCode || item.form_code || item.form
    if (key === code || key === name) rules.push(...(item.rules || item.permissionRules || []))
  }
  return rules
}

function hasOp(rules: any[], ops: string[]): boolean {
  return rules.some(rule => {
    if (rule.op === 'all') return true
    const arr = Array.isArray(rule.op) ? rule.op : String(rule.op || '').split(/[,+]/).map(x => x.trim())
    return ops.some(op => arr.includes(op))
  })
}

function capabilitiesForForm(form: any) {
  const rules = rulesForForm(form)
  return [
    { key: 'view', label: '查看', on: hasOp(rules, ['view']) || rules.some(r => r.canView) },
    { key: 'add', label: '新增', on: hasOp(rules, ['add', 'create']) || rules.some(r => r.canAdd || r.canCreate) },
    { key: 'edit', label: '编辑', on: hasOp(rules, ['edit']) || rules.some(r => r.canEdit) },
    { key: 'delete', label: '删除', on: hasOp(rules, ['delete']) || rules.some(r => r.canDelete) },
    { key: 'import', label: '可导入', on: rules.some(r => r.canImport) },
    { key: 'export', label: '可导出', on: hasOp(rules, ['export']) || rules.some(r => r.canExport) },
  ]
}

const permissionMatrix = computed(() => {
  const byForm: Record<string, any> = {}
  for (const item of permissions.value) {
    const formCode = item.formCode || item.form_code || item.form
    const form = forms.value.find((f: any) => (f.code || f.formCode) === formCode || (f.name || f.formName) === formCode)
    const formName = form?.name || form?.formName || formCode
    if (!byForm[formName]) byForm[formName] = { form: formName }
    for (const rule of (item.rules || item.permissionRules || [])) {
      const roleCode = rule.role || rule.roleCode || 'all'
      const role = roles.value.find((x: any) => (x.code || x.roleCode) === roleCode)
      const roleName = role?.name || role?.roleName || (roleCode === 'all' ? '全员' : roleCode)
      byForm[formName][roleName] = {
        ops: formatOps(rule),
        scope: formatScope(rule.data || rule.scope || 'ALL'),
      }
    }
  }
  return Object.values(byForm)
})

const matrixRoles = computed(() => {
  const set = new Set<string>()
  for (const row of permissionMatrix.value) Object.keys(row).forEach(k => { if (k !== 'form') set.add(k) })
  return Array.from(set)
})

function formatOps(rule: any): string {
  const labels: string[] = []
  const opMap: Record<string, string> = { view: '查看', add: '新增', create: '新增', edit: '编辑', delete: '删除' }
  const flagMap: Record<string, string> = { canDraft: '暂存', canImport: '导入', canExport: '导出' }
  const ops = rule.op === 'all' ? Object.keys(opMap) : Array.isArray(rule.op) ? rule.op : String(rule.op || '').split(/[,+]/).map(x => x.trim())
  for (const op of ops) if (opMap[op] && !labels.includes(opMap[op])) labels.push(opMap[op])
  for (const key in flagMap) if (rule[key] && !labels.includes(flagMap[key])) labels.push(flagMap[key])
  return labels.length >= 7 ? '全权限' : labels.join('·') || '—'
}

function formatScope(scope: string): string {
  const map: Record<string, string> = {
    ALL: '全部数据',
    SELF: '本人数据',
    CURRENT_USER_DEPT: '本部门数据',
    CURRENT_USER_DEPT_LOW_LEVEL: '本部门及下级',
  }
  return map[scope] || scope
}
</script>

<style scoped>
.business-flow { padding: 20px 40px; }
.stats { display: grid; grid-template-columns: repeat(5, 1fr); gap: 16px; margin-bottom: 20px; }
.stat { background: #fff; padding: 18px 20px; border-radius: 6px; box-shadow: 0 1px 2px rgba(0,0,0,.04); }
.stat .label { color: #909399; font-size: 12px; }
.stat .value { font-size: 28px; font-weight: 600; margin-top: 4px; }
.section { margin-bottom: 16px; }
.section :deep(.el-card__header) { display: flex; align-items: center; gap: 8px; font-weight: 600; }
.relation-canvas { display: grid; grid-template-columns: .8fr 1.2fr; gap: 16px; margin-bottom: 14px; }
.relation-group { border: 1px solid #ebeef5; border-radius: 6px; padding: 14px; background: #fafafa; display: grid; gap: 10px; align-content: start; }
.relation-title { color: #909399; font-size: 12px; font-weight: 600; }
.relation-node { border: 1px solid #dcdfe6; border-radius: 6px; padding: 12px; background: #fff; min-height: 62px; }
.relation-node.participant { border-color: #d9ecff; background: #f5faff; }
.relation-list { display: flex; flex-wrap: wrap; gap: 8px; }
.relation-line { display: inline-flex; align-items: center; gap: 8px; padding: 7px 10px; border: 1px solid #ebeef5; border-radius: 6px; background: #fff; color: #606266; font-size: 12px; }
.relation-line b { color: #409eff; font-weight: 600; }
.title, .strong { font-weight: 600; }
.desc, .muted { color: #909399; font-size: 12px; line-height: 1.5; }
.grid { display: grid; grid-template-columns: 1.2fr .8fr; gap: 16px; align-items: start; }
.object-list { display: grid; gap: 10px; }
.object-row { display: flex; justify-content: space-between; gap: 16px; padding: 12px; border: 1px solid #ebeef5; border-radius: 6px; background: #fafafa; }
.cap { margin-right: 4px; margin-bottom: 4px; }
code { font-family: SFMono-Regular, Consolas, monospace; font-size: 12px; background: #f4f4f5; padding: 1px 6px; border-radius: 3px; color: #5e6d82; }
.perm-cell .ops { color: #67c23a; font-weight: 500; font-size: 12px; }
.perm-cell .scope { color: #909399; font-size: 11px; }
.empty { color: #c0c4cc; }
@media (max-width: 900px) {
  .business-flow { padding: 16px; }
  .stats, .relation-canvas, .grid { grid-template-columns: 1fr; }
}
</style>
