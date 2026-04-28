import type { AnalysisResult } from '@/api/requirements'

export interface UnifiedAiBuilderInput {
  businessInput: string
  codingFocus?: string
  uploadedFileName?: string
}

const DEFAULT_SCENE = 'page-pc'

function cleanLines(input: string): string[] {
  return input
    .split(/\r?\n/)
    .map(line => line.replace(/^[-*•\d.\s]+/, '').trim())
    .filter(Boolean)
}

function joinLineSummary(lines: string[], fallback = '暂无补充说明'): string {
  if (lines.length === 0) return fallback
  if (lines.length === 1) return lines[0] as string
  return lines.map(line => `- ${line}`).join('\n')
}

function pickRoleNames(docResult: AnalysisResult): string[] {
  return (docResult.roles || [])
    .map(role => role.role_name?.trim())
    .filter((value): value is string => Boolean(value))
}

function pickTableNames(docResult: AnalysisResult): string[] {
  return (docResult.tables || [])
    .map(table => table.table_name?.trim())
    .filter((value): value is string => Boolean(value))
}

function pickFlowNames(docResult: AnalysisResult): string[] {
  return (docResult.flows || [])
    .map(flow => flow.flow_name?.trim())
    .filter((value): value is string => Boolean(value))
}

function pickModuleFeatures(docResult: AnalysisResult): string[] {
  return (docResult.modules || [])
    .flatMap(module => module.features || [])
    .map(feature => feature.name?.trim())
    .filter((value): value is string => Boolean(value))
}

export function buildUnifiedKickoffMessage(input: UnifiedAiBuilderInput): string {
  const blocks: string[] = []
  const businessText = input.businessInput.trim()
  const codingText = (input.codingFocus || '').trim()

  if (businessText) {
    blocks.push(`业务需求说明：\n${businessText}`)
  }

  if (codingText) {
    blocks.push(
      '补充说明：以下内容既要用于智能搭建的设计文档整理，也要作为后续智能开发的输入边界，请一起吸收：\n'
      + codingText,
    )
  }

  if (input.uploadedFileName) {
    blocks.push(`本次还上传了需求附件：${input.uploadedFileName}。请先完整吸收附件内容，再整理成统一方案。`)
  }

  blocks.push('请先整理一版统一的需求摘要，后续我会继续自动生成标准设计文档，并拆出智能开发输入。')
  return blocks.join('\n\n')
}

export function inferCodingSceneCategory(docResult: AnalysisResult, codingFocus = ''): string {
  const raw = [
    codingFocus,
    ...pickFlowNames(docResult),
    ...pickModuleFeatures(docResult),
    ...pickTableNames(docResult),
  ].join('\n')

  if (/(接口|API|后端|集成|同步|Webhook|定时|任务|脚本|服务)/i.test(raw)) {
    return 'backend'
  }
  if (/(移动|mobile|H5|小程序)/i.test(raw) && /(组件|控件|选择器|上传|图表|卡片)/i.test(raw)) {
    return 'component-mobile'
  }
  if (/(移动|mobile|H5|小程序)/i.test(raw)) {
    return 'page-mobile'
  }
  if (/(组件|控件|上传|图表|选择器|日历|看板卡片|自定义字段组件)/i.test(raw)) {
    return 'component-pc'
  }
  return DEFAULT_SCENE
}

export function buildBuilderMarkdownFilename(docResult: AnalysisResult): string {
  const appName = docResult.app_info?.name?.trim() || 'AIBuilder'
  return `${appName}-智能搭建设计文档.md`
}

export function buildCodingBriefFilename(docResult: AnalysisResult): string {
  const appName = docResult.app_info?.name?.trim() || 'AIBuilder'
  return `${appName}-智能开发任务简报.md`
}

function inferAppName(input: UnifiedAiBuilderInput): string {
  const source = `${input.businessInput}\n${input.codingFocus || ''}`.trim()
  const exactMatch = source.match(/([^\n，。；：]{2,24}(系统|平台|应用))/)
  if (exactMatch?.[1]) {
    return exactMatch[1]
  }
  if (/请假|休假|年假/.test(source)) return '请假审批系统'
  if (/报销|费用/.test(source)) return '费用报销系统'
  if (/采购|供应商/.test(source)) return '采购管理系统'
  return input.uploadedFileName ? input.uploadedFileName.replace(/\.[^.]+$/, '') : '业务管理系统'
}

function inferAppCode(appName: string): string {
  const normalized = appName
    .toUpperCase()
    .replace(/[^A-Z0-9]/g, '')
    .slice(0, 8)
  return `APP_${normalized || 'DEMO'}`
}

function inferEntityName(input: UnifiedAiBuilderInput): string {
  const source = `${input.businessInput}\n${input.codingFocus || ''}`
  if (/请假|休假|年假/.test(source)) return '请假申请'
  if (/报销|费用/.test(source)) return '报销申请'
  if (/采购|供应商/.test(source)) return '采购申请'
  return '业务申请'
}

export function buildFallbackSummary(input: UnifiedAiBuilderInput): string {
  const appName = inferAppName(input)
  const entityName = inferEntityName(input)
  return [
    '当前租户的需求分析模型暂时不可用，已切换为本地兜底模式。',
    '',
    `- 已根据输入整理出一版基础应用骨架：**${appName}**`,
    `- 智能搭建侧会先围绕 **${entityName}** 的角色、数据表、流程和权限矩阵生成标准设计文档`,
    '- 智能开发侧会继续消费同一份设计文档，并结合你填写的自开发关注点生成任务简报',
    '- 建议后续在模型恢复后，再对这份基础文档做一轮精修',
  ].join('\n')
}

export function buildFallbackDocResult(input: UnifiedAiBuilderInput): AnalysisResult {
  const appName = inferAppName(input)
  const entityName = inferEntityName(input)
  const entityCode = entityName.replace(/申请$/, '') || '业务'
  const tableCode = /请假|休假|年假/.test(entityName) ? 't_leave_request' : 't_business_request'
  const moduleName = entityName.replace(/申请$/, '') + '管理'
  const codingFocusLines = cleanLines(input.codingFocus || '')

  return {
    app_info: {
      code: inferAppCode(appName),
      name: appName,
      description: `${appName}的基础兜底设计文档，建议在模型恢复后继续补充细节。`,
    },
    roles: [
      {
        role_code: 'dept_manager',
        role_name: '部门经理',
        description: '负责审批和查看本部门业务申请',
      },
      {
        role_code: 'hr_specialist',
        role_name: 'HR专员',
        description: '负责查看统计、维护规则和全局台账',
      },
    ],
    data_dictionary: [
      {
        dict_code: 'request_status',
        dict_name: '申请状态',
        items: [
          { item_code: 'DRAFT', item_name: '草稿' },
          { item_code: 'PENDING', item_name: '待审批' },
          { item_code: 'APPROVED', item_name: '已通过' },
          { item_code: 'REJECTED', item_name: '已拒绝' },
        ],
      },
    ],
    tables: [
      {
        table_code: tableCode,
        table_name: entityName,
        table_type: '主表',
        parent_table: '',
        description: `${entityName}主数据，记录申请主体、时间范围、原因和当前状态。`,
        fields: [
          {
            field_code: 'request_no',
            field_name: '申请单号',
            data_type: 'VARCHAR',
            length: '64',
            is_pk: false,
            is_fk: false,
            nullable: false,
            default_value: '',
            description: '业务申请编号',
          },
          {
            field_code: 'applicant_name',
            field_name: '申请人',
            data_type: 'VARCHAR',
            length: '64',
            is_pk: false,
            is_fk: false,
            nullable: false,
            default_value: '',
            description: '发起申请的员工姓名',
          },
          {
            field_code: 'start_date',
            field_name: '开始日期',
            data_type: 'DATE',
            length: '',
            is_pk: false,
            is_fk: false,
            nullable: false,
            default_value: '',
            description: '业务开始时间',
          },
          {
            field_code: 'end_date',
            field_name: '结束日期',
            data_type: 'DATE',
            length: '',
            is_pk: false,
            is_fk: false,
            nullable: false,
            default_value: '',
            description: '业务结束时间',
          },
          {
            field_code: 'reason',
            field_name: '申请原因',
            data_type: 'TEXT',
            length: '',
            is_pk: false,
            is_fk: false,
            nullable: true,
            default_value: '',
            description: '申请原因说明',
          },
          {
            field_code: 'request_status',
            field_name: '申请状态',
            data_type: 'VARCHAR',
            length: '32',
            is_pk: false,
            is_fk: false,
            nullable: false,
            default_value: 'DRAFT',
            description: '当前审批状态',
          },
        ],
      },
    ],
    role_table_mapping: [
      {
        table_code: tableCode,
        table_name: entityName,
        permissions: [
          {
            role_code: 'all_employee',
            role_name: '全部员工',
            operations: ['暂存', '新增', '查看'],
            data_scope: 'self',
          },
          {
            role_code: 'dept_manager',
            role_name: '部门经理',
            operations: ['查看', '批量同意', '批量拒绝', '查看审批历史'],
            data_scope: 'dept',
          },
          {
            role_code: 'hr_specialist',
            role_name: 'HR专员',
            operations: ['查看', '导出', '日志'],
            data_scope: 'all',
          },
        ],
      },
    ],
    modules: [
      {
        module_name: moduleName,
        module_code: `${entityCode.toLowerCase()}_mgmt`,
        description: `${entityName}的提交、审批和查询功能`,
        features: [
          {
            name: `提交${entityName}`,
            description: '员工录入并提交业务申请',
            roles: ['全部员工'],
          },
          {
            name: `审批${entityName}`,
            description: '部门经理进行审批处理',
            roles: ['部门经理'],
          },
          {
            name: '统计分析',
            description: 'HR 查看全局台账和统计结果',
            roles: ['HR专员'],
          },
          ...codingFocusLines.slice(0, 2).map((line, index) => ({
            name: `自开发扩展 ${index + 1}`,
            description: line,
            roles: ['HR专员'],
          })),
        ],
      },
    ],
    flows: [
      {
        flow_name: `${entityName}审批流程`,
        flow_code: `${entityCode.toLowerCase()}_approval_flow`,
        description: `${entityName}从提交到审批归档的标准流程`,
        steps: [
          { step: 1, action: `员工提交${entityName}`, role: '全部员工', status: '待审批' },
          { step: 2, action: '部门经理审批', role: '部门经理', status: '已通过/已拒绝' },
          { step: 3, action: 'HR归档并统计', role: 'HR专员', status: '已归档' },
        ],
      },
    ],
  }
}

export function buildCodingBrief(
  docResult: AnalysisResult,
  input: UnifiedAiBuilderInput,
  sceneCategory?: string,
): string {
  const appInfo = docResult.app_info || { code: '', name: '未命名应用', description: '' }
  const roleNames = pickRoleNames(docResult)
  const tableNames = pickTableNames(docResult)
  const flowNames = pickFlowNames(docResult)
  const moduleFeatures = pickModuleFeatures(docResult)
  const codingFocusLines = cleanLines(input.codingFocus || '')
  const businessLines = cleanLines(input.businessInput)
  const resolvedScene = sceneCategory || inferCodingSceneCategory(docResult, input.codingFocus || '')

  const builderScope = [
    '组织角色、数据字典、数据表、表单和基础权限矩阵由智能搭建负责。',
    '基础流程配置和平台内可配置规则优先走低代码能力。',
  ]

  const codingScope = codingFocusLines.length > 0
    ? codingFocusLines.map(line => `- ${line}`)
    : [
        '- 请优先关注需要自定义页面交互、复杂组件、统计分析看板或平台外部接口集成的部分。',
        '- 如果需求主要是平台配置即可完成，请在实现前先确认是否真的需要自开发。',
      ]

  const featureLines = moduleFeatures.length > 0
    ? moduleFeatures.slice(0, 8).map(item => `- ${item}`)
    : ['- 暂无显式功能点，请结合业务对象和流程补齐实现细节。']

  return [
    `# ${appInfo.name || '业务应用'} 智能开发任务简报`,
    '',
    '## 一、背景与目标',
    '',
    `- **应用名称**：${appInfo.name || '未命名应用'}`,
    `- **应用编码**：${appInfo.code || '待补充'}`,
    `- **业务目标**：${appInfo.description || '待补充'}`,
    `- **推荐开发场景**：${resolvedScene}`,
    input.uploadedFileName ? `- **来源附件**：${input.uploadedFileName}` : '',
    '',
    '## 二、原始业务输入',
    '',
    joinLineSummary(businessLines, '暂无额外业务输入，主要以结构化设计文档为准。'),
    '',
    '## 三、与智能搭建的分工',
    '',
    ...builderScope.map(item => `- ${item}`),
    '',
    '## 四、智能开发需要重点处理的内容',
    '',
    ...codingScope,
    '',
    '## 五、业务结构参考',
    '',
    `- **角色**：${roleNames.length > 0 ? roleNames.join('、') : '待补充'}`,
    `- **核心业务对象**：${tableNames.length > 0 ? tableNames.join('、') : '待补充'}`,
    `- **关键流程**：${flowNames.length > 0 ? flowNames.join('、') : '待补充'}`,
    '',
    '## 六、建议先实现的功能点',
    '',
    ...featureLines,
    '',
    '## 七、执行要求',
    '',
    '- 以当前生成的设计文档为主，不要脱离低代码平台的数据模型和权限边界。',
    '- 如果发现某项需求纯靠平台配置即可完成，应明确指出并避免不必要的自开发。',
    '- 产出物需要能回到项目协作上下文中，便于后续多人接力和发布。',
    '',
  ]
    .filter(Boolean)
    .join('\n')
}
