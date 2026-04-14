<template>
  <div class="structured-doc">
    <section class="doc-section app-hero">
      <h1 class="doc-app-name">{{ appInfo.name || '未命名应用' }}</h1>
    </section>

    <section class="doc-section">
      <h2 class="doc-section-title">一、应用信息</h2>
      <div class="doc-table-wrap">
        <table class="doc-table">
          <thead>
            <tr>
              <th>应用名称</th>
              <th>应用编码</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>{{ appInfo.name || '-' }}</td>
              <td>{{ appInfo.code || '-' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="appInfo.description" class="doc-app-desc">{{ appInfo.description }}</p>
    </section>

    <section class="doc-section">
      <h2 class="doc-section-title">二、角色列表</h2>
      <div class="doc-table-wrap">
        <table class="doc-table">
          <thead>
            <tr>
              <th>角色编码</th>
              <th>角色名称</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!roles.length">
              <td colspan="2" class="empty-cell">暂无角色数据</td>
            </tr>
            <tr v-for="role in roles" :key="role.role_code || role.role_name">
              <td>{{ role.role_code || '-' }}</td>
              <td>{{ role.role_name || '-' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="doc-section">
      <h2 class="doc-section-title">三、数据字典</h2>
      <div v-if="!dicts.length" class="doc-empty-block">暂无数据字典</div>
      <div v-for="dict in dicts" :key="dict.dict_code || dict.dict_name" class="doc-subsection">
        <h3 class="doc-subsection-title">{{ dict.dict_name || '未命名字典' }}（{{ dict.dict_code || '-' }}）</h3>
        <div class="doc-table-wrap">
          <table class="doc-table">
            <thead>
              <tr>
                <th>选项编码</th>
                <th>选项名称</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!(dict.items || []).length">
                <td colspan="2" class="empty-cell">暂无选项</td>
              </tr>
              <tr v-for="item in (dict.items || [])" :key="item.item_code || item.item_name">
                <td>{{ item.item_code || '-' }}</td>
                <td>{{ item.item_name || '-' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>

    <section class="doc-section">
      <h2 class="doc-section-title">四、数据模型</h2>
      <div v-if="!tables.length" class="doc-empty-block">暂无数据模型</div>
      <div v-for="table in tables" :key="table.table_code || table.table_name" class="doc-subsection">
        <h3 class="doc-subsection-title">
          {{ table.table_name || '未命名模型' }}（{{ table.table_code || '-' }}）
        </h3>
        <div class="doc-table-wrap">
          <table class="doc-table">
            <thead>
              <tr>
                <th>字段编码</th>
                <th>字段名称</th>
                <th>存储类型</th>
                <th>长度</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!(table.fields || []).length">
                <td colspan="4" class="empty-cell">暂无字段</td>
              </tr>
              <tr v-for="field in (table.fields || [])" :key="field.field_code || field.field_name">
                <td>{{ field.field_code || '-' }}</td>
                <td>{{ field.field_name || '-' }}</td>
                <td>{{ field.database_field_type || field.data_type || field.type || '-' }}</td>
                <td>{{ field.max_length || field.length || '-' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>

    <section class="doc-section">
      <h2 class="doc-section-title">五、表单定义</h2>
      <div v-if="!forms.length" class="doc-empty-block">暂无表单定义</div>
      <div v-for="form in forms" :key="form.form_name" class="doc-subsection">
        <h3 class="doc-subsection-title">{{ form.form_name || '未命名表单' }}</h3>
        <div class="doc-sub-meta">
          主表模型：{{ form.main_model_code || '-' }}
        </div>
        <div class="doc-form-group">
          <div class="doc-form-group-title">主表字段</div>
          <div class="doc-table-wrap">
            <table class="doc-table">
              <thead>
                <tr>
                  <th>字段编码</th>
                  <th>字段名称</th>
                  <th>组件类型</th>
                  <th>必填</th>
                  <th>隐藏</th>
                  <th>只读</th>
                  <th>列表展示</th>
                  <th>查询条件</th>
                  <th>字典编码</th>
                  <th>目标模型编码</th>
                  <th>目标字段编码</th>
                  <th>本表关联字段编码</th>
                  <th>说明</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="!(form.main_components || []).length">
                  <td colspan="13" class="empty-cell">暂无主表字段</td>
                </tr>
                <tr v-for="component in (form.main_components || [])" :key="`${form.form_name}-main-${component.field_code}-${component.component_type}`">
                  <td>{{ component.field_code || '-' }}</td>
                  <td>{{ component.field_name || '-' }}</td>
                  <td>{{ displayComponentType(component) }}</td>
                  <td>{{ formatBool(component.required) }}</td>
                  <td>{{ formatBool(component.hidden) }}</td>
                  <td>{{ formatBool(component.readonly) }}</td>
                  <td>{{ formatBool(component.show_in_list) }}</td>
                  <td>{{ formatBool(component.searchable) }}</td>
                  <td>{{ component.dict_code || '-' }}</td>
                  <td>{{ component.ref_model_code || component.selector_form_code || component.association_form_code || '-' }}</td>
                  <td>{{ component.ref_display_field_code || component.selector_field_code || component.association_target_field_code || '-' }}</td>
                  <td>{{ component.association_origin_field_code || '-' }}</td>
                  <td>{{ component.description || '-' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div v-for="subGroup in (form.sub_groups || [])" :key="`${form.form_name}-${subGroup.model_code}-${subGroup.group_name}`" class="doc-form-group">
          <div class="doc-form-group-title">
            子表：{{ subGroup.group_name || subGroup.model_name || subGroup.model_code || '-' }}
            <span class="doc-form-group-code">（{{ subGroup.model_code || '-' }}）</span>
          </div>
          <table class="doc-table">
            <thead>
              <tr>
                <th>字段编码</th>
                <th>字段名称</th>
                <th>组件类型</th>
                <th>必填</th>
                <th>隐藏</th>
                <th>只读</th>
                <th>列表展示</th>
                <th>查询条件</th>
                <th>字典编码</th>
                <th>目标模型编码</th>
                <th>目标字段编码</th>
                <th>本表关联字段编码</th>
                <th>说明</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!(subGroup.components || []).length">
                <td colspan="13" class="empty-cell">暂无子表字段</td>
              </tr>
              <tr v-for="component in (subGroup.components || [])" :key="`${form.form_name}-${subGroup.model_code}-${component.field_code}-${component.component_type}`">
                <td>{{ component.field_code || '-' }}</td>
                <td>{{ component.field_name || '-' }}</td>
                <td>{{ displayComponentType(component) }}</td>
                <td>{{ formatBool(component.required) }}</td>
                <td>{{ formatBool(component.hidden) }}</td>
                <td>{{ formatBool(component.readonly) }}</td>
                <td>{{ formatBool(component.show_in_list) }}</td>
                <td>{{ formatBool(component.searchable) }}</td>
                <td>{{ component.dict_code || '-' }}</td>
                <td>{{ component.ref_model_code || component.selector_form_code || component.association_form_code || '-' }}</td>
                <td>{{ component.ref_display_field_code || component.selector_field_code || component.association_target_field_code || '-' }}</td>
                <td>{{ component.association_origin_field_code || '-' }}</td>
                <td>{{ component.description || '-' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="!(form.sub_groups || []).length" class="doc-empty-block">暂无子表结构</div>
      </div>
    </section>

    <section class="doc-section">
      <h2 class="doc-section-title">六、权限定义</h2>
      <div v-if="!roleTableMapping.length" class="doc-empty-block">暂无权限定义</div>
      <div v-for="mapping in roleTableMapping" :key="mapping.table_code || mapping.table_name" class="doc-subsection">
        <h3 class="doc-subsection-title">{{ mapping.table_name || mapping.table_code || '未命名对象' }}</h3>
        <div class="doc-table-wrap">
          <table class="doc-table">
            <thead>
              <tr>
                <th>角色编码</th>
                <th>可暂存</th>
                <th>可新增</th>
                <th>可导入</th>
                <th>可查看</th>
                <th>可编辑</th>
                <th>可删除</th>
                <th>可导出</th>
                <th>数据范围</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!(mapping.permissions || []).length">
                <td colspan="9" class="empty-cell">暂无权限项</td>
              </tr>
              <tr v-for="perm in (mapping.permissions || [])" :key="`${mapping.table_code || mapping.table_name}-${perm.role_code || perm.role_name}`">
                <td>{{ perm.role_code || '-' }}</td>
                <td>{{ formatPermissionFlag(perm, ['stash', 'save', 'draft'], 'can_draft') }}</td>
                <td>{{ formatPermissionFlag(perm.operations, ['add']) }}</td>
                <td>{{ formatPermissionFlag(perm, ['import'], 'can_import') }}</td>
                <td>{{ formatPermissionFlag(perm.operations, ['view']) }}</td>
                <td>{{ formatPermissionFlag(perm.operations, ['edit']) }}</td>
                <td>{{ formatPermissionFlag(perm.operations, ['delete']) }}</td>
                <td>{{ formatPermissionFlag(perm, ['export'], 'can_export') }}</td>
                <td>{{ formatDataScope(perm.data_scope) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  docResult: any
}>()

const appInfo = computed(() => {
  const doc = props.docResult || {}
  const legacy = doc.app_info || {}
  return {
    name: legacy.app_name || legacy.name || doc.appName || doc.app_name || doc.name || '-',
    code: legacy.app_code || legacy.code || doc.appCode || doc.app_code || doc.code || '-',
    description: legacy.description || doc.description || '',
  }
})

const roles = computed(() => (props.docResult?.roles || []).map((role: any) => ({
  role_code: role.role_code || role.code || '',
  role_name: role.role_name || role.name || '',
})))

const dicts = computed(() => {
  const source = props.docResult?.data_dictionary || props.docResult?.dicts || []
  return source.map((dict: any) => ({
    dict_code: dict.dict_code || dict.code || '',
    dict_name: dict.dict_name || dict.name || '',
    items: (dict.items || dict.options || []).map((item: any) => ({
      item_code: item.item_code || item.code || '',
      item_name: item.item_name || item.name || '',
    })),
  }))
})

const tables = computed(() => {
  const source = props.docResult?.tables || props.docResult?.models || []
  const normalizeField = (field: any) => ({
    field_code: field.field_code || field.code || '',
    field_name: field.field_name || field.name || '',
    database_field_type: field.database_field_type || field.databaseFieldType || field.db_type || 'varchar',
    max_length: field.max_length || field.maxLength || field.length || '',
    length: field.length || field.max_length || field.maxLength || '',
    type: field.type || field.field_type || '',
    required: !!field.required,
    hidden: !!field.hidden,
    readonly: !!(field.readonly ?? field.readOnly),
  })

  const normalizedTables: any[] = []
  const seenTableCodes = new Set<string>()

  for (const table of source) {
    const tableCode = table.table_code || table.code || ''
    const tableName = table.table_name || table.name || ''
    const tableType = table.table_type || table.tableType || ''
    const rawFields = Array.isArray(table.fields) ? table.fields : []

    const regularFields = rawFields.filter((field: any) => String(field?.type || field?.field_type || '') !== '子表')
    const subTableFields = rawFields.filter((field: any) => String(field?.type || field?.field_type || '') === '子表')

    if (!seenTableCodes.has(tableCode || tableName)) {
      normalizedTables.push({
        table_code: tableCode,
        table_name: tableName,
        table_type: tableType,
        parent_model_code: table.parent_model_code || table.parentModelCode || '',
        fields: regularFields.map(normalizeField),
      })
      seenTableCodes.add(tableCode || tableName)
    }

    for (const subField of subTableFields) {
      const subCode = subField.sub_code || subField.subCode || subField.field_code || subField.code || ''
      const subName = subField.name || subField.field_name || subField.fieldName || subCode
      const dedupeKey = subCode || `${tableCode}::${subName}`
      if (seenTableCodes.has(dedupeKey)) continue
      normalizedTables.push({
        table_code: subCode,
        table_name: subName,
        table_type: '子表',
        parent_model_code: tableCode,
        fields: (subField.sub_fields || subField.subFields || []).map(normalizeField),
      })
      seenTableCodes.add(dedupeKey)
    }
  }

  return normalizedTables
})

const modelNameMap = computed(() => {
  const map = new Map<string, string>()
  for (const table of tables.value) {
    if (table.table_code) map.set(table.table_code, table.table_name || table.table_code)
  }
  return map
})

const modelFieldTypeMap = computed(() => {
  const map = new Map<string, string>()
  for (const table of tables.value) {
    const modelCode = table.table_code || ''
    for (const field of table.fields || []) {
      const fieldCode = field.field_code || ''
      const fieldName = field.field_name || ''
      const modelType = field.type || field.field_type || field.component_type || ''
      if (modelCode && fieldCode && modelType) map.set(`${modelCode}::${fieldCode}`, modelType)
      if (modelCode && fieldName && modelType) map.set(`${modelCode}::${fieldName}`, modelType)
    }
  }
  return map
})

const forms = computed(() => {
  const source = props.docResult?.forms || []
  return source
    .map((form: any) => {
      const mainModelCode = form.main_model_code || form.model_code || form.modelCode || form.bindModelCode || ''
      const components = (form.components || form.formComponents || []).map((component: any) => {
        const modelField = String(component.model_field || component.modelField || '')
        const [modelFieldModelCode, modelFieldCode] = modelField.includes('.') ? modelField.split('.', 2) : ['', '']
        const sectionType = component.section_type || (component.componentType === 'FORM_WIDGET_SON_TABLE' ? 'sub' : 'main')
        const modelCode =
          component.model_code
          || component.modelCode
          || component.table_model_code
          || component.tableModelCode
          || modelFieldModelCode
          || (sectionType === 'sub' ? '' : mainModelCode)
        const fieldCode = component.field_code || component.fieldCode || component.code || modelFieldCode || ''
        const fieldName = component.field_name || component.fieldName || component.label || fieldCode || ''
        const modelType =
          modelFieldTypeMap.value.get(`${modelCode}::${fieldCode}`)
          || modelFieldTypeMap.value.get(`${modelCode}::${fieldName}`)
          || ''
        const ref = component.ref || {}
        const associationConfig = component.formAssociationConfig || component.form_association_config || {}
        return {
          field_code: fieldCode,
          field_name: fieldName,
          component_type: component.component_type || component.componentType || component.type || '',
          raw_component_type: component.raw_component_type || component.componentType || component.type || '',
          model_type: modelType,
          section_type: sectionType,
          model_code: modelCode,
          sub_group_name: component.sub_group_name || component.subGroupName || '',
          required: !!component.required,
          hidden: !!component.hidden,
          readonly: !!(component.readonly ?? component.readOnly),
          show_in_list: !!(component.show_in_list ?? component.showInList),
          searchable: !!component.searchable,
          dict_code: component.dict_code || component.dictCode || '',
          selector_form_code:
            component.selector_form_code
            || component.selectorFormCode
            || component.ref_model_code
            || component.refModelCode
            || ref.model
            || '',
          selector_form_name: component.selector_form_name || component.selectorFormName || '',
          selector_field_code:
            component.selector_field_code
            || component.selectorFieldCode
            || component.ref_display_field_code
            || component.refDisplayFieldCode
            || ref.display_field
            || ref.target_field
            || ref.field
            || '',
          selector_field_name: component.selector_field_name || component.selectorFieldName || '',
          association_form_code:
            component.association_form_code
            || component.associationFormCode
            || associationConfig.targetModelCode
            || '',
          association_form_name: component.association_form_name || component.associationFormName || '',
          association_origin_field_code:
            component.association_origin_field_code
            || component.associationOriginFieldCode
            || associationConfig.originFieldCode
            || '',
          association_origin_field_name: component.association_origin_field_name || component.associationOriginFieldName || '',
          association_target_field_code:
            component.association_target_field_code
            || component.associationTargetFieldCode
            || associationConfig.targetFieldCode
            || '',
          association_target_field_name: component.association_target_field_name || component.associationTargetFieldName || '',
          ref_model_code:
            component.ref_model_code
            || component.refModelCode
            || ref.model
            || '',
          ref_display_field_code:
            component.ref_display_field_code
            || component.refDisplayFieldCode
            || ref.display_field
            || ref.target_field
            || ref.field
            || '',
          description: component.description || component.comment || '',
        }
      })
      const subModelCodes: string[] = Array.from(new Set<string>(
        components
          .filter((component: any) => component.section_type === 'sub' && component.model_code)
          .map((component: any) => component.model_code)
      ))
      const mainComponents = components.filter((component: any) => component.section_type !== 'sub')
      const subGroups = Array.from(new Set<string>(
        components
          .filter((component: any) => component.section_type === 'sub')
          .map((component: any) => `${component.model_code || ''}::${component.sub_group_name || ''}`)
      ))
        .filter(Boolean)
        .map((groupKey: string) => {
          const [modelCode = '', groupName = ''] = groupKey.split('::')
          return {
            model_code: modelCode,
            model_name: modelNameMap.value.get(modelCode) || modelCode,
            group_name: groupName || '',
            components: components.filter((component: any) =>
              component.section_type === 'sub'
              && component.model_code === modelCode
              && (component.sub_group_name || '') === (groupName || '')
            ),
          }
        })
      return {
        form_name: form.form_name || form.formName || form.name || '',
        main_model_code: mainModelCode || '-',
        sub_model_codes: subModelCodes,
        main_components: mainComponents,
        sub_groups: subGroups,
        components,
      }
    })
    .filter((form: any) => form.form_name)
})

const roleTableMapping = computed(() => {
  const formNameMap = new Map<string, string>()
  ;(props.docResult?.forms || []).forEach((form: any) => {
    const formName = form.form_name || form.formName || form.name || ''
    const formCode = form.form_code || form.formCode || form.code || ''
    const modelCode = form.model_code || form.modelCode || form.bindModelCode || ''
    if (formCode && formName) formNameMap.set(String(formCode), formName)
    if (modelCode && formName) formNameMap.set(String(modelCode), formName)
  })
  const legacy = props.docResult?.role_table_mapping || []
  if (legacy.length) {
    return legacy.map((mapping: any) => ({
      table_code: mapping.table_code || '',
      table_name: mapping.table_name || formNameMap.get(String(mapping.table_code || '')) || '',
      permissions: (mapping.permissions || []).map((perm: any) => ({
        role_code: perm.role_code || perm.role || '',
        role_name: perm.role_name || perm.role || '',
        operations: Array.isArray(perm.operations)
          ? perm.operations
          : String(perm.op || '')
              .split(',')
              .map((item: string) => item.trim())
              .filter(Boolean),
        data_scope: perm.data_scope || perm.data || '',
        can_draft: !!(perm.can_draft ?? perm.canDraft),
        can_import: !!(perm.can_import ?? perm.canImport),
        can_export: !!(perm.can_export ?? perm.canExport),
      })),
    }))
  }
  const permissions = props.docResult?.permissions || []
  return permissions.map((mapping: any) => ({
    table_code: mapping.form || mapping.form_code || '',
    table_name: formNameMap.get(String(mapping.form || mapping.form_code || '')) || mapping.form_name || mapping.form || '',
      permissions: (mapping.rules || []).map((rule: any) => ({
        role_code: rule.role || rule.role_code || '',
        role_name: rule.role_name || rule.role || '',
        operations: Array.isArray(rule.operations)
          ? rule.operations
        : String(rule.op || '')
              .split(',')
              .map((item: string) => item.trim())
              .filter(Boolean),
        data_scope: rule.data_scope || rule.data || '',
        can_draft: !!(rule.can_draft ?? rule.canDraft),
        can_import: !!(rule.can_import ?? rule.canImport),
        can_export: !!(rule.can_export ?? rule.canExport),
      })),
  }))
})

function formatBool(value: any) {
  return value ? '是' : '否'
}

function formatPermissionFlag(source: any, expectedOps: string[], boolKey?: string) {
  if (boolKey && source && source[boolKey]) return '是'
  const operations = Array.isArray(source) ? source : source?.operations
  if (!Array.isArray(operations)) return '否'
  const normalized = operations.map((item: any) => String(item).trim().toLowerCase())
  if (normalized.includes('all')) return '是'
  return expectedOps.some(op => normalized.includes(op.toLowerCase())) ? '是' : '否'
}


function formatDataScope(value: any) {
  const key = String(value || '').trim()
  const scopeMap: Record<string, string> = {
    ALL: '全公司',
    SELF: '仅本人',
    CURRENT_USER_DEPT: '本部门',
    CURRENT_USER_DEPT_LOW_LEVEL: '本部门及下级',
    all: '全公司',
    self: '仅本人',
    dept: '本部门',
  }
  return scopeMap[key] || key || '-'
}

const componentTypeLabels: Record<string, string> = {
  FORM_DOCUMENT_NUMBER: '单据号',
  FORM_TEXT_INPUT: '单行输入',
  FORM_TEXTAREA_INPUT: '多行输入',
  FORM_PHONE_INPUT: '手机号码',
  FORM_EMAIL_INPUT: '电子邮箱',
  FORM_SELECT_INPUT_SINGLE: '下拉单选',
  FORM_SELECT_INPUT: '下拉选择',
  FORM_DATA_SELECTOR_SINGLE: '数据单选',
  FORM_DATA_SELECTOR: '数据选择',
  FORM_DATEPICK_INPUT: '日期时间',
  FORM_MONEY_INPUT: '金额',
  FORM_NUMBER_INPUT: '数字',
  FORM_FILE_UPLOAD: '附件上传',
  FORM_SWITCH_SELECT: '开关',
  FORM_PEOPLE_SELECT: '人员选择',
  FORM_DEPARTMENT_SELECT: '部门选择',
  FORM_WIDGET_LOCATION: '地理位置',
  FORM_WIDGET_SON_TABLE: '子表',
  FORM_RADIO_INPUT: '单选框',
  FORM_CHECKBOX_INPUT: '复选框',
  FORM_RICH_TEXT: '富文本',
  FORM_HYPERLINK_INPUT: '超链接',
  FORM_IDCARD_INPUT: '身份证号',
  FORM_WIDGET_AREA: '地区地址',
  FORM_ASSOCIATION: '关联表单',
}

function formatComponentType(value: any) {
  const key = String(value || '').trim()
  return componentTypeLabels[key] || key || '-'
}

function displayComponentType(component: any) {
  return formatComponentType(component?.component_type || component?.raw_component_type)
}
</script>

<style scoped>
.structured-doc {
  display: flex;
  flex-direction: column;
  gap: 12px;
  color: #24324a;
}

.doc-section {
  padding-bottom: 10px;
  border-bottom: 1px solid rgba(161, 179, 226, 0.22);
}

.doc-section:last-child {
  border-bottom: none;
  padding-bottom: 0;
}

.app-hero {
  padding-bottom: 2px;
}

.doc-app-name {
  margin: 0;
  font-size: 20px;
  line-height: 1.2;
  font-weight: 800;
  color: #1d2940;
}

.doc-section-title {
  margin: 0 0 8px;
  font-size: 17px;
  line-height: 1.25;
  font-weight: 800;
  color: #1e2a43;
}

.doc-subsection {
  margin-top: 8px;
}

.doc-subsection:first-of-type {
  margin-top: 0;
}

.doc-subsection-title {
  margin: 0 0 6px;
  font-size: 14px;
  line-height: 1.35;
  font-weight: 700;
  color: #22314d;
}

.doc-sub-meta {
  margin: 0 0 6px;
  color: #6f7e99;
  font-size: 12px;
  line-height: 1.45;
}

.doc-app-desc {
  margin: 6px 0 0;
  color: #62708a;
  font-size: 12px;
  line-height: 1.55;
}

.doc-table-wrap {
  overflow-x: auto;
  border: 1px solid rgba(164, 181, 229, 0.22);
  background: rgba(255, 255, 255, 0.42);
}

.doc-table {
  width: 100%;
  border-collapse: collapse;
  min-width: 420px;
}

.doc-table th,
.doc-table td {
  padding: 8px 12px;
  border: 1px solid rgba(164, 181, 229, 0.22);
  text-align: left;
  vertical-align: top;
  font-size: 13px;
  line-height: 1.4;
}

.doc-table th {
  background: rgba(113, 140, 255, 0.08);
  color: #6c86ff;
  font-size: 13px;
  font-weight: 800;
}

.doc-table td {
  color: #22314d;
}

.empty-cell,
.doc-empty-block {
  color: #70809e;
}

.doc-empty-block {
  padding: 8px 0 0;
  font-size: 12px;
}

@media (max-width: 768px) {
  .structured-doc {
    gap: 12px;
  }

  .doc-app-name {
    font-size: 18px;
  }

  .doc-section-title {
    font-size: 15px;
  }

  .doc-subsection-title {
    font-size: 13px;
  }

  .doc-table th,
  .doc-table td {
    padding: 8px 9px;
    font-size: 12px;
  }

  .doc-table th {
    font-size: 12px;
  }
}
</style>
