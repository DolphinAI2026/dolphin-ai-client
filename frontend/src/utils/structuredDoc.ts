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

  const normalizeCustomDevItems = (sourceData: any) => {
    const source = sourceData?.custom_development
      || sourceData?.customDevelopment
      || sourceData?.customDevelopments
      || sourceData?.custom_dev
      || sourceData?.customDev
    const rawItems = Array.isArray(source)
      ? source
      : (source?.items || source?.tasks || source?.features || [])
    if (!Array.isArray(rawItems)) return []
    return rawItems
      .map((item: any, index: number) => ({
        type: String(item?.type || item?.scene || item?.category || '自开发扩展').trim(),
        name: String(item?.name || item?.item_name || item?.title || item?.module || `自开发项 ${index + 1}`).trim(),
        trigger: String(item?.trigger || item?.reason || item?.condition || item?.description || '配置能力无法完整覆盖').trim(),
        scope: String(item?.scope || item?.implementation || item?.deliverable || item?.deliverables || '在 IDE 中实现并回写项目上下文').trim(),
        acceptance: String(item?.acceptance || item?.acceptance_criteria || item?.test || '完成源码、联调和可演示验证').trim(),
      }))
      .filter((item: any) => item.name)
  }

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
    flows: (data.workflows || data.flows || []).map((flow: any, idx: number) => ({
      flow_code: flow?.code || flow?.flow_code || flow?.workflowCode || `flow_${idx + 1}`,
      flow_name: flow?.name || flow?.flow_name || flow?.workflowName || `流程${idx + 1}`,
      description: flow?.description || flow?.remark || '',
      steps: (flow?.steps || flow?.nodes || flow?.actions || []).map((step: any, stepIdx: number) => ({
        step: step?.step || step?.order || stepIdx + 1,
        action: step?.action || step?.name || step?.label || '',
        role: step?.role || step?.assignee || '',
        status: step?.status || step?.result || '',
      })),
    })),
    custom_development: normalizeCustomDevItems(data),
  }
}
