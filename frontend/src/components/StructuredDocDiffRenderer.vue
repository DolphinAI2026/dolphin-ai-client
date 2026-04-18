<template>
  <div class="structured-doc diff-doc">
    <section class="doc-section app-hero">
      <h1 class="doc-app-name" :class="cellStatusClass(appInfoStatus('name'))">{{ appInfo.name }}</h1>
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
              <td :class="cellStatusClass(appInfoStatus('name'))">{{ appInfo.name || '-' }}</td>
              <td :class="cellStatusClass(appInfoStatus('code'))">{{ appInfo.code || '-' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="appInfo.description" class="doc-app-desc" :class="cellStatusClass(appInfoStatus('description'))">{{ appInfo.description }}</p>
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
            <tr v-for="role in roles" :key="roleKey(role)" :class="rowStatusClass(roleMeta(role).status)">
              <td :class="cellStatusClass(roleMeta(role).cells.role_code)">{{ role.role_code || '-' }}</td>
              <td :class="cellStatusClass(roleMeta(role).cells.role_name)">{{ role.role_name || '-' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="doc-section">
      <h2 class="doc-section-title">三、数据字典</h2>
      <div v-if="!dicts.length" class="doc-empty-block">暂无数据字典</div>
      <div v-for="dict in dicts" :key="dictKey(dict)" class="doc-subsection">
        <h3 class="doc-subsection-title" :class="titleStatusClass(dictMeta(dict).title)">{{ dict.dict_name || '未命名字典' }}（{{ dict.dict_code || '-' }}）</h3>
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
              <tr v-for="item in (dict.items || [])" :key="dictItemKey(item)" :class="rowStatusClass(dictItemMeta(dict, item).status)">
                <td :class="cellStatusClass(dictItemMeta(dict, item).cells.item_code)">{{ item.item_code || '-' }}</td>
                <td :class="cellStatusClass(dictItemMeta(dict, item).cells.item_name)">{{ item.item_name || '-' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>

    <section class="doc-section">
      <h2 class="doc-section-title">四、数据模型</h2>
      <div v-if="!tables.length" class="doc-empty-block">暂无数据模型</div>
      <div v-for="table in tables" :key="tableKey(table)" class="doc-subsection">
        <h3 class="doc-subsection-title" :class="titleStatusClass(tableMeta(table).title)">
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
              <tr v-for="field in (table.fields || [])" :key="fieldKey(field)" :class="rowStatusClass(tableFieldMeta(table, field).status)">
                <td :class="cellStatusClass(tableFieldMeta(table, field).cells.field_code)">{{ field.field_code || '-' }}</td>
                <td :class="cellStatusClass(tableFieldMeta(table, field).cells.field_name)">{{ field.field_name || '-' }}</td>
                <td :class="cellStatusClass(tableFieldMeta(table, field).cells.database_field_type)">{{ field.database_field_type || field.data_type || field.type || '-' }}</td>
                <td :class="cellStatusClass(tableFieldMeta(table, field).cells.length)">{{ field.max_length || field.length || '-' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>

    <section class="doc-section">
      <h2 class="doc-section-title">五、表单定义</h2>
      <div v-if="!forms.length" class="doc-empty-block">暂无表单定义</div>
      <div v-for="form in forms" :key="formKey(form)" class="doc-subsection">
        <h3 class="doc-subsection-title" :class="titleStatusClass(formMeta(form).title)">{{ form.form_name || '未命名表单' }}</h3>
        <div class="doc-sub-meta" :class="cellStatusClass(formTitleStatus(form))">
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
                <tr v-for="component in (form.main_components || [])" :key="fieldKey(component)" :class="rowStatusClass(formMainMeta(form, component).status)">
                  <td :class="cellStatusClass(formMainMeta(form, component).cells.field_code)">{{ component.field_code || '-' }}</td>
                  <td :class="cellStatusClass(formMainMeta(form, component).cells.field_name)">{{ component.field_name || '-' }}</td>
                  <td :class="cellStatusClass(formMainMeta(form, component).cells.component_type)">{{ displayComponentType(component) }}</td>
                  <td :class="cellStatusClass(formMainMeta(form, component).cells.required)">{{ formatBool(component.required) }}</td>
                  <td :class="cellStatusClass(formMainMeta(form, component).cells.hidden)">{{ formatBool(component.hidden) }}</td>
                  <td :class="cellStatusClass(formMainMeta(form, component).cells.readonly)">{{ formatBool(component.readonly) }}</td>
                  <td :class="cellStatusClass(formMainMeta(form, component).cells.show_in_list)">{{ formatBool(component.show_in_list) }}</td>
                  <td :class="cellStatusClass(formMainMeta(form, component).cells.searchable)">{{ formatBool(component.searchable) }}</td>
                  <td :class="cellStatusClass(formMainMeta(form, component).cells.dict_code)">{{ component.dict_code || '-' }}</td>
                  <td :class="cellStatusClass(formMainMeta(form, component).cells.ref_model_code)">{{ component.ref_model_code || component.selector_form_code || component.association_form_code || '-' }}</td>
                  <td :class="cellStatusClass(formMainMeta(form, component).cells.ref_display_field_code)">{{ component.ref_display_field_code || component.selector_field_code || component.association_target_field_code || '-' }}</td>
                  <td :class="cellStatusClass(formMainMeta(form, component).cells.association_origin_field_code)">{{ component.association_origin_field_code || '-' }}</td>
                  <td :class="cellStatusClass(formMainMeta(form, component).cells.description)">{{ component.description || '-' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div v-for="subGroup in (form.sub_groups || [])" :key="subGroupKey(subGroup)" class="doc-form-group">
          <div class="doc-form-group-title" :class="titleStatusClass(subGroupMeta(form, subGroup).title)">
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
              <tr v-for="component in (subGroup.components || [])" :key="fieldKey(component)" :class="rowStatusClass(subGroupComponentMeta(form, subGroup, component).status)">
                <td :class="cellStatusClass(subGroupComponentMeta(form, subGroup, component).cells.field_code)">{{ component.field_code || '-' }}</td>
                <td :class="cellStatusClass(subGroupComponentMeta(form, subGroup, component).cells.field_name)">{{ component.field_name || '-' }}</td>
                <td :class="cellStatusClass(subGroupComponentMeta(form, subGroup, component).cells.component_type)">{{ displayComponentType(component) }}</td>
                <td :class="cellStatusClass(subGroupComponentMeta(form, subGroup, component).cells.required)">{{ formatBool(component.required) }}</td>
                <td :class="cellStatusClass(subGroupComponentMeta(form, subGroup, component).cells.hidden)">{{ formatBool(component.hidden) }}</td>
                <td :class="cellStatusClass(subGroupComponentMeta(form, subGroup, component).cells.readonly)">{{ formatBool(component.readonly) }}</td>
                <td :class="cellStatusClass(subGroupComponentMeta(form, subGroup, component).cells.show_in_list)">{{ formatBool(component.show_in_list) }}</td>
                <td :class="cellStatusClass(subGroupComponentMeta(form, subGroup, component).cells.searchable)">{{ formatBool(component.searchable) }}</td>
                <td :class="cellStatusClass(subGroupComponentMeta(form, subGroup, component).cells.dict_code)">{{ component.dict_code || '-' }}</td>
                <td :class="cellStatusClass(subGroupComponentMeta(form, subGroup, component).cells.ref_model_code)">{{ component.ref_model_code || component.selector_form_code || component.association_form_code || '-' }}</td>
                <td :class="cellStatusClass(subGroupComponentMeta(form, subGroup, component).cells.ref_display_field_code)">{{ component.ref_display_field_code || component.selector_field_code || component.association_target_field_code || '-' }}</td>
                <td :class="cellStatusClass(subGroupComponentMeta(form, subGroup, component).cells.association_origin_field_code)">{{ component.association_origin_field_code || '-' }}</td>
                <td :class="cellStatusClass(subGroupComponentMeta(form, subGroup, component).cells.description)">{{ component.description || '-' }}</td>
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
      <div v-for="mapping in roleTableMapping" :key="permissionGroupKey(mapping)" class="doc-subsection">
        <h3 class="doc-subsection-title" :class="titleStatusClass(permissionGroupMeta(mapping).title)">{{ mapping.table_name || mapping.table_code || '未命名对象' }}</h3>
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
              <tr v-for="perm in (mapping.permissions || [])" :key="roleKey(perm)" :class="rowStatusClass(permissionRowMeta(mapping, perm).status)">
                <td :class="cellStatusClass(permissionRowMeta(mapping, perm).cells.role_code)">{{ perm.role_code || '-' }}</td>
                <td :class="cellStatusClass(permissionRowMeta(mapping, perm).cells.can_draft)">{{ formatPermissionFlag(perm, ['stash', 'save', 'draft'], 'can_draft') }}</td>
                <td :class="cellStatusClass(permissionRowMeta(mapping, perm).cells.can_add)">{{ formatPermissionFlag(perm.operations, ['add']) }}</td>
                <td :class="cellStatusClass(permissionRowMeta(mapping, perm).cells.can_import)">{{ formatPermissionFlag(perm, ['import'], 'can_import') }}</td>
                <td :class="cellStatusClass(permissionRowMeta(mapping, perm).cells.can_view)">{{ formatPermissionFlag(perm.operations, ['view']) }}</td>
                <td :class="cellStatusClass(permissionRowMeta(mapping, perm).cells.can_edit)">{{ formatPermissionFlag(perm.operations, ['edit']) }}</td>
                <td :class="cellStatusClass(permissionRowMeta(mapping, perm).cells.can_delete)">{{ formatPermissionFlag(perm.operations, ['delete']) }}</td>
                <td :class="cellStatusClass(permissionRowMeta(mapping, perm).cells.can_export)">{{ formatPermissionFlag(perm, ['export'], 'can_export') }}</td>
                <td :class="cellStatusClass(permissionRowMeta(mapping, perm).cells.data_scope)">{{ formatDataScope(perm.data_scope) }}</td>
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
import type { DiffGroupMeta, DiffRowMeta, DiffStatus, StructuredDocPaneDiffMeta } from '@/utils/structuredDocDiff'

const props = defineProps<{
  docResult: any
  diffMeta?: StructuredDocPaneDiffMeta
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
  return source.map((table: any) => ({
    table_code: table.table_code || table.code || '',
    table_name: table.table_name || table.name || '',
    table_type: table.table_type || table.tableType || '',
    fields: (table.fields || []).map((field: any) => ({
      field_code: field.field_code || field.code || '',
      field_name: field.field_name || field.name || '',
      database_field_type: field.database_field_type || field.databaseFieldType || field.db_type || 'varchar',
      max_length: field.max_length || field.maxLength || field.length || '',
      length: field.length || field.max_length || field.maxLength || '',
      type: field.type || field.field_type || '',
      required: !!field.required,
      hidden: !!field.hidden,
      readonly: !!(field.readonly ?? field.readOnly),
    })),
  }))
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
          selector_field_code:
            component.selector_field_code
            || component.selectorFieldCode
            || component.ref_display_field_code
            || component.refDisplayFieldCode
            || ref.display_field
            || ref.target_field
            || ref.field
            || '',
          association_form_code:
            component.association_form_code
            || component.associationFormCode
            || associationConfig.targetModelCode
            || '',
          association_origin_field_code:
            component.association_origin_field_code
            || component.associationOriginFieldCode
            || associationConfig.originFieldCode
            || '',
          association_target_field_code:
            component.association_target_field_code
            || component.associationTargetFieldCode
            || associationConfig.targetFieldCode
            || '',
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
        form_code: form.form_code || form.formCode || form.code || '',
        main_model_code: mainModelCode || '-',
        main_components: mainComponents,
        sub_groups: subGroups,
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
  return legacy.map((mapping: any) => ({
    table_code: mapping.table_code || '',
    table_name: mapping.table_name || formNameMap.get(String(mapping.table_code || '')) || '',
    permissions: (mapping.permissions || []).map((perm: any) => ({
      role_code: perm.role_code || perm.role || '',
      role_name: perm.role_name || perm.role || '',
      operations: Array.isArray(perm.operations)
        ? perm.operations
        : String(perm.op || '').split(',').map((item: string) => item.trim()).filter(Boolean),
      data_scope: perm.data_scope || perm.data || '',
      can_draft: !!(perm.can_draft ?? perm.canDraft),
      can_import: !!(perm.can_import ?? perm.canImport),
      can_export: !!(perm.can_export ?? perm.canExport),
    })),
  }))
})

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

function formatComponentType(value: any) {
  const key = String(value || '').trim()
  return componentTypeLabels[key] || key || '-'
}

function displayComponentType(component: any) {
  return formatComponentType(component?.component_type || component?.raw_component_type)
}

function fallbackRowMeta(columns: string[]): DiffRowMeta {
  return { status: 'same', cells: Object.fromEntries(columns.map(column => [column, 'same' as DiffStatus])) }
}

function fallbackGroupMeta(): DiffGroupMeta {
  return { status: 'same', title: 'same' }
}

function appInfoStatus(key: string) {
  return props.diffMeta?.appInfo?.[key] || 'same'
}

function roleKey(role: any) {
  return String(role?.role_code || role?.role_name || '')
}

function dictKey(dict: any) {
  return String(dict?.dict_code || dict?.dict_name || '')
}

function dictItemKey(item: any) {
  return String(item?.item_code || item?.item_name || '')
}

function tableKey(table: any) {
  return String(table?.table_code || table?.table_name || '')
}

function fieldKey(field: any) {
  return String(field?.field_code || field?.field_name || '')
}

function formKey(form: any) {
  return String(form?.form_code || form?.form_name || form?.main_model_code || '')
}

function subGroupKey(group: any) {
  return String(group?.model_code || group?.group_name || group?.model_name || '')
}

function permissionGroupKey(group: any) {
  return String(group?.table_code || group?.table_name || '')
}

function roleMeta(role: any) {
  return props.diffMeta?.roles?.[roleKey(role)] || fallbackRowMeta(['role_code', 'role_name'])
}

function dictMeta(dict: any) {
  return props.diffMeta?.dicts?.[dictKey(dict)] || fallbackGroupMeta()
}

function dictItemMeta(dict: any, item: any) {
  return props.diffMeta?.dicts?.[dictKey(dict)]?.items?.[dictItemKey(item)] || fallbackRowMeta(['item_code', 'item_name'])
}

function tableMeta(table: any) {
  return props.diffMeta?.tables?.[tableKey(table)] || fallbackGroupMeta()
}

function tableFieldMeta(table: any, field: any) {
  return props.diffMeta?.tables?.[tableKey(table)]?.fields?.[fieldKey(field)] || fallbackRowMeta(['field_code', 'field_name', 'database_field_type', 'length'])
}

function formMeta(form: any) {
  return props.diffMeta?.forms?.[formKey(form)] || fallbackGroupMeta()
}

function formTitleStatus(form: any) {
  return formMeta(form).title || 'same'
}

function formMainMeta(form: any, component: any) {
  return props.diffMeta?.forms?.[formKey(form)]?.mainComponents?.[fieldKey(component)] || fallbackRowMeta(['field_code', 'field_name', 'component_type', 'required', 'hidden', 'readonly', 'show_in_list', 'searchable', 'dict_code', 'ref_model_code', 'ref_display_field_code', 'association_origin_field_code', 'description'])
}

function subGroupMeta(form: any, subGroup: any) {
  return props.diffMeta?.forms?.[formKey(form)]?.subGroups?.[subGroupKey(subGroup)] || fallbackGroupMeta()
}

function subGroupComponentMeta(form: any, subGroup: any, component: any) {
  return props.diffMeta?.forms?.[formKey(form)]?.subGroups?.[subGroupKey(subGroup)]?.components?.[fieldKey(component)] || fallbackRowMeta(['field_code', 'field_name', 'component_type', 'required', 'hidden', 'readonly', 'show_in_list', 'searchable', 'dict_code', 'ref_model_code', 'ref_display_field_code', 'association_origin_field_code', 'description'])
}

function permissionGroupMeta(group: any) {
  return props.diffMeta?.permissions?.[permissionGroupKey(group)] || fallbackGroupMeta()
}

function permissionRowMeta(group: any, perm: any) {
  return props.diffMeta?.permissions?.[permissionGroupKey(group)]?.rows?.[roleKey(perm)] || fallbackRowMeta(['role_code', 'can_draft', 'can_add', 'can_import', 'can_view', 'can_edit', 'can_delete', 'can_export', 'data_scope'])
}

function rowStatusClass(status: DiffStatus) {
  return {
    'diff-row-added': status === 'added',
    'diff-row-removed': status === 'removed',
    'diff-row-modified': status === 'modified',
  }
}

function cellStatusClass(status: DiffStatus) {
  return {
    'diff-cell-added': status === 'added',
    'diff-cell-removed': status === 'removed',
    'diff-cell-modified': status === 'modified',
  }
}

function titleStatusClass(status: DiffStatus) {
  return {
    'diff-title-added': status === 'added',
    'diff-title-removed': status === 'removed',
    'diff-title-modified': status === 'modified',
  }
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
  font-weight: 700;
  color: #1f2b44;
}

.doc-sub-meta,
.doc-form-group-title,
.doc-form-group-code,
.doc-app-desc {
  color: #5f6f90;
}

.doc-form-group {
  margin-top: 10px;
}

.doc-table-wrap {
  overflow-x: auto;
}

.doc-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  table-layout: auto;
}

.doc-table th {
  background: rgba(99, 102, 241, 0.1);
  color: #4f46e5;
  text-align: left;
  padding: 8px 12px;
  border: 1px solid rgba(161, 179, 226, 0.24);
  font-weight: 600;
  white-space: nowrap;
}

.doc-table td {
  padding: 6px 12px;
  border: 1px solid rgba(161, 179, 226, 0.2);
  white-space: nowrap;
}

.empty-cell,
.doc-empty-block {
  color: #8ea0bf;
}

.diff-doc .doc-table tbody tr {
  transition: background-color 0.2s ease;
}

.diff-cell-added {
  background: rgba(34, 197, 94, 0.14);
  color: #14532d;
  font-weight: 600;
}

.diff-cell-removed {
  background: rgba(239, 68, 68, 0.14);
  color: #7f1d1d;
  font-weight: 600;
}

.diff-cell-modified {
  background: rgba(245, 158, 11, 0.14);
  color: #78350f;
  font-weight: 600;
}

.diff-row-added td {
  box-shadow: inset 0 0 0 9999px rgba(34, 197, 94, 0.05);
}

.diff-row-removed td {
  box-shadow: inset 0 0 0 9999px rgba(239, 68, 68, 0.05);
}

.diff-row-modified td {
  box-shadow: inset 0 0 0 9999px rgba(245, 158, 11, 0.04);
}

.diff-title-added {
  color: #15803d;
}

.diff-title-removed {
  color: #b91c1c;
}

.diff-title-modified {
  color: #b45309;
}
</style>
