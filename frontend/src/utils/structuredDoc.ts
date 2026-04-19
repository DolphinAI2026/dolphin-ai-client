type TableRow = Record<string, string>

const HEADER_ALIASES: Record<string, string> = {
  '应用编码': '应用编码',
  '应用名称': '应用名称',
  '角色编码': '角色编码',
  '角色名称': '角色名称',
  '字典编码': '字典编码',
  '字典名称': '字典名称',
  '选项编码': '选项编码',
  '选项名称': '选项名称',
  '模型编码': '模型编码',
  '模型名称': '模型名称',
  '字段编码': '字段编码',
  '字段名称': '字段名称',
  '数据库字段类型': '数据库字段类型',
  '长度/精度': '长度/精度',
  '长度': '长度',
  '字典编码 ': '字典编码',
  '关联模型编码': '目标模型编码',
  '关联显示字段编码': '目标字段编码',
  '说明': '说明',
  '表单名称': '表单名称',
  '表单编码': '表单编码',
  '表单名': '表单名称',
  '绑定主表模型编码': '绑定主表模型',
  '绑定主表模型名称': '绑定主表模型',
  '绑定主表模型': '绑定主表模型',
  '组件类型': '组件类型',
  '必填': '必填',
  '是否必填': '是否必填',
  '隐藏': '隐藏',
  '是否隐藏': '是否隐藏',
  '只读': '只读',
  '是否只读': '是否只读',
  '列表展示': '列表展示',
  '是否列表展示': '是否列表展示',
  '查询条件': '查询条件',
  '是否查询条件': '是否查询条件',
  '子表模型编码': '子表模型编码',
  '子表模型名称': '子表模型名称',
  '子表显示名称': '子表显示名称',
  '子表字段编码': '子表字段编码',
  '子表字段名称': '子表字段名称',
  '数据选择目标表单编码': '数据选择目标表单编码',
  '数据选择目标表单名称': '数据选择目标表单名称',
  '数据选择展示字段编码': '数据选择展示字段编码',
  '数据选择展示字段名称': '数据选择展示字段名称',
  '目标表编码': '目标模型编码',
  '目标模型编码': '目标模型编码',
  '目标字段编码': '目标字段编码',
  '关联表单编码': '关联表单编码',
  '关联表单名称': '关联表单名称',
  '本表关联字段编码': '本表关联字段编码',
  '本表关联字段名称': '本表关联字段名称',
  '关联表单关联字段编码': '关联表单关联字段编码',
  '关联表单关联字段名称': '关联表单关联字段名称',
  '可暂存': '可暂存',
  '可新增': '可新增',
  '可导入': '可导入',
  '可查看': '可查看',
  '可编辑': '可编辑',
  '可删除': '可删除',
  '可导出': '可导出',
  '数据范围': '数据范围',
}

function resolveRefMeta(source: any): { model: string; field: string } {
  const association = source?.formAssociationConfig || source?.form_association_config || {}
  if (association && typeof association === 'object' && association.targetModelCode) {
    return {
      model: String(association.targetModelCode || ''),
      field: String(association.targetFieldCode || ''),
    }
  }
  const ref = source?.ref || {}
  if (ref && typeof ref === 'object') {
    return {
      model: String(ref.model || ''),
      field: String(ref.display_field || ref.target_field || ref.field || ''),
    }
  }
  return { model: '', field: '' }
}

function normalizeHeader(value: string) {
  return value.trim().replace(/\s+/g, '')
}

function resolveHeader(value: string) {
  const normalized = normalizeHeader(value)
  return HEADER_ALIASES[normalized] || normalized
}

function stripFrontmatter(markdown: string) {
  const match = markdown.match(/^---\n([\s\S]*?)\n---\n?/)
  if (!match) return { body: markdown, frontmatter: {} as Record<string, string> }
  const frontmatterBlock = match[1] ?? ''

  const frontmatter: Record<string, string> = {}
  for (const line of frontmatterBlock.split('\n')) {
    const idx = line.indexOf(':')
    if (idx === -1) continue
    const key = line.slice(0, idx).trim()
    const value = line.slice(idx + 1).trim()
    if (key) frontmatter[key] = value
  }
  return {
    body: markdown.slice(match[0].length),
    frontmatter,
  }
}

function splitRow(line: string) {
  let value = line.trim()
  if (value.startsWith('|')) value = value.slice(1)
  if (value.endsWith('|')) value = value.slice(0, -1)
  return value.split('|').map(cell => cell.trim())
}

function isSeparator(line: string) {
  return /^\|?[\s:-]+(\|[\s:-]+)+\|?$/.test(line.trim())
}

function findTables(text: string) {
  const lines = text.split('\n')
  const tables: string[] = []
  let i = 0

  while (i < lines.length) {
    const currentLine = lines[i] ?? ''
    const nextLine = lines[i + 1] ?? ''
    if (currentLine.includes('|') && i + 1 < lines.length && isSeparator(nextLine)) {
      let j = i + 2
      while (j < lines.length && (lines[j] ?? '').includes('|')) j += 1
      tables.push(lines.slice(i, j).join('\n'))
      i = j
      continue
    }
    i += 1
  }

  return tables
}

function parseSingleTable(tableText: string): TableRow[] {
  const lines = tableText.split('\n').filter(line => line.trim())
  if (lines.length < 2) return []

  const headers = splitRow(lines[0] ?? '').map(resolveHeader)
  return lines.slice(2).map((line) => {
    const cells = splitRow(line)
    while (cells.length < headers.length) cells.push('')
    const row: TableRow = {}
    headers.forEach((header, index) => {
      row[header] = cells[index] || ''
    })
    return row
  })
}

function parseAllTables(text: string) {
  return findTables(text).map(parseSingleTable)
}

function splitSections(markdown: string) {
  const sections = new Map<string, string>()
  const lines = markdown.split('\n')
  let currentTitle = ''
  let currentLines: string[] = []

  for (const line of lines) {
    const match = line.match(/^##\s+(?:[一二三四五六七八九十]+[、.]?\s*)?(.+)$/)
    if (match) {
      if (currentTitle) sections.set(currentTitle, currentLines.join('\n').trim())
      currentTitle = (match[1] ?? '').trim()
      currentLines = []
      continue
    }
    if (currentTitle) currentLines.push(line)
  }

  if (currentTitle) sections.set(currentTitle, currentLines.join('\n').trim())
  return sections
}

function splitSubsections(text: string) {
  const blocks: Array<{ title: string; content: string }> = []
  const lines = text.split('\n')
  let currentTitle = ''
  let currentLines: string[] = []

  for (const line of lines) {
    if (line.startsWith('### ')) {
      if (currentTitle) blocks.push({ title: currentTitle, content: currentLines.join('\n').trim() })
      currentTitle = line.replace(/^###\s+/, '').trim()
      currentLines = []
      continue
    }
    if (currentTitle) currentLines.push(line)
  }

  if (currentTitle) blocks.push({ title: currentTitle, content: currentLines.join('\n').trim() })
  return blocks
}

function getSection(sections: Map<string, string>, names: string[]) {
  for (const name of names) {
    const value = sections.get(name)
    if (value) return value
  }
  return ''
}

function boolCell(value?: string) {
  return ['是', 'yes', 'true', '1', 'y'].includes(String(value || '').trim().toLowerCase())
}

function titleAfterMarker(title: string, marker: string) {
  const idx = title.indexOf(marker)
  return idx >= 0 ? title.slice(idx + marker.length).trim() : title.trim()
}

function normalizeSubtableName(name: string) {
  return name.replace(/[（(][^）)]+[）)]/g, '').trim()
}

function buildOperations(row: TableRow) {
  const operations: string[] = []
  if (boolCell(row['可暂存'])) operations.push('stash')
  if (boolCell(row['可新增'])) operations.push('add')
  if (boolCell(row['可查看'])) operations.push('view')
  if (boolCell(row['可编辑'])) operations.push('edit')
  if (boolCell(row['可删除'])) operations.push('delete')
  if (boolCell(row['可导入'])) operations.push('import')
  if (boolCell(row['可导出'])) operations.push('export')
  return operations
}

export function buildStructuredDocFromPreviewConfig(
  data: any,
  options?: {
    appName?: string
    appCode?: string
    description?: string
  }
) {
  if (!data || typeof data !== 'object') return null

  const formNameMap = new Map<string, string>()
  const roleNameMap = new Map<string, string>()
  ;(data.forms || []).forEach((form: any, idx: number) => {
    const formName = form?.formName || form?.name || `表单${idx + 1}`
    const formCode = form?.formCode || form?.code
    const modelCode = form?.modelCode || form?.bindModelCode
    if (formCode) formNameMap.set(String(formCode), formName)
    if (modelCode) formNameMap.set(String(modelCode), formName)
  })
  ;(data.roles || []).forEach((role: any, idx: number) => {
    const roleCode = String(role?.code || `role_${idx + 1}`)
    const roleName = role?.name || role?.role_name || roleCode
    roleNameMap.set(roleCode, roleName)
  })

  const roleTableMapping = (data.permissions || []).map((perm: any, idx: number) => ({
    table_name: formNameMap.get(String(perm?.form || perm?.formName || perm?.form_code || perm?.formCode || perm?.table || perm?.table_code || ''))
      || perm?.form_name
      || perm?.formName
      || perm?.form
      || perm?.table
      || `表${idx + 1}`,
    table_code: perm?.form_code || perm?.formCode || perm?.table_code || `table_${idx + 1}`,
    permissions: (perm?.rules || perm?.roles || perm?.permissions || []).map((r: any, rIdx: number) => {
      const roleCode = String(r?.role_code || r?.roleCode || r?.code || r?.role || `role_${rIdx + 1}`)
      return {
        role_code: roleCode,
        role_name: r?.role_name || r?.roleName || r?.name || roleNameMap.get(roleCode) || roleCode,
        operations: r?.actions || r?.operations || r?.permissions || (typeof r?.op === 'string'
          ? r.op.split(',').map((item: string) => item.trim()).filter(Boolean)
          : []),
        data_scope: r?.data_scope || r?.dataScope || r?.scope || r?.data || '',
      }
    }),
  }))

  return {
    app_info: {
      // 应用名由调用方负责解析并传入（通常来自 store.preview.appName）；
      // 这里不再回填占位符，让上层或模板自行决定空值如何展示。
      name: options?.appName || data.appName || '',
      code: options?.appCode || data.appCode || '',
      description: options?.description || '',
    },
    roles: (data.roles || []).map((role: any, idx: number) => ({
      role_code: role?.code || `role_${idx + 1}`,
      role_name: role?.name || role?.code || `角色${idx + 1}`,
      description: role?.description || '',
    })),
    data_dictionary: (data.dicts || []).map((dict: any, idx: number) => ({
      dict_code: dict?.code || `dict_${idx + 1}`,
      dict_name: dict?.name || dict?.code || `字典${idx + 1}`,
      items: (dict?.options || []).map((item: any, itemIdx: number) => ({
        item_code: typeof item === 'string'
          ? `item_${itemIdx + 1}`
          : (item?.code || item?.item_code || `item_${itemIdx + 1}`),
        item_name: typeof item === 'string'
          ? item
          : (item?.name || item?.item_name || `选项${itemIdx + 1}`),
      })),
    })),
    tables: (data.models || []).map((model: any, idx: number) => ({
      table_code: model?.code || `table_${idx + 1}`,
      table_name: model?.name || model?.code || `数据表${idx + 1}`,
      table_type: model?.table_type || '主表',
      parent_model_code: model?.parent_model_code || model?.parentModelCode || '',
      fields: (model?.fields || []).map((field: any, fIdx: number) => ({
        ...(resolveRefMeta(field)),
        field_code: field?.code || `field_${fIdx + 1}`,
        field_name: field?.name || field?.code || `字段${fIdx + 1}`,
        type: field?.type || field?.data_type || '',
        database_field_type: field?.database_field_type || field?.databaseFieldType || field?.db_type || '',
        max_length: field?.max_length || field?.maxLength || field?.length || '',
        length: field?.length || field?.max_length || field?.maxLength || '',
        comment: field?.comment || '',
        dict_code: field?.dict_code || field?.dict || '',
        ref_model_code: resolveRefMeta(field).model || field?.ref_model_code || field?.refModelCode || '',
        ref_display_field_code: resolveRefMeta(field).field || field?.ref_display_field_code || field?.refDisplayFieldCode || '',
      })),
    })),
    forms: (data.forms || []).map((form: any, idx: number) => ({
      form_code: form?.formCode || form?.code || `form_${idx + 1}`,
      form_name: form?.formName || form?.name || `表单${idx + 1}`,
      model_code: form?.modelCode || form?.bindModelCode || `model_${idx + 1}`,
      all_model_codes: form?.allModelCodes || form?.all_model_codes || [],
      components: (form?.components || []).map((component: any, compIdx: number) => {
        const rawComponentType = component?.componentType || component?.component_type || component?.type || ''
        const refMeta = resolveRefMeta(component)
        const associationConfig = component?.formAssociationConfig || component?.form_association_config || {}
        // component 可能只有 modelField="t_xxx.field_code" 没有独立 code 字段
        // （_build_forms_from_models 自动生成的就是这种结构），从 modelField 兜底拆出 code
        const modelFieldStr = String(component?.modelField || component?.model_field || '')
        const modelFieldCode = modelFieldStr.includes('.') ? modelFieldStr.split('.', 2)[1] : ''
        return {
          field_code: component?.code || component?.field_code || component?.fieldCode || modelFieldCode || `field_${compIdx + 1}`,
          field_name: component?.label || component?.name || component?.code || modelFieldCode || `字段${compIdx + 1}`,
          component_type: rawComponentType,
          raw_component_type: rawComponentType,
          section_type: component?.sectionType
            || component?.section_type
            || (rawComponentType === 'FORM_WIDGET_SON_TABLE' ? 'sub' : 'main'),
          model_code: component?.modelCode || component?.model_code || component?.tableModelCode || component?.table_model_code || '',
          table_model_code: component?.tableModelCode || component?.table_model_code || component?.modelCode || component?.model_code || '',
          readonly: !!component?.readonly,
          hidden: !!component?.hidden,
          required: !!component?.required,
          show_in_list: !!(component?.showInList ?? component?.show_in_list),
          searchable: !!(component?.searchable ?? component?.is_searchable),
          dict_code: component?.dict_code || component?.dictCode || component?.dict || '',
          dictCode: component?.dictCode || '',
          selector_form_code:
            component?.selector_form_code
            || component?.selectorFormCode
            || refMeta.model
            || '',
          selector_field_code:
            component?.selector_field_code
            || component?.selectorFieldCode
            || refMeta.field
            || '',
          association_form_code:
            component?.association_form_code
            || component?.associationFormCode
            || associationConfig?.targetModelCode
            || '',
          association_origin_field_code:
            component?.association_origin_field_code
            || component?.associationOriginFieldCode
            || associationConfig?.originFieldCode
            || '',
          association_target_field_code:
            component?.association_target_field_code
            || component?.associationTargetFieldCode
            || associationConfig?.targetFieldCode
            || '',
          ref_model_code: refMeta.model || component?.ref_model_code || component?.refModelCode || '',
          ref_display_field_code: refMeta.field || component?.ref_display_field_code || component?.refDisplayFieldCode || '',
          description: component?.description || component?.comment || '',
        }
      }),
    })),
    role_table_mapping: roleTableMapping,
  }
}

export function standardDocMdToStructuredDoc(markdown: string) {
  if (!markdown.trim()) return null

  const { body, frontmatter } = stripFrontmatter(markdown)
  const sections = splitSections(body)

  const appInfoRows = parseAllTables(getSection(sections, ['应用信息']))[0] || []
  const appInfoKeyValue = appInfoRows.reduce<Record<string, string>>((acc, row) => {
    const key = row['项目'] || ''
    if (key) acc[key] = row['内容'] || ''
    return acc
  }, {})
  const appInfo = {
    ...appInfoRows[0],
    应用名称: appInfoKeyValue['应用名称'] || appInfoRows[0]?.['应用名称'] || '',
    应用编码: appInfoKeyValue['应用编码'] || appInfoRows[0]?.['应用编码'] || '',
    说明: appInfoKeyValue['说明'] || appInfoRows[0]?.['说明'] || '',
  }

  const roles = (parseAllTables(getSection(sections, ['角色列表']))[0] || []).map((row, idx) => ({
    role_code: row['角色编码'] || `role_${idx + 1}`,
    role_name: row['角色名称'] || row['角色编码'] || `角色${idx + 1}`,
  }))
  const roleNameMap = new Map(roles.map(role => [String(role.role_code), role.role_name]))

  const modelsSection = getSection(sections, ['数据模型'])
  const modelSectionTables = parseAllTables(modelsSection)
  const modelMetaRows = modelSectionTables.find(table => table[0] && '模型编码' in table[0] && '模型名称' in table[0] && !('字段编码' in table[0])) || []
  const modelFieldRows = modelSectionTables.find(table => table[0] && '模型编码' in table[0] && '字段编码' in table[0]) || []
  let tables = modelMetaRows.map((row, idx) => ({
    table_code: row['模型编码'] || `table_${idx + 1}`,
    table_name: row['模型名称'] || row['模型编码'] || `数据表${idx + 1}`,
    table_type: '主表',
    fields: [] as Array<Record<string, string>>,
  }))

  if (tables.length && modelFieldRows.length) {
    const fieldsByModelCode = new Map<string, Array<Record<string, string>>>()
    modelFieldRows.forEach((row, fieldIdx) => {
      const modelCode = row['模型编码'] || ''
      const fields = fieldsByModelCode.get(modelCode) || []
      fields.push({
        field_code: row['字段编码'] || `field_${fieldIdx + 1}`,
        field_name: row['字段名称'] || row['字段编码'] || `字段${fieldIdx + 1}`,
        database_field_type: row['数据库字段类型'] || '',
        length: row['长度/精度'] || row['长度'] || '',
        type: row['数据库字段类型'] || '',
        comment: '',
        dict_code: '',
        ref_model_code: '',
        ref_display_field_code: '',
      })
      fieldsByModelCode.set(modelCode, fields)
    })
    tables = tables.map((table) => ({
      ...table,
      fields: fieldsByModelCode.get(table.table_code) || [],
    }))
  } else {
    const modelBlocks = splitSubsections(modelsSection)
    tables = modelBlocks.map((block, idx) => {
      const tableGroups = parseAllTables(block.content)
      const meta = tableGroups[0]?.[0] || {}
      const rows = tableGroups[1] || []
      const tableName = meta['模型名称'] || titleAfterMarker(block.title, '模型：')
      return {
        table_code: meta['模型编码'] || `table_${idx + 1}`,
        table_name: tableName,
        table_type: '主表',
        fields: rows.map((row, fieldIdx) => ({
          field_code: row['字段编码'] || `field_${fieldIdx + 1}`,
          field_name: row['字段名称'] || row['字段编码'] || `字段${fieldIdx + 1}`,
          database_field_type: row['数据库字段类型'] || '',
          length: row['长度/精度'] || row['长度'] || '',
          type: row['数据库字段类型'] || '',
          comment: '',
          dict_code: '',
          ref_model_code: '',
          ref_display_field_code: '',
        })),
      }
    }).filter(table => table.table_name)
  }

  const modelCodeByName = new Map<string, string>()
  tables.forEach((table) => {
    if (table.table_name) modelCodeByName.set(table.table_name, table.table_code)
  })

  const dictBlocks = splitSubsections(getSection(sections, ['数据字典']))
  const dataDictionary = dictBlocks.map((block, idx) => {
    const tableGroups = parseAllTables(block.content)
    const meta = tableGroups[0]?.[0] || {}
    const itemsTable = tableGroups.find(table => table[0] && '选项编码' in table[0]) || []
    const fallbackName = titleAfterMarker(block.title, '').replace(/^[\d.]+\s*/, '')
    return {
      dict_code: meta['字典编码'] || `dict_${idx + 1}`,
      dict_name: meta['字典名称'] || fallbackName,
      items: itemsTable.map((row, itemIdx) => ({
        item_code: row['选项编码'] || `item_${itemIdx + 1}`,
        item_name: row['选项名称'] || row['选项编码'] || `选项${itemIdx + 1}`,
      })),
    }
  }).filter(dict => dict.dict_name)

  const formsSection = getSection(sections, ['表单定义', '表单配置'])
  const formTables = parseAllTables(formsSection)
  const formListRows = formTables.find(table => table[0] && '表单名称' in table[0] && '绑定主表模型' in table[0]) || []
  const mainFieldRows = formTables
    .filter(table => table[0] && '表单名称' in table[0] && '字段编码' in table[0] && !('子表区域名称' in table[0]))
    .flat()
  const subRegionRows = formTables
    .filter(table => table[0] && '表单名称' in table[0] && '子表区域名称' in table[0] && '绑定模型' in table[0])
    .flat()
  const subFieldRows = formTables
    .filter(table => table[0] && '表单名称' in table[0] && '子表区域名称' in table[0] && '字段编码' in table[0])
    .flat()
  const formCodeByName = new Map(formListRows.map(row => [row['表单名称'] || '', row['表单编码'] || '']))

  let forms = formListRows.map((row, idx) => {
    const formName = row['表单名称'] || `表单${idx + 1}`
    const rawModelValue = row['绑定主表模型'] || ''
    const mainModelCode = modelCodeByName.get(rawModelValue) || rawModelValue || `model_${idx + 1}`
    const subRegions = subRegionRows
      .filter(subRow => (subRow['表单名称'] || '') === formName)
      .map((subRow, subIdx) => ({
        name: subRow['子表区域名称'] || `子表${subIdx + 1}`,
        model_code: subRow['绑定模型'] || subRow['子表模型编码'] || `sub_model_${subIdx + 1}`,
      }))
    const subRegionMap = new Map(subRegions.map(region => [region.name, region.model_code]))

    const components = [
      ...mainFieldRows
        .filter(fieldRow => (fieldRow['表单名称'] || '') === formName)
        .map((fieldRow, rowIdx) => {
          return {
            field_code: fieldRow['字段编码'] || `field_${rowIdx + 1}`,
            field_name: fieldRow['字段名称'] || fieldRow['字段编码'] || `字段${rowIdx + 1}`,
            component_type: fieldRow['组件类型'] || '',
            raw_component_type: fieldRow['组件类型'] || '',
            section_type: 'main',
            model_code: mainModelCode,
            required: boolCell(fieldRow['必填'] || fieldRow['是否必填']),
            hidden: boolCell(fieldRow['隐藏'] || fieldRow['是否隐藏']),
            readonly: boolCell(fieldRow['只读'] || fieldRow['是否只读']),
            show_in_list: boolCell(fieldRow['列表展示'] || fieldRow['是否列表展示']),
            searchable: boolCell(fieldRow['查询条件'] || fieldRow['是否查询条件']),
            dict_code: fieldRow['字典编码'] || '',
            selector_form_code: fieldRow['目标模型编码'] || '',
            selector_form_name: '',
            selector_field_code: fieldRow['目标字段编码'] || '',
            selector_field_name: '',
            association_form_code: fieldRow['组件类型'] === '关联表单' ? (fieldRow['目标模型编码'] || '') : '',
            association_form_name: '',
            association_origin_field_code: fieldRow['本表关联字段编码'] || '',
            association_origin_field_name: '',
            association_target_field_code: fieldRow['组件类型'] === '关联表单' ? (fieldRow['目标字段编码'] || '') : '',
            association_target_field_name: '',
            ref_model_code: fieldRow['目标模型编码'] || '',
            ref_display_field_code: fieldRow['目标字段编码'] || '',
            description: fieldRow['说明'] || '',
          }
        }),
      ...subFieldRows
        .filter(fieldRow => (fieldRow['表单名称'] || '') === formName)
        .map((fieldRow, rowIdx) => {
          const subGroupName = fieldRow['子表区域名称'] || ''
          const subModelCode = subRegionMap.get(subGroupName) || `sub_model_${rowIdx + 1}`
          return {
            field_code: fieldRow['字段编码'] || `sub_field_${rowIdx + 1}`,
            field_name: fieldRow['字段名称'] || fieldRow['字段编码'] || `子表字段${rowIdx + 1}`,
            component_type: fieldRow['组件类型'] || '',
            raw_component_type: fieldRow['组件类型'] || '',
            section_type: 'sub',
            model_code: subModelCode,
            table_model_code: subModelCode,
            sub_group_name: subGroupName,
            required: boolCell(fieldRow['必填'] || fieldRow['是否必填']),
            hidden: boolCell(fieldRow['隐藏'] || fieldRow['是否隐藏']),
            readonly: boolCell(fieldRow['只读'] || fieldRow['是否只读']),
            show_in_list: boolCell(fieldRow['列表展示'] || fieldRow['是否列表展示']),
            searchable: boolCell(fieldRow['查询条件'] || fieldRow['是否查询条件']),
            dict_code: fieldRow['字典编码'] || '',
            selector_form_code: fieldRow['目标模型编码'] || '',
            selector_form_name: '',
            selector_field_code: fieldRow['目标字段编码'] || '',
            selector_field_name: '',
            association_form_code: fieldRow['组件类型'] === '关联表单' ? (fieldRow['目标模型编码'] || '') : '',
            association_form_name: '',
            association_origin_field_code: fieldRow['本表关联字段编码'] || '',
            association_origin_field_name: '',
            association_target_field_code: fieldRow['组件类型'] === '关联表单' ? (fieldRow['目标字段编码'] || '') : '',
            association_target_field_name: '',
            ref_model_code: fieldRow['目标模型编码'] || '',
            ref_display_field_code: fieldRow['目标字段编码'] || '',
            description: fieldRow['说明'] || '',
          }
        }),
    ]

    return {
      form_code: formCodeByName.get(formName) || mainModelCode,
      form_name: formName,
      model_code: mainModelCode,
      all_model_codes: [mainModelCode, ...subRegions.map(region => region.model_code).filter((code): code is string => Boolean(code))],
      components,
    }
  }).filter(form => form.form_name)

  if (!forms.length) {
    forms = splitSubsections(formsSection).map((block, idx) => {
      const titleName = titleAfterMarker(block.title, '表单：')
      const allTables = parseAllTables(block.content)
      const meta = allTables.find(table => table[0] && ('表单名称' in table[0] || '绑定主表模型' in table[0]))?.[0] || {}
      const formName = meta['表单名称'] || titleName || `表单${idx + 1}`
      const rawModelValue = meta['绑定主表模型'] || ''
      const mainModelCode = modelCodeByName.get(rawModelValue) || rawModelValue || `model_${idx + 1}`
      const mainRows = allTables.find(table => table[0] && '字段编码' in table[0]) || []
      const subDefRows = allTables.find(table => table[0] && '子表模型编码' in table[0]) || []
      const subFieldTables = allTables.filter(table => table[0] && '子表字段编码' in table[0])

      const subMarkers = block.content
        .split('\n')
        .map(line => line.trim())
        .map((line) => {
          const match = line.match(/^#{4,6}\s+.*?子表[：:]\s*(.+?)\s*$/)
          return match ? normalizeSubtableName(match[1] ?? '') : ''
        })
        .filter(Boolean)

      const subFieldTableByName = new Map<string, TableRow[]>()
      subMarkers.forEach((name, markerIdx) => {
        if (subFieldTables[markerIdx]) subFieldTableByName.set(name, subFieldTables[markerIdx])
      })

      const components = [
        ...mainRows.map((row, rowIdx) => ({
          field_code: row['字段编码'] || `field_${rowIdx + 1}`,
          field_name: row['字段名称'] || row['字段编码'] || `字段${rowIdx + 1}`,
          component_type: row['组件类型'] || '',
          raw_component_type: row['组件类型'] || '',
          section_type: 'main',
          model_code: mainModelCode,
          required: boolCell(row['必填'] || row['是否必填']),
          hidden: boolCell(row['隐藏'] || row['是否隐藏']),
          readonly: boolCell(row['只读'] || row['是否只读']),
          show_in_list: boolCell(row['列表展示'] || row['是否列表展示']),
          searchable: boolCell(row['查询条件'] || row['是否查询条件']),
          dict_code: row['字典编码'] || '',
          ref_model_code: row['目标模型编码'] || '',
          ref_display_field_code: row['目标字段编码'] || '',
          association_origin_field_code: row['本表关联字段编码'] || '',
          description: row['说明'] || '',
        })),
        ...subDefRows.flatMap((subRow, subIdx) => {
          const subModelCode = subRow['子表模型编码'] || `sub_model_${subIdx + 1}`
          const subModelName = subRow['子表显示名称'] || subRow['子表模型名称'] || subModelCode
          const rows = subFieldTableByName.get(normalizeSubtableName(subModelName))
            || subFieldTableByName.get(normalizeSubtableName(subRow['子表模型名称'] || ''))
            || []
          return rows.map((row, rowIdx) => ({
            field_code: row['子表字段编码'] || `sub_field_${rowIdx + 1}`,
            field_name: row['子表字段名称'] || row['子表字段编码'] || `子表字段${rowIdx + 1}`,
            component_type: row['组件类型'] || '',
            raw_component_type: row['组件类型'] || '',
            section_type: 'sub',
            model_code: subModelCode,
            table_model_code: subModelCode,
            sub_group_name: subModelName,
            required: boolCell(row['必填'] || row['是否必填']),
            hidden: boolCell(row['隐藏'] || row['是否隐藏']),
            readonly: boolCell(row['只读'] || row['是否只读']),
            show_in_list: boolCell(row['列表展示'] || row['是否列表展示']),
            searchable: boolCell(row['查询条件'] || row['是否查询条件']),
            dict_code: row['字典编码'] || '',
            ref_model_code: row['目标模型编码'] || '',
            ref_display_field_code: row['目标字段编码'] || '',
            association_origin_field_code: row['本表关联字段编码'] || '',
            description: row['说明'] || '',
          }))
        }),
      ]

      return {
        form_code: mainModelCode,
        form_name: formName,
        model_code: mainModelCode,
        all_model_codes: [mainModelCode, ...subDefRows.map(row => row['子表模型编码']).filter((code): code is string => Boolean(code))],
        components,
      }
    }).filter(form => form.form_name)
  }

  const permissionRows = splitSubsections(getSection(sections, ['权限定义', '权限配置']))
    .flatMap(block => parseAllTables(block.content))
    .find(table => table[0] && '表单名称' in table[0]) || parseAllTables(getSection(sections, ['权限定义', '权限配置']))[0] || []

  const permissionMap = new Map<string, { table_code: string; table_name: string; permissions: Array<any> }>()
  forms.forEach((form) => {
    permissionMap.set(form.form_name, {
      table_code: form.form_code,
      table_name: form.form_name,
      permissions: [],
    })
  })

  permissionRows.forEach((row, idx) => {
    const formName = row['表单名称'] || `表单${idx + 1}`
    const target = permissionMap.get(formName) || {
      table_code: forms.find(form => form.form_name === formName)?.form_code || `table_${idx + 1}`,
      table_name: formName,
      permissions: [],
    }
    const roleCode = row['角色编码'] || `role_${idx + 1}`
    target.permissions.push({
      role_code: roleCode,
      role_name: roleNameMap.get(roleCode) || roleCode,
      operations: buildOperations(row),
      data_scope: row['数据范围'] || '',
    })
    permissionMap.set(formName, target)
  })

  return {
    app_info: {
      name: appInfo['应用名称'] || '',
      code: appInfo['应用编码'] || '',
      description: appInfo['说明'] || frontmatter.description || '',
    },
    roles,
    data_dictionary: dataDictionary,
    tables,
    forms,
    role_table_mapping: Array.from(permissionMap.values()).filter(item => item.permissions.length > 0),
  }
}
