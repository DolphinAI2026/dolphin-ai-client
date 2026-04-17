/**
 * 组件类型码 → 中文显示名（前端单一真相源）
 *
 * 对应后端 `app/field_types.py` 中 FIELD_TYPES 的 component_type → display_name
 * 反向表，以及 `app/routes/generation_steps.py::_PLATFORM_LEGACY_COMPONENT_ALIASES`
 * 里列出的平台非规范遗留码。
 *
 * 新增组件类型时后端改 FIELD_TYPES 之后，这里需要手工同步一次
 * （前后端语言不同，暂时没有机制自动镜像）。
 */

/** 规范组件码 → 中文长名显示 */
export const COMPONENT_TYPE_LABELS: Record<string, string> = {
  FORM_DOCUMENT_NUMBER: '单据号',
  FORM_TEXT_INPUT: '单行输入',
  FORM_TEXTAREA_INPUT: '多行输入',
  FORM_PHONE_INPUT: '手机号码',
  FORM_EMAIL_INPUT: '电子邮箱',
  FORM_SELECT_INPUT_SINGLE: '下拉单选',
  FORM_SELECT_INPUT: '下拉多选',
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

/**
 * 平台可能返回的非规范遗留组件码（缺 _INPUT / _SELECT 之类后缀）。
 * 跟后端 generation_steps.py 的 _PLATFORM_LEGACY_COMPONENT_ALIASES 对称。
 */
export const PLATFORM_LEGACY_COMPONENT_ALIASES: Record<string, string> = {
  FORM_TEXTAREA: '多行输入',
  FORM_SELECT: '下拉单选',
  FORM_SELECT_MULTI: '下拉多选',
  FORM_DATE_PICKER: '日期时间',
  FORM_DATE: '日期时间',
  FORM_UPLOAD: '附件上传',
  FORM_SWITCH: '开关',
  FORM_USER_SELECT: '人员选择',
  FORM_DEPT_SELECT: '部门选择',
  FORM_RADIO: '单选框',
  FORM_CHECKBOX: '复选框',
  FORM_LINK: '超链接',
  FORM_ID_CARD: '身份证号',
  FORM_LOCATION: '地理位置',
  FORM_ADDRESS: '地区地址',
  FORM_SERIAL: '单据号',
}

/** 合并后的查表：规范码优先于 legacy 别名 */
const MERGED_LABELS: Record<string, string> = {
  ...PLATFORM_LEGACY_COMPONENT_ALIASES,
  ...COMPONENT_TYPE_LABELS,
}

/**
 * 把组件类型码解析成中文显示名。
 *
 * @param code    组件类型码，可能是空/undefined/null/非规范别名
 * @param fallback 未命中时的兜底文案；不传则返回原始 code（或空）
 */
export function resolveComponentLabel(
  code: string | undefined | null,
  fallback?: string,
): string {
  const raw = String(code || '').trim()
  if (!raw) return fallback ?? ''
  return MERGED_LABELS[raw] ?? fallback ?? raw
}
