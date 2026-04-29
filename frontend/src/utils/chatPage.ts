/**
 * ChatPage.vue 抽出的纯工具函数（doc 导出 / 消息识别 / 冲突编码推荐）。
 * 无 Vue/reactive/store 依赖。
 */
import { resolveComponentLabel } from '@/utils/componentTypes'
import { APP_CODE_MAX_LENGTH, normalizeAppCode } from '@/utils/app'

// ── 文档解析元数据 ─────────────────────────────────────
export function formatParseMetaSummary(meta: any): string {
  const score = Number(meta?.standard_score ?? meta?.score)
  if (!Number.isFinite(score)) return ''
  return `文档标准度：${score} 分`
}

// ── 设计文档导出 ─────────────────────────────────────
export function docExportComponentTypeLabel(value: any, modelType?: any): string {
  const raw = String(value || '').trim()
  const modelLabel = String(modelType || '').trim()
  const label = resolveComponentLabel(raw, '') || raw || modelLabel || '-'
  // 业务规则：如果组件类型退回到默认"单行输入"但模型层声明的类型更具体，
  // 以模型声明为准（导出 md 时更贴合原意）
  if (label === '单行输入' && modelLabel && modelLabel !== '单行输入') return modelLabel
  return label
}

export function docExportFieldCode(modelField: any): string {
  const raw = String(modelField || '').trim()
  return raw.includes('.') ? raw.split('.').pop() || '' : raw
}

export function docExportBool(value: any): string {
  return value ? '是' : '否'
}

export function isSubTableComponent(component: any): boolean {
  return String(component?.componentType || component?.component_type || '').trim() === 'FORM_WIDGET_SON_TABLE'
}

export function docExportModelMaps(models: any[]): {
  modelsByCode: Map<string, any>
  fieldsByModel: Map<string, Map<string, any>>
} {
  const modelsByCode = new Map<string, any>()
  const fieldsByModel = new Map<string, Map<string, any>>()
  ;(models || []).forEach((model: any) => {
    const modelCode = String(model?.code || '')
    if (!modelCode) return
    modelsByCode.set(modelCode, model)
    const fieldMap = new Map<string, any>()
    ;(model?.fields || []).forEach((field: any) => {
      const fieldCode = String(field?.code || '')
      if (fieldCode) fieldMap.set(fieldCode, field)
    })
    fieldsByModel.set(modelCode, fieldMap)
  })
  return { modelsByCode, fieldsByModel }
}

// ── 消息识别 ────────────────────────────────────────
export function isAutoDocSummaryMessage(content: string): boolean {
  const text = String(content || '').trim()
  if (!text) return false
  if (!text.startsWith('我已经理解了设计文档《')) return false
  return text.includes('识别出：')
    && (text.includes('你可以告诉我需要调整的地方')
      || text.includes('或者直接说"开始生成"')
      || text.includes('或者直接点击"开始生成"'))
}

// ── 冲突编码推荐 ──────────────────────────────────────
/** 编码冲突时建议下一个可用编码：code-v1 → code-v2；无版本号则补 -v1。 */
export function suggestNextConflictCode(code: string): string {
  const source = normalizeAppCode(String(code || '').trim()) || 'code'
  const matched = source.match(/^(.*?)-v(\d+)$/)
  if (matched) {
    const prefix = matched[1] || source
    const version = Number(matched[2] || '0')
    const suffix = `-v${version + 1}`
    return `${prefix.slice(0, APP_CODE_MAX_LENGTH - suffix.length).replace(/-+$/g, '')}${suffix}`
  }
  const suffix = '-v1'
  return `${source.slice(0, APP_CODE_MAX_LENGTH - suffix.length).replace(/-+$/g, '')}${suffix}`
}
