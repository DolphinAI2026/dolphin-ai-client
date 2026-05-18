// frontend/src/views/chat/blueprint-adapter.ts
//
// Maps the loose ChatPage SPEC data (store.preview.{models, forms, flows,
// roles, dicts}, plus the normalized businessFlowItems / formPreviewItems
// computeds) into the strict prop shape that AppBlueprintPanel expects.
//
// Pure data transformations — no Vue reactivity dependencies.

export interface BPField { name: string; code: string; type: string; required?: boolean; unique?: boolean; isNew?: boolean }
export interface BPModel { name: string; code: string; fields: BPField[] }
export interface BPFormSection { title: string; fields: string[] }
export interface BPForm { name: string; backingModel: string; sections: BPFormSection[] }
export interface BPFlowNode { role: string; action: string; sla?: string }
export interface BPFlow { name: string; trigger: string; nodes: BPFlowNode[] }
export interface BPRole { name: string; scope: string }
export interface BPDictEntry { code: string; label: string }
export interface BPDict { name: string; entries: BPDictEntry[] }

export interface BPBlueprint {
  models: BPModel[]
  forms: BPForm[]
  flows: BPFlow[]
  roles: BPRole[]
  dicts: BPDict[]
}

function str(v: unknown, fallback = ''): string {
  if (v == null) return fallback
  return String(v).trim() || fallback
}

export function mapModels(rawModels: any[]): BPModel[] {
  if (!Array.isArray(rawModels)) return []
  return rawModels.map((m: any, idx: number) => {
    const name = str(m?.name, `模型${idx + 1}`)
    const code = str(m?.code, `model_${idx + 1}`)
    const rawFields = Array.isArray(m?.fields) ? m.fields : []
    const fields: BPField[] = rawFields.map((f: any, fi: number) => ({
      name: str(f?.name, `字段${fi + 1}`),
      code: str(f?.code, `field_${fi + 1}`),
      type: str(f?.type, '文本'),
      required: Boolean(f?.required),
      unique: Boolean(f?.unique),
      isNew: Boolean(f?.isNew || f?.is_new),
    }))
    return { name, code, fields }
  })
}

export function mapForms(rawForms: any[], rawModels: any[]): BPForm[] {
  if (Array.isArray(rawForms) && rawForms.length > 0) {
    return rawForms.map((form: any, idx: number) => {
      const components = Array.isArray(form?.components) ? form.components : []
      const fieldsList = components
        .map((c: any) => str(c?.label) || str(c?.name) || str(c?.code) || str(c?.modelField) || '')
        .filter(Boolean)
      const sections: BPFormSection[] = fieldsList.length
        ? [{ title: '主表字段', fields: fieldsList }]
        : []
      return {
        name: str(form?.formName) || str(form?.name) || `表单${idx + 1}`,
        backingModel: str(form?.modelName) || str(form?.bindModelName) || str(form?.modelCode) || str(form?.bindModelCode) || '',
        sections,
      }
    })
  }
  // Fallback: derive a form per non-sub model (matches ChatPage formPreviewItems
  // behavior so the panel is never empty when models are present).
  if (Array.isArray(rawModels) && rawModels.length > 0) {
    return rawModels
      .filter((m: any) => !/sub|child|子表/.test(String(m?.table_type || m?.type || '').toLowerCase()))
      .map((m: any, idx: number) => {
        const fieldsList = Array.isArray(m?.fields)
          ? m.fields.map((f: any) => str(f?.name) || str(f?.code)).filter(Boolean)
          : []
        return {
          name: str(m?.form_name) || str(m?.name) || `表单${idx + 1}`,
          backingModel: str(m?.code, `model_${idx + 1}`),
          sections: fieldsList.length ? [{ title: '主表字段', fields: fieldsList }] : [],
        }
      })
  }
  return []
}

export function mapFlows(rawFlows: any[]): BPFlow[] {
  if (!Array.isArray(rawFlows)) return []
  return rawFlows
    .map((flow: any, idx: number): BPFlow | null => {
      const name = str(flow?.name) || str(flow?.flowName) || `流程${idx + 1}`
      const trigger = str(flow?.trigger) || str(flow?.triggerEvent) || str(flow?.event) || ''
      const rawNodes = Array.isArray(flow?.nodes) ? flow.nodes : Array.isArray(flow?.steps) ? flow.steps : []
      const nodes: BPFlowNode[] = rawNodes.map((n: any) => ({
        role: str(n?.role) || str(n?.assignee) || '',
        action: str(n?.action) || str(n?.name) || str(n?.type) || '',
        sla: str(n?.sla) || str(n?.deadline) || undefined,
      })).filter((n: BPFlowNode) => n.role || n.action)
      if (!nodes.length && !name) return null
      return { name, trigger, nodes }
    })
    .filter(Boolean) as BPFlow[]
}

export function mapRoles(rawRoles: any[]): BPRole[] {
  if (!Array.isArray(rawRoles)) return []
  return rawRoles.map((r: any, idx: number) => ({
    name: str(r?.name, `角色${idx + 1}`),
    scope: str(r?.scope) || str(r?.description) || str(r?.code) || '',
  }))
}

export function mapDicts(rawDicts: any[]): BPDict[] {
  if (!Array.isArray(rawDicts)) return []
  return rawDicts.map((d: any, idx: number) => {
    const rawOptions = Array.isArray(d?.options) ? d.options : Array.isArray(d?.entries) ? d.entries : []
    const entries: BPDictEntry[] = rawOptions.map((opt: any, oi: number) => {
      if (typeof opt === 'string') {
        return { code: `opt_${oi + 1}`, label: opt }
      }
      return {
        code: str(opt?.code, `opt_${oi + 1}`),
        label: str(opt?.label) || str(opt?.name) || str(opt?.code) || `选项${oi + 1}`,
      }
    })
    return {
      name: str(d?.name, `字典${idx + 1}`),
      entries,
    }
  })
}

/**
 * Convert preview slices (whatever the existing parser/SSE puts on
 * store.preview) into the strict AppBlueprintPanel prop shape.
 */
export function buildBlueprintSpec(preview: {
  models?: any[]
  forms?: any[]
  flows?: any[]
  workflows?: any[]
  roles?: any[]
  dicts?: any[]
}): BPBlueprint {
  const rawModels = preview?.models || []
  const rawFlows = preview?.flows && preview.flows.length ? preview.flows : (preview?.workflows || [])
  return {
    models: mapModels(rawModels),
    forms: mapForms(preview?.forms || [], rawModels),
    flows: mapFlows(rawFlows),
    roles: mapRoles(preview?.roles || []),
    dicts: mapDicts(preview?.dicts || []),
  }
}
