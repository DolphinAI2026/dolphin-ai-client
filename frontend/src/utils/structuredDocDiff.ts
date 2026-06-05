export type DiffStatus = 'same' | 'added' | 'removed' | 'modified'

type AnyRecord = Record<string, any>
type CellMeta = Record<string, DiffStatus>

export interface DiffRowMeta {
  status: DiffStatus
  cells: CellMeta
}

export interface DiffGroupMeta {
  status: DiffStatus
  title: DiffStatus
  rows?: Record<string, DiffRowMeta>
  items?: Record<string, DiffRowMeta>
  fields?: Record<string, DiffRowMeta>
  mainComponents?: Record<string, DiffRowMeta>
  subGroups?: Record<string, DiffGroupMeta>
  components?: Record<string, DiffRowMeta>
}

export interface StructuredDocPaneDiffMeta {
  appInfo: CellMeta
  roles: Record<string, DiffRowMeta>
  dicts: Record<string, DiffGroupMeta>
  tables: Record<string, DiffGroupMeta>
  forms: Record<string, DiffGroupMeta>
  permissions: Record<string, DiffGroupMeta>
}

export interface StructuredDocDiffResult {
  left: StructuredDocPaneDiffMeta
  right: StructuredDocPaneDiffMeta
  stats: {
    added: number
    removed: number
    modified: number
    same: number
  }
}

function normalizeValue(value: any) {
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  return String(value ?? '').trim()
}

function createPaneMeta(): StructuredDocPaneDiffMeta {
  return {
    appInfo: {},
    roles: {},
    dicts: {},
    tables: {},
    forms: {},
    permissions: {},
  }
}

function createRowMeta(status: DiffStatus, columns: string[]): DiffRowMeta {
  const cells: CellMeta = {}
  columns.forEach((column) => {
    cells[column] = status
  })
  return { status, cells }
}

function compareCells(
  leftRow: AnyRecord | undefined,
  rightRow: AnyRecord | undefined,
  columns: string[],
) {
  const leftMeta: CellMeta = {}
  const rightMeta: CellMeta = {}
  let hasModified = false
  let hasSame = false

  for (const column of columns) {
    const leftValue = normalizeValue(leftRow?.[column])
    const rightValue = normalizeValue(rightRow?.[column])
    if (leftValue === rightValue) {
      leftMeta[column] = 'same'
      rightMeta[column] = 'same'
      hasSame = true
    } else {
      leftMeta[column] = leftRow ? 'modified' : 'same'
      rightMeta[column] = rightRow ? 'modified' : 'same'
      hasModified = true
    }
  }

  const rowStatus: DiffStatus = hasModified ? 'modified' : 'same'
  return {
    left: { status: rowStatus, cells: leftMeta },
    right: { status: rowStatus, cells: rightMeta },
    hasModified,
    hasSame,
  }
}

function applyRowDiff(
  leftRows: any[],
  rightRows: any[],
  columns: string[],
  keyGetter: (row: any, index: number) => string,
) {
  const leftMeta: Record<string, DiffRowMeta> = {}
  const rightMeta: Record<string, DiffRowMeta> = {}
  let added = 0
  let removed = 0
  let modified = 0
  let same = 0

  const leftMap = new Map(leftRows.map((row, index) => [keyGetter(row, index), row]))
  const rightMap = new Map(rightRows.map((row, index) => [keyGetter(row, index), row]))
  const keys = Array.from(new Set([...leftMap.keys(), ...rightMap.keys()]))

  for (const key of keys) {
    const leftRow = leftMap.get(key)
    const rightRow = rightMap.get(key)
    if (leftRow && !rightRow) {
      leftMeta[key] = createRowMeta('removed', columns)
      removed += 1
      continue
    }
    if (!leftRow && rightRow) {
      rightMeta[key] = createRowMeta('added', columns)
      added += 1
      continue
    }
    if (!leftRow || !rightRow) continue

    const compared = compareCells(leftRow, rightRow, columns)
    leftMeta[key] = compared.left
    rightMeta[key] = compared.right
    if (compared.hasModified) modified += 1
    else same += 1
  }

  return { leftMeta, rightMeta, stats: { added, removed, modified, same } }
}

function mergeStatuses(statuses: DiffStatus[]): DiffStatus {
  if (statuses.includes('added')) return 'added'
  if (statuses.includes('removed')) return 'removed'
  if (statuses.includes('modified')) return 'modified'
  return 'same'
}

function groupTitleStatus(selfColumns: DiffStatus[], nestedStatuses: DiffStatus[]): DiffStatus {
  return mergeStatuses([...selfColumns, ...nestedStatuses])
}

function keyedMap(rows: any[], keyGetter: (row: any, index: number) => string): Map<string, AnyRecord> {
  return new Map(rows.map((row, index) => [keyGetter(row, index), row as AnyRecord]))
}

function mergedKeys(...maps: Array<Map<string, AnyRecord>>): string[] {
  return Array.from(new Set(maps.flatMap(map => Array.from(map.keys()))))
}

function addStats(target: StructuredDocDiffResult['stats'], source: StructuredDocDiffResult['stats'] | { added: number; removed: number; modified: number; same: number }) {
  target.added += source.added
  target.removed += source.removed
  target.modified += source.modified
  target.same += source.same
}

function roleKey(role: any, index = 0) {
  return String(role?.role_code || role?.code || role?.role_name || role?.name || `role_${index + 1}`)
}

function dictKey(dict: any, index = 0) {
  return String(dict?.dict_code || dict?.code || dict?.dict_name || dict?.name || `dict_${index + 1}`)
}

function dictItemKey(item: any, index = 0) {
  return String(item?.item_code || item?.code || item?.item_name || item?.name || `item_${index + 1}`)
}

function tableKey(table: any, index = 0) {
  return String(table?.table_code || table?.code || table?.table_name || table?.name || `table_${index + 1}`)
}

function fieldKey(field: any, index = 0) {
  return String(field?.field_code || field?.code || field?.field_name || field?.name || `field_${index + 1}`)
}

function formKey(form: any, index = 0) {
  return String(form?.form_code || form?.code || form?.form_name || form?.name || form?.main_model_code || `form_${index + 1}`)
}

function subGroupKey(group: any, index = 0) {
  return String(group?.model_code || group?.group_name || group?.model_name || `sub_group_${index + 1}`)
}

function permissionGroupKey(group: any, index = 0) {
  return String(group?.table_code || group?.form || group?.table_name || group?.form_name || `perm_${index + 1}`)
}

function normalizeFormForDiff(form: any) {
  const formName = form?.form_name || form?.formName || form?.name || ''
  const formCode = form?.form_code || form?.formCode || form?.code || ''
  const mainModelCode = form?.main_model_code || form?.model_code || form?.modelCode || form?.bindModelCode || ''
  const rawComponents = Array.isArray(form?.components) ? form.components : (Array.isArray(form?.formComponents) ? form.formComponents : [])
  if (Array.isArray(form?.main_components) || Array.isArray(form?.sub_groups)) {
    return {
      form_name: formName,
      form_code: formCode,
      main_model_code: mainModelCode,
      main_components: form?.main_components || [],
      sub_groups: form?.sub_groups || [],
    }
  }
  const components = rawComponents.map((component: any) => ({
    field_code: component?.field_code || component?.fieldCode || component?.code || '',
    field_name: component?.field_name || component?.fieldName || component?.label || component?.name || '',
    component_type: component?.component_type || component?.componentType || component?.type || '',
    required: !!component?.required,
    hidden: !!component?.hidden,
    readonly: !!(component?.readonly ?? component?.readOnly),
    show_in_list: !!(component?.show_in_list ?? component?.showInList),
    searchable: !!component?.searchable,
    dict_code: component?.dict_code || component?.dictCode || '',
    ref_model_code: component?.ref_model_code || component?.refModelCode || component?.selector_form_code || component?.selectorFormCode || component?.association_form_code || component?.associationFormCode || '',
    ref_display_field_code: component?.ref_display_field_code || component?.refDisplayFieldCode || component?.selector_field_code || component?.selectorFieldCode || component?.association_target_field_code || component?.associationTargetFieldCode || '',
    association_origin_field_code: component?.association_origin_field_code || component?.associationOriginFieldCode || '',
    description: component?.description || component?.comment || '',
    section_type: component?.section_type || component?.sectionType || (component?.componentType === 'FORM_WIDGET_SON_TABLE' ? 'sub' : 'main'),
    model_code: component?.model_code || component?.modelCode || component?.table_model_code || component?.tableModelCode || mainModelCode,
    sub_group_name: component?.sub_group_name || component?.subGroupName || '',
  }))
  const mainComponents = components.filter((component: any) => component.section_type !== 'sub')
  const subGroups = Array.from(new Set(
    components
      .filter((component: any) => component.section_type === 'sub')
      .map((component: any) => `${component.model_code || ''}::${component.sub_group_name || ''}`)
  ))
    .filter(Boolean)
    .map((groupKey) => {
      const [modelCode = '', groupName = ''] = String(groupKey).split('::')
      return {
        model_code: modelCode,
        group_name: groupName,
        components: components.filter((component: any) =>
          component.section_type === 'sub'
          && component.model_code === modelCode
          && (component.sub_group_name || '') === groupName
        ),
      }
    })
  return {
    form_name: formName,
    form_code: formCode,
    main_model_code: mainModelCode,
    main_components: mainComponents,
    sub_groups: subGroups,
  }
}

export function computeStructuredDocDiff(leftDoc: any, rightDoc: any): StructuredDocDiffResult {
  const result: StructuredDocDiffResult = {
    left: createPaneMeta(),
    right: createPaneMeta(),
    stats: { added: 0, removed: 0, modified: 0, same: 0 },
  }

  const leftApp = leftDoc?.app_info || {}
  const rightApp = rightDoc?.app_info || {}
  ;['name', 'code', 'description'].forEach((key) => {
    const leftValue = normalizeValue(leftApp[key])
    const rightValue = normalizeValue(rightApp[key])
    const status: DiffStatus = leftValue === rightValue ? 'same' : 'modified'
    result.left.appInfo[key] = status
    result.right.appInfo[key] = status
    result.stats[status === 'modified' ? 'modified' : 'same'] += 1
  })

  const roleDiff = applyRowDiff(leftDoc?.roles || [], rightDoc?.roles || [], ['role_code', 'role_name'], roleKey)
  result.left.roles = roleDiff.leftMeta
  result.right.roles = roleDiff.rightMeta
  addStats(result.stats, roleDiff.stats)

  const leftDicts = leftDoc?.data_dictionary || leftDoc?.dicts || []
  const rightDicts = rightDoc?.data_dictionary || rightDoc?.dicts || []
  const leftDictMap = keyedMap(leftDicts, dictKey)
  const rightDictMap = keyedMap(rightDicts, dictKey)
  for (const key of mergedKeys(leftDictMap, rightDictMap)) {
    const leftDict = leftDictMap.get(key)
    const rightDict = rightDictMap.get(key)
    if (leftDict && !rightDict) {
      result.left.dicts[key] = {
        status: 'removed',
        title: 'removed',
        items: Object.fromEntries((leftDict.items || []).map((item: any, index: number) => [dictItemKey(item, index), createRowMeta('removed', ['item_code', 'item_name'])])),
      }
      result.stats.removed += 1 + (leftDict.items || []).length
      continue
    }
    if (!leftDict && rightDict) {
      result.right.dicts[key] = {
        status: 'added',
        title: 'added',
        items: Object.fromEntries((rightDict.items || []).map((item: any, index: number) => [dictItemKey(item, index), createRowMeta('added', ['item_code', 'item_name'])])),
      }
      result.stats.added += 1 + (rightDict.items || []).length
      continue
    }
    if (!leftDict || !rightDict) continue
    const itemDiff = applyRowDiff(leftDict.items || [], rightDict.items || [], ['item_code', 'item_name'], dictItemKey)
    const titleStatus = groupTitleStatus(
      [
        normalizeValue(leftDict.dict_code) === normalizeValue(rightDict.dict_code) ? 'same' : 'modified',
        normalizeValue(leftDict.dict_name) === normalizeValue(rightDict.dict_name) ? 'same' : 'modified',
      ],
      [...Object.values(itemDiff.leftMeta), ...Object.values(itemDiff.rightMeta)].map(meta => meta.status),
    )
    result.left.dicts[key] = { status: titleStatus, title: titleStatus, items: itemDiff.leftMeta }
    result.right.dicts[key] = { status: titleStatus, title: titleStatus, items: itemDiff.rightMeta }
    addStats(result.stats, itemDiff.stats)
    result.stats[titleStatus === 'modified' ? 'modified' : 'same'] += 1
  }

  const leftTables = leftDoc?.tables || leftDoc?.models || []
  const rightTables = rightDoc?.tables || rightDoc?.models || []
  const leftTableMap = keyedMap(leftTables, tableKey)
  const rightTableMap = keyedMap(rightTables, tableKey)
  for (const key of mergedKeys(leftTableMap, rightTableMap)) {
    const leftTable = leftTableMap.get(key)
    const rightTable = rightTableMap.get(key)
    if (leftTable && !rightTable) {
      result.left.tables[key] = {
        status: 'removed',
        title: 'removed',
        fields: Object.fromEntries((leftTable.fields || []).map((field: any, index: number) => [fieldKey(field, index), createRowMeta('removed', ['field_code', 'field_name', 'database_field_type', 'length'])])),
      }
      result.stats.removed += 1 + (leftTable.fields || []).length
      continue
    }
    if (!leftTable && rightTable) {
      result.right.tables[key] = {
        status: 'added',
        title: 'added',
        fields: Object.fromEntries((rightTable.fields || []).map((field: any, index: number) => [fieldKey(field, index), createRowMeta('added', ['field_code', 'field_name', 'database_field_type', 'length'])])),
      }
      result.stats.added += 1 + (rightTable.fields || []).length
      continue
    }
    if (!leftTable || !rightTable) continue
    const fieldDiff = applyRowDiff(
      leftTable.fields || [],
      rightTable.fields || [],
      ['field_code', 'field_name', 'database_field_type', 'max_length', 'length'],
      fieldKey,
    )
    const titleStatus = groupTitleStatus(
      [
        normalizeValue(leftTable.table_code) === normalizeValue(rightTable.table_code) ? 'same' : 'modified',
        normalizeValue(leftTable.table_name) === normalizeValue(rightTable.table_name) ? 'same' : 'modified',
      ],
      [...Object.values(fieldDiff.leftMeta), ...Object.values(fieldDiff.rightMeta)].map(meta => meta.status),
    )
    result.left.tables[key] = { status: titleStatus, title: titleStatus, fields: fieldDiff.leftMeta }
    result.right.tables[key] = { status: titleStatus, title: titleStatus, fields: fieldDiff.rightMeta }
    addStats(result.stats, fieldDiff.stats)
    result.stats[titleStatus === 'modified' ? 'modified' : 'same'] += 1
  }

  const leftForms = leftDoc?.forms || []
  const rightForms = rightDoc?.forms || []
  const leftFormMap = new Map<string, AnyRecord>(leftForms.map((form: any, index: number) => {
    const normalized = normalizeFormForDiff(form)
    return [formKey(normalized, index), normalized]
  }))
  const rightFormMap = new Map<string, AnyRecord>(rightForms.map((form: any, index: number) => {
    const normalized = normalizeFormForDiff(form)
    return [formKey(normalized, index), normalized]
  }))
  for (const key of mergedKeys(leftFormMap, rightFormMap)) {
    const leftForm = leftFormMap.get(key)
    const rightForm = rightFormMap.get(key)
    if (leftForm && !rightForm) {
      result.left.forms[key] = {
        status: 'removed',
        title: 'removed',
        mainComponents: Object.fromEntries((leftForm.main_components || []).map((component: any, index: number) => [fieldKey(component, index), createRowMeta('removed', ['field_code', 'field_name', 'component_type', 'required', 'hidden', 'readonly', 'show_in_list', 'searchable', 'dict_code', 'ref_model_code', 'ref_display_field_code', 'association_origin_field_code', 'description'])])),
        subGroups: {},
      }
      result.stats.removed += 1 + (leftForm.main_components || []).length
      continue
    }
    if (!leftForm && rightForm) {
      result.right.forms[key] = {
        status: 'added',
        title: 'added',
        mainComponents: Object.fromEntries((rightForm.main_components || []).map((component: any, index: number) => [fieldKey(component, index), createRowMeta('added', ['field_code', 'field_name', 'component_type', 'required', 'hidden', 'readonly', 'show_in_list', 'searchable', 'dict_code', 'ref_model_code', 'ref_display_field_code', 'association_origin_field_code', 'description'])])),
        subGroups: {},
      }
      result.stats.added += 1 + (rightForm.main_components || []).length
      continue
    }
    if (!leftForm || !rightForm) continue

    const mainDiff = applyRowDiff(
      leftForm.main_components || [],
      rightForm.main_components || [],
      ['field_code', 'field_name', 'component_type', 'required', 'hidden', 'readonly', 'show_in_list', 'searchable', 'dict_code', 'ref_model_code', 'ref_display_field_code', 'association_origin_field_code', 'description'],
      fieldKey,
    )

    const leftSubGroups = leftForm.sub_groups || []
    const rightSubGroups = rightForm.sub_groups || []
    const leftSubMap = keyedMap(leftSubGroups, subGroupKey)
    const rightSubMap = keyedMap(rightSubGroups, subGroupKey)
    const leftSubMeta: Record<string, DiffGroupMeta> = {}
    const rightSubMeta: Record<string, DiffGroupMeta> = {}
    const subStatuses: DiffStatus[] = []
    for (const subKey of mergedKeys(leftSubMap, rightSubMap)) {
      const leftSub = leftSubMap.get(subKey)
      const rightSub = rightSubMap.get(subKey)
      if (leftSub && !rightSub) {
        leftSubMeta[subKey] = {
          status: 'removed',
          title: 'removed',
          components: Object.fromEntries((leftSub.components || []).map((component: any, index: number) => [fieldKey(component, index), createRowMeta('removed', ['field_code', 'field_name', 'component_type', 'required', 'hidden', 'readonly', 'show_in_list', 'searchable', 'dict_code', 'ref_model_code', 'ref_display_field_code', 'association_origin_field_code', 'description'])])),
        }
        subStatuses.push('removed')
        result.stats.removed += 1 + (leftSub.components || []).length
        continue
      }
      if (!leftSub && rightSub) {
        rightSubMeta[subKey] = {
          status: 'added',
          title: 'added',
          components: Object.fromEntries((rightSub.components || []).map((component: any, index: number) => [fieldKey(component, index), createRowMeta('added', ['field_code', 'field_name', 'component_type', 'required', 'hidden', 'readonly', 'show_in_list', 'searchable', 'dict_code', 'ref_model_code', 'ref_display_field_code', 'association_origin_field_code', 'description'])])),
        }
        subStatuses.push('added')
        result.stats.added += 1 + (rightSub.components || []).length
        continue
      }
      if (!leftSub || !rightSub) continue
      const subDiff = applyRowDiff(
        leftSub.components || [],
        rightSub.components || [],
        ['field_code', 'field_name', 'component_type', 'required', 'hidden', 'readonly', 'show_in_list', 'searchable', 'dict_code', 'ref_model_code', 'ref_display_field_code', 'association_origin_field_code', 'description'],
        fieldKey,
      )
      const subStatus = groupTitleStatus(
        [
          normalizeValue(leftSub.model_code) === normalizeValue(rightSub.model_code) ? 'same' : 'modified',
          normalizeValue(leftSub.group_name) === normalizeValue(rightSub.group_name) ? 'same' : 'modified',
        ],
        [...Object.values(subDiff.leftMeta), ...Object.values(subDiff.rightMeta)].map(meta => meta.status),
      )
      leftSubMeta[subKey] = { status: subStatus, title: subStatus, components: subDiff.leftMeta }
      rightSubMeta[subKey] = { status: subStatus, title: subStatus, components: subDiff.rightMeta }
      subStatuses.push(subStatus)
      addStats(result.stats, subDiff.stats)
      result.stats[subStatus === 'modified' ? 'modified' : 'same'] += 1
    }

    const formStatus = groupTitleStatus(
      [
        normalizeValue(leftForm.form_name) === normalizeValue(rightForm.form_name) ? 'same' : 'modified',
        normalizeValue(leftForm.main_model_code) === normalizeValue(rightForm.main_model_code) ? 'same' : 'modified',
      ],
      [
        ...Object.values(mainDiff.leftMeta).map(meta => meta.status),
        ...Object.values(mainDiff.rightMeta).map(meta => meta.status),
        ...subStatuses,
      ],
    )
    result.left.forms[key] = { status: formStatus, title: formStatus, mainComponents: mainDiff.leftMeta, subGroups: leftSubMeta }
    result.right.forms[key] = { status: formStatus, title: formStatus, mainComponents: mainDiff.rightMeta, subGroups: rightSubMeta }
    addStats(result.stats, mainDiff.stats)
    result.stats[formStatus === 'modified' ? 'modified' : 'same'] += 1
  }

  const leftPerms = leftDoc?.role_table_mapping || []
  const rightPerms = rightDoc?.role_table_mapping || []
  const leftPermMap = keyedMap(leftPerms, permissionGroupKey)
  const rightPermMap = keyedMap(rightPerms, permissionGroupKey)
  for (const key of mergedKeys(leftPermMap, rightPermMap)) {
    const leftGroup = leftPermMap.get(key)
    const rightGroup = rightPermMap.get(key)
    if (leftGroup && !rightGroup) {
      result.left.permissions[key] = {
        status: 'removed',
        title: 'removed',
        rows: Object.fromEntries((leftGroup.permissions || []).map((row: any, index: number) => [roleKey(row, index), createRowMeta('removed', ['role_code', 'can_draft', 'can_add', 'can_import', 'can_view', 'can_edit', 'can_delete', 'can_export', 'data_scope'])])),
      }
      result.stats.removed += 1 + (leftGroup.permissions || []).length
      continue
    }
    if (!leftGroup && rightGroup) {
      result.right.permissions[key] = {
        status: 'added',
        title: 'added',
        rows: Object.fromEntries((rightGroup.permissions || []).map((row: any, index: number) => [roleKey(row, index), createRowMeta('added', ['role_code', 'can_draft', 'can_add', 'can_import', 'can_view', 'can_edit', 'can_delete', 'can_export', 'data_scope'])])),
      }
      result.stats.added += 1 + (rightGroup.permissions || []).length
      continue
    }
    if (!leftGroup || !rightGroup) continue
    const leftRows = (leftGroup.permissions || []).map((row: any) => ({
      role_code: row.role_code,
      can_draft: row.can_draft,
      can_add: Array.isArray(row.operations) ? row.operations.includes('add') || row.operations.includes('all') : false,
      can_import: row.can_import,
      can_view: Array.isArray(row.operations) ? row.operations.includes('view') || row.operations.includes('all') : false,
      can_edit: Array.isArray(row.operations) ? row.operations.includes('edit') || row.operations.includes('all') : false,
      can_delete: Array.isArray(row.operations) ? row.operations.includes('delete') || row.operations.includes('all') : false,
      can_export: row.can_export,
      data_scope: row.data_scope,
    }))
    const rightRows = (rightGroup.permissions || []).map((row: any) => ({
      role_code: row.role_code,
      can_draft: row.can_draft,
      can_add: Array.isArray(row.operations) ? row.operations.includes('add') || row.operations.includes('all') : false,
      can_import: row.can_import,
      can_view: Array.isArray(row.operations) ? row.operations.includes('view') || row.operations.includes('all') : false,
      can_edit: Array.isArray(row.operations) ? row.operations.includes('edit') || row.operations.includes('all') : false,
      can_delete: Array.isArray(row.operations) ? row.operations.includes('delete') || row.operations.includes('all') : false,
      can_export: row.can_export,
      data_scope: row.data_scope,
    }))
    const permDiff = applyRowDiff(
      leftRows,
      rightRows,
      ['role_code', 'can_draft', 'can_add', 'can_import', 'can_view', 'can_edit', 'can_delete', 'can_export', 'data_scope'],
      roleKey,
    )
    const permStatus = groupTitleStatus(
      [
        normalizeValue(leftGroup.table_code) === normalizeValue(rightGroup.table_code) ? 'same' : 'modified',
        normalizeValue(leftGroup.table_name) === normalizeValue(rightGroup.table_name) ? 'same' : 'modified',
      ],
      [...Object.values(permDiff.leftMeta), ...Object.values(permDiff.rightMeta)].map(meta => meta.status),
    )
    result.left.permissions[key] = { status: permStatus, title: permStatus, rows: permDiff.leftMeta }
    result.right.permissions[key] = { status: permStatus, title: permStatus, rows: permDiff.rightMeta }
    addStats(result.stats, permDiff.stats)
    result.stats[permStatus === 'modified' ? 'modified' : 'same'] += 1
  }

  return result
}
