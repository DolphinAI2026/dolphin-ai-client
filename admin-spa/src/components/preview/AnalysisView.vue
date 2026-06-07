<template>
  <div class="analysis">
    <!-- 统计 -->
    <div class="stats">
      <div class="stat"><div class="label">角色</div><div class="value">{{ roles.length }}</div></div>
      <div class="stat"><div class="label">字典</div><div class="value">{{ dicts.length }}</div></div>
      <div class="stat"><div class="label">数据模型</div><div class="value">{{ models.length }}</div></div>
      <div class="stat"><div class="label">表单</div><div class="value">{{ forms.length }}</div></div>
      <div class="stat"><div class="label">权限规则</div><div class="value">{{ permissionRulesCount }}</div></div>
    </div>

    <!-- 角色 -->
    <el-card class="section" v-if="roles.length">
      <template #header>📋 角色清单 <el-tag size="small">{{ roles.length }}</el-tag></template>
      <el-table :data="roles" stripe size="small">
        <el-table-column prop="code" label="角色编码">
          <template #default="{ row }"><code>{{ row.code || row.roleCode }}</code></template>
        </el-table-column>
        <el-table-column prop="name" label="角色名称">
          <template #default="{ row }">{{ row.name || row.roleName }}</template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 字典 -->
    <el-card class="section" v-if="dicts.length">
      <template #header>📚 数据字典 <el-tag size="small">{{ dicts.length }}</el-tag></template>
      <el-table :data="dicts" stripe size="small">
        <el-table-column label="字典编码" width="200">
          <template #default="{ row }"><code>{{ row.code || row.dictCode }}</code></template>
        </el-table-column>
        <el-table-column label="字典名称" width="160">
          <template #default="{ row }">{{ row.name || row.dictName }}</template>
        </el-table-column>
        <el-table-column label="选项">
          <template #default="{ row }">
            <el-tag v-for="(opt, i) in (row.options || row.items || [])" :key="i" size="small" type="info" style="margin-right: 4px; margin-bottom: 2px">
              {{ (opt.code || opt.value) }} {{ opt.name || opt.label }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 数据模型 -->
    <el-card class="section" v-if="models.length">
      <template #header>🗄 数据模型 <el-tag size="small">{{ models.length }}</el-tag></template>
      <el-table :data="models" stripe size="small">
        <el-table-column label="模型编码" width="200">
          <template #default="{ row }"><code>{{ row.code || row.modelCode }}</code></template>
        </el-table-column>
        <el-table-column label="名称" width="140">
          <template #default="{ row }">{{ row.name || row.modelName }}</template>
        </el-table-column>
        <el-table-column label="字段">
          <template #default="{ row }">
            <el-tag v-for="(f, i) in (row.fields || [])" :key="i" size="small" type="primary" style="margin-right: 4px; margin-bottom: 2px">
              {{ f.code || f.fieldCode }} {{ formatFieldType(f) }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 表单 -->
    <el-card class="section" v-if="forms.length">
      <template #header>📝 表单清单 <el-tag size="small">{{ forms.length }}</el-tag></template>
      <el-table :data="forms" stripe size="small">
        <el-table-column label="表单编码" width="200">
          <template #default="{ row }"><code>{{ row.code || row.formCode }}</code></template>
        </el-table-column>
        <el-table-column label="表单名称" width="160">
          <template #default="{ row }">{{ row.name || row.formName }}</template>
        </el-table-column>
        <el-table-column label="绑定主表" width="180">
          <template #default="{ row }"><code v-if="getMainModel(row)">{{ getMainModel(row) }}</code></template>
        </el-table-column>
        <el-table-column label="字段数" width="80">
          <template #default="{ row }">{{ (row.fields || row.components || []).length }}</template>
        </el-table-column>
        <el-table-column label="子表" width="200">
          <template #default="{ row }">
            <span v-if="(row.subForms || []).length">{{ (row.subForms || []).map((s: any) => s.name || s.subFormName).join('、') }}</span>
            <span v-else style="color: #c0c4cc">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="说明" />
      </el-table>
    </el-card>

    <!-- 权限矩阵 -->
    <el-card class="section" v-if="permissionMatrix.length">
      <template #header>🔒 权限矩阵 <el-tag size="small">{{ permissionRulesCount }} 条规则</el-tag></template>
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

const permissionRulesCount = computed(() =>
  permissions.value.reduce((s: number, p: any) => s + ((p.rules || p.permissionRules || []).length), 0),
)

function getMainModel(form: any): string {
  return form.mainModel || form.modelCode || form.bindModel || ''
}

function formatFieldType(f: any): string {
  const t = f.dbType || f.type || ''
  const len = f.length || f.precision
  return len ? `${t}(${len})` : t
}

// 权限矩阵：行=表单 列=角色
const permissionMatrix = computed(() => {
  const rolesSet = new Set<string>()
  const byForm: Record<string, any> = {}
  for (const p of permissions.value) {
    const formCode = p.formCode || p.form_code || p.form
    const formName = forms.value.find((f: any) =>
      (f.code || f.formCode) === formCode || (f.name || f.formName) === formCode,
    )?.name || (forms.value.find((f: any) => (f.code || f.formCode) === formCode)?.formName) || formCode
    if (!byForm[formName]) byForm[formName] = { form: formName }
    for (const r of (p.rules || p.permissionRules || [])) {
      const roleCode = r.role || r.roleCode || 'all'
      const roleName = roles.value.find((x: any) => (x.code || x.roleCode) === roleCode)?.name
        || roles.value.find((x: any) => (x.code || x.roleCode) === roleCode)?.roleName
        || (roleCode === 'all' ? '全员' : roleCode)
      rolesSet.add(roleName)
      byForm[formName][roleName] = {
        ops: formatOps(r),
        scope: r.data || r.scope || r.dataRange || '全部数据',
      }
    }
  }
  return Object.values(byForm)
})

const matrixRoles = computed(() => {
  const set = new Set<string>()
  for (const row of permissionMatrix.value) {
    Object.keys(row).forEach(k => { if (k !== 'form') set.add(k) })
  }
  return Array.from(set)
})

function formatOps(rule: any): string {
  // 按"可X"字段聚合简短描述
  const labels: string[] = []
  const map: Record<string, string> = {
    canView: '看', canCreate: '增', canAdd: '增',
    canEdit: '改', canDelete: '删',
    canStage: '暂', canImport: '导入', canExport: '导出',
  }
  let all = 0, has = 0
  for (const k in map) {
    if (k in rule) { all++; if (rule[k]) { has++; labels.push(map[k]) } }
  }
  if (all && has === all) return '全权限'
  if (labels.length) return labels.join('+')
  if (Array.isArray(rule.op)) return rule.op.join('+')
  if (rule.op === 'all') return '全权限'
  return rule.op || ''
}
</script>

<style scoped>
.analysis {
  padding: 20px 40px;
}
.stats {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 16px;
  margin-bottom: 20px;
}
.stat {
  background: #fff;
  padding: 18px 20px;
  border-radius: 6px;
  box-shadow: 0 1px 2px rgba(0,0,0,.04);
}
.stat .label { color: #909399; font-size: 12px; }
.stat .value { font-size: 28px; font-weight: 600; margin-top: 4px; }
.section {
  margin-bottom: 16px;
}
.section :deep(.el-card__header) {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}
code {
  font-family: SFMono-Regular, Consolas, monospace;
  font-size: 12px;
  background: #f4f4f5;
  padding: 1px 6px;
  border-radius: 3px;
  color: #5e6d82;
}
.perm-cell .ops { color: #67c23a; font-weight: 500; font-size: 12px; }
.perm-cell .scope { color: #909399; font-size: 11px; }
.empty { color: #c0c4cc; }
</style>
