export type DemoAppStatus = 'active' | 'deployed' | 'draft'

export interface DemoApp {
  id: string
  icon: string
  name: string
  phase: string
  progress: number
  updated: string
  status: DemoAppStatus
  color: string
}

export const demoApps: DemoApp[] = [
  {
    id: 'inspection-ops',
    icon: 'I',
    name: '设备巡检管理',
    phase: 'SPEC 设计',
    progress: 42,
    updated: '3 分钟前',
    status: 'active',
    color: '#4f6ef7',
  },
  {
    id: 'crm-lite',
    icon: 'C',
    name: '客户跟进 CRM',
    phase: '配置生成',
    progress: 76,
    updated: '1 小时前',
    status: 'active',
    color: '#0f9f8f',
  },
  {
    id: 'asset-ledger',
    icon: 'A',
    name: '资产台账',
    phase: '部署',
    progress: 100,
    updated: '昨天',
    status: 'deployed',
    color: '#b7791f',
  },
  {
    id: 'ticket-dispatch',
    icon: 'S',
    name: '工单调度平台',
    phase: '自开发',
    progress: 62,
    updated: '昨天',
    status: 'active',
    color: '#7c3aed',
  },
  {
    id: 'contract-review',
    icon: 'R',
    name: '合同评审',
    phase: '需求理解',
    progress: 18,
    updated: '3 天前',
    status: 'draft',
    color: '#d14a61',
  },
]

export const demoModels = [
  { name: 'Device', label: '设备台账', fields: 12, forms: 2, status: '已确认' },
  { name: 'InspectionRecord', label: '巡检记录', fields: 18, forms: 1, status: '待决策' },
  { name: 'WorkOrder', label: '异常工单', fields: 15, forms: 1, status: '草稿' },
]

export const demoForms = [
  { name: '设备登记表', model: 'Device', layout: 'PC + 移动端', fields: 12, status: '已生成' },
  { name: '巡检执行表', model: 'InspectionRecord', layout: '移动端优先', fields: 18, status: '待确认' },
  { name: '异常工单表', model: 'WorkOrder', layout: 'PC 工作台', fields: 15, status: '草稿' },
  { name: '巡检统计页', model: 'InspectionRecord', layout: '仪表盘', fields: 8, status: '规划中' },
]

export const demoPipelines = [
  { name: 'inspection · deploy', app: '设备巡检管理', branch: 'feat/inspection-v3', status: '运行中', success: '96%', time: '12 分钟前' },
  { name: 'crm · full-pipeline', app: '客户跟进 CRM', branch: 'main', status: '通过', success: '94%', time: '1 小时前' },
  { name: 'asset · deploy', app: '资产台账', branch: 'main', status: '通过', success: '98%', time: '昨天' },
  { name: 'workorder · deploy', app: '工单调度平台', branch: 'release/2.4', status: '失败', success: '89%', time: '2 小时前' },
]

export const demoEnvironments = [
  { key: 'dev', name: '开发', version: 'v0.3.2', status: 'healthy', apps: 12 },
  { key: 'test', name: '测试', version: 'v0.3.2', status: 'healthy', apps: 10 },
  { key: 'staging', name: '预发', version: 'v0.3.1', status: 'approval', apps: 8 },
  { key: 'prod', name: '生产', version: 'v0.3.0', status: 'healthy', apps: 6 },
]

export const demoModelConfigs = [
  { provider: 'Anthropic', model: 'claude-sonnet-4.5', usage: '搭建 / 复杂开发', tokens: '142K', status: '正常' },
  { provider: 'OpenAI', model: 'gpt-4o', usage: '辅助开发', tokens: '38K', status: '正常' },
  { provider: 'DeepSeek', model: 'deepseek-chat', usage: '需求理解', tokens: '22K', status: '正常' },
  { provider: '自建', model: 'llama-3-70b · 内网', usage: '离线站点', tokens: '-', status: '未启用' },
]
