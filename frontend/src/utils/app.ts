/**
 * 应用名 / 应用编码相关的纯工具函数。
 *
 * 都是零副作用、不依赖 store/ref 的纯函数，从 ChatPage.vue 抽出。
 * 任何组件需要做"应用名提取"或"从中文名推编码"时直接 import 即可。
 */

export const APP_CODE_MAX_LENGTH = 17
export const APP_CODE_PATTERN = /^[a-z][a-z0-9-]{0,16}$/
export const APP_CODE_RULE_TEXT = '应用编码只能输入小写字母、中划线和数字；必须以小写字母开头；最多 17 个字符。'

export function isValidAppCode(code: string): boolean {
  return APP_CODE_PATTERN.test(String(code || '').trim())
}

export function normalizeAppCode(candidate: string): string {
  let code = String(candidate || '')
    .trim()
    .toLowerCase()
    .replace(/[_\s]+/g, '-')
    .replace(/[^a-z0-9-]/g, '')
    .replace(/-+/g, '-')
    .replace(/^-+|-+$/g, '')

  if (!code) return ''
  if (!/^[a-z]/.test(code)) code = `app-${code}`
  code = code.slice(0, APP_CODE_MAX_LENGTH).replace(/-+$/g, '')
  return isValidAppCode(code) ? code : ''
}

/**
 * 从可能有多种字段名变体的 data 对象中抽取应用编码。
 * 支持顺序：appCode > app_code > app_info.code > appInfo.code。
 */
export function pickAppCode(data: any): string {
  return (
    data?.appCode ||
    data?.app_code ||
    data?.app_info?.code ||
    data?.appInfo?.code ||
    ''
  )
}

/**
 * 从可能有多种字段名变体的 data 对象中抽取应用名称。
 * 支持顺序：appName > app_name > app_info.name > appInfo.name。
 */
export function pickAppName(data: any): string {
  return (
    data?.appName ||
    data?.app_name ||
    data?.app_info?.name ||
    data?.appInfo?.name ||
    ''
  )
}

/**
 * 从 markdown 文档正文推断应用编码。
 * 识别"应用编码：XXX"、表格行"| 应用编码 | XXX |"、JSON 里 "code":"XXX" 等常见写法。
 */
export function extractAppCodeFromText(text: string): string {
  if (!text) return ''
  const patterns = [
    /应用编码[：:\s`]*([A-Za-z][A-Za-z0-9_-]{0,63})/i,
    /app[_\s-]?code[：:\s`]*([A-Za-z][A-Za-z0-9_-]{0,63})/i,
    /\|\s*应用编码\s*\|\s*`?([A-Za-z][A-Za-z0-9_-]{0,63})`?\s*\|/i,
    /\|\s*App\s*Code\s*\|\s*`?([A-Za-z][A-Za-z0-9_-]{0,63})`?\s*\|/i,
    /"code"\s*:\s*"([A-Za-z][A-Za-z0-9_-]{0,63})"/i,
  ]
  for (const p of patterns) {
    const m = text.match(p)
    if (m?.[1]) return normalizeAppCode(m[1])
  }
  return ''
}

/**
 * 从 markdown 文档头部推断应用名称。
 * 用于文档刚上传、后端 AI 兜底还没跑完时前端立即占位显示；
 * 后端权威值返回后会通过 store.setAppName 覆盖（setter 自带默认占位过滤）。
 *
 * 跳过文档模板里常见的占位字样（"未命名应用" / "业务应用" / "应用" / "应用设计文档"）。
 */
export function extractAppNameFromText(text: string): string {
  if (!text) return ''
  const DEFAULTS = new Set(['', '未命名应用', '业务应用', '应用', '应用设计文档'])
  const patterns = [
    /\|\s*应用名称\s*\|\s*`?([^|\n`]+?)`?\s*\|/i,  // 标准表格行
    /应用名称[：:\s`]*([^\n`|]+)/i,                // "应用名称: xxx" 散文
    /^#\s+([^\n#]+)$/m,                            // 一级标题兜底
  ]
  for (const p of patterns) {
    const m = text.match(p)
    const v = String(m?.[1] || '').trim()
    if (v && !DEFAULTS.has(v)) return v
  }
  return ''
}

/**
 * 从中文应用名推断出一个合法的低代码应用编码（kebab 风格）。
 *
 * 策略（从严到宽）：
 *   1. 匹配常见完整系统名（"档案管理系统" → "archive-mgmt"）
 *   2. 按业务关键词分词拼接（"客户合同" → "customer-contract"）
 *   3. 如果含英文/数字/分隔符，规范化后直接用
 *   4. 兜底 "app-builder"
 */
export function buildAppCode(name: string): string {
  const source = (name || '').trim()
  if (!source) return 'app-builder'

  const phraseMap: Array<[RegExp, string]> = [
    [/档案管理系统|档案管理平台/g, 'archive-mgmt'],
    [/客户管理系统|客户管理平台/g, 'customer-mgmt'],
    [/报销管理系统|报销管理平台/g, 'expense-mgmt'],
    [/请假管理系统|请假管理平台/g, 'leave-mgmt'],
    [/合同管理系统|合同管理平台/g, 'contract-mgmt'],
    [/项目管理系统|项目管理平台/g, 'project-mgmt'],
    [/采购管理系统|采购管理平台/g, 'purchase-mgmt'],
    [/库存管理系统|库存管理平台/g, 'inventory-mgmt'],
    [/员工管理系统|人事管理系统/g, 'employee-mgmt'],
    [/人才管理系统|人才管理平台/g, 'talent-mgmt'],
    [/工单管理系统|售后工单系统/g, 'ticket-mgmt'],
  ]
  for (const [pattern, code] of phraseMap) {
    if (pattern.test(source)) return normalizeAppCode(code) || 'app-builder'
  }

  const tokenMap: Array<[RegExp, string]> = [
    [/档案/g, 'archive'],
    [/文档/g, 'document'],
    [/知识库/g, 'knowledge'],
    [/客户/g, 'customer'],
    [/用户/g, 'user'],
    [/会员/g, 'member'],
    [/员工|人事/g, 'employee'],
    [/人才/g, 'talent'],
    [/部门/g, 'department'],
    [/报销|费用/g, 'expense'],
    [/请假|休假/g, 'leave'],
    [/考勤/g, 'attendance'],
    [/合同/g, 'contract'],
    [/采购/g, 'purchase'],
    [/库存/g, 'inventory'],
    [/商品/g, 'product'],
    [/订单/g, 'order'],
    [/销售/g, 'sales'],
    [/项目/g, 'project'],
    [/任务/g, 'task'],
    [/审批/g, 'approval'],
    [/流程/g, 'workflow'],
    [/工单|售后/g, 'ticket'],
    [/设备|资产/g, 'asset'],
    [/财务/g, 'finance'],
    [/管理|平台|系统/g, 'mgmt'],
  ]

  const parts: string[] = []
  for (const [pattern, token] of tokenMap) {
    if (pattern.test(source) && !parts.includes(token)) {
      parts.push(token)
    }
  }

  if (parts.length > 0) {
    const code = parts.slice(0, 3).join('-').replace(/-mgmt-mgmt$/, '-mgmt')
    return normalizeAppCode(code.startsWith('mgmt') ? `app-${code}` : code) || 'app-builder'
  }

  return normalizeAppCode(source) || 'app-builder'
}
