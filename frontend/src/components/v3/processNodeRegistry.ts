/**
 * processNodeRegistry.ts — Phase C 24 节点注册表.
 *
 * 2026-05-26 design-v4 Phase C: 流程设计器 24 节点定义 (4 分类 × 4-5 种).
 *
 * 给 ProcessDesignerPanel + ProcessNodePropsPanel 共享:
 *   - 左 sidebar collapsible 分类按 NODE_CATEGORIES 渲染
 *   - 中央 canvas buildNodeSpec 按 type 选 shape/color
 *   - 右 PropsPanel 按 type 选不同 props block
 */

export type NodeCategoryCode = 'entry' | 'approval' | 'logic' | 'action'

export type NodeType =
  // entry
  | 'start' | 'end' | 'timer' | 'webhook'
  // approval
  | 'assignee_approval' | 'role_approval' | 'manager_approval' | 'parallel_approval' | 'cc'
  // logic
  | 'condition' | 'multi_branch' | 'parallel_gateway' | 'merge' | 'wait'
  // action
  | 'fill_form' | 'write_data' | 'read_data' | 'ai_judge' | 'ai_generate'

export interface NodeDef {
  type: NodeType
  label: string
  icon: string
  /** 仅 entry 节点显式定义 color, 其他用 category 默认色. */
  color?: string
}

export interface NodeCategory {
  code: NodeCategoryCode
  label: string
  /** Category 默认色 — buildNodeSpec 兜底用 (entry node 自己有 color override). */
  color: string
  nodes: NodeDef[]
}

/** ────────────────────────────────────────────────────────────
 *  4 分类 × 24 节点
 *  注: hex 值是 x6 内部 attrs 需要的原始值 (不走 CSS token),
 *  这是 SPEC 144-178 行 NODE_CATEGORIES 的原貌, 跟设计语言冲突的
 *  例外 case (token 在 .vue scoped style 里都用 var(--xxx)).
 * ────────────────────────────────────────────────────────────*/
export const NODE_CATEGORIES: NodeCategory[] = [
  {
    code: 'entry',
    label: '入口/出口',
    color: '#10b981',
    nodes: [
      { type: 'start',   label: '开始',       icon: '⏻', color: '#10b981' },
      { type: 'end',     label: '结束',       icon: '⊗', color: '#dc2626' },
      { type: 'timer',   label: '定时触发',   icon: '⏰' },
      { type: 'webhook', label: 'Webhook',    icon: '🔗' },
    ],
  },
  {
    code: 'approval',
    label: '审批',
    color: '#2563eb',
    nodes: [
      { type: 'assignee_approval', label: '指定人审批', icon: '👤' },
      { type: 'role_approval',     label: '角色审批',   icon: '👥' },
      { type: 'manager_approval',  label: '上级审批',   icon: '👔' },
      { type: 'parallel_approval', label: '会签 / 或签', icon: '🤝' },
      { type: 'cc',                label: '抄送',       icon: '📢' },
    ],
  },
  {
    code: 'logic',
    label: '逻辑',
    color: '#f59e0b',
    nodes: [
      { type: 'condition',        label: '条件分支',  icon: '⊻' },
      { type: 'multi_branch',     label: '多分支',    icon: '⋔' },
      { type: 'parallel_gateway', label: '并行网关',  icon: '∥' },
      { type: 'merge',            label: '汇聚',      icon: '⋎' },
      { type: 'wait',             label: '等待',      icon: '⏳' },
    ],
  },
  {
    code: 'action',
    label: '动作',
    color: '#7c3aed',
    nodes: [
      { type: 'fill_form',   label: '填写表单',   icon: '📝' },
      { type: 'write_data',  label: '写入数据表', icon: '💾' },
      { type: 'read_data',   label: '读取数据',   icon: '📖' },
      { type: 'ai_judge',    label: 'AI 判定',    icon: '✨' },
      { type: 'ai_generate', label: 'AI 生成',    icon: '🪄' },
    ],
  },
]

/** ProcessNode — 编辑层 model. 不严格按 BPMN, 只为 UI/state 用. */
export interface ProcessBranch {
  condition: string
  targetNodeKey: string
}

export interface ProcessFieldMapping {
  targetField: string
  sourceExpr: string
}

export interface ProcessNode {
  id: string
  type: NodeType
  label: string
  key: string
  x?: number
  y?: number

  // approval
  approvers?: string[]
  strategy?: 'single' | 'any' | 'all' | 'majority'
  slaHours?: number
  timeoutAutoApprove?: boolean
  allowAddApprover?: boolean
  allowReject?: boolean

  // condition / multi_branch
  expression?: string
  branches?: ProcessBranch[]

  // wait
  waitMinutes?: number

  // write_data
  targetModelCode?: string
  fieldMappings?: ProcessFieldMapping[]

  // read_data
  sourceModelCode?: string
  filterExpression?: string
  outputVar?: string

  // timer / webhook
  cron?: string
  description?: string

  // fill_form
  formCode?: string
  assignee?: string

  // ai_judge / ai_generate
  prompt?: string
  model?: string
}

/** Quick lookup: type → NodeDef. */
const NODE_DEF_INDEX: Record<string, NodeDef> = (() => {
  const idx: Record<string, NodeDef> = {}
  for (const cat of NODE_CATEGORIES) {
    for (const n of cat.nodes) {
      idx[n.type] = n
    }
  }
  return idx
})()

/** Quick lookup: type → category code. */
const CAT_INDEX: Record<string, NodeCategoryCode> = (() => {
  const idx: Record<string, NodeCategoryCode> = {}
  for (const cat of NODE_CATEGORIES) {
    for (const n of cat.nodes) {
      idx[n.type] = cat.code
    }
  }
  return idx
})()

export function getNodeDef(type: string): NodeDef | undefined {
  return NODE_DEF_INDEX[type]
}

export function getNodeCategoryCode(type: string): NodeCategoryCode | undefined {
  return CAT_INDEX[type]
}

export function getCategoryColor(code: NodeCategoryCode): string {
  return NODE_CATEGORIES.find(c => c.code === code)?.color || '#64748b'
}

/** 给定 type, 返回默认显示色 (优先 node.color, 兜底 category.color). */
export function getNodeColor(type: string): string {
  const def = getNodeDef(type)
  if (def?.color) return def.color
  const cat = getNodeCategoryCode(type)
  if (cat) return getCategoryColor(cat)
  return '#64748b'
}
