// Mock data for the aPaaS Builder AI prototype.
// All data references real product concepts from the codebase.

window.MOCK = (() => {
  const apps = [
    {
      id: 1,
      name: '资产管理系统',
      code: 'asset_mgr',
      status: 'completed',
      env: '生产环境',
      apaasAppId: 'A20260318',
      models: 8, forms: 14, roles: 5, dicts: 12,
      updatedAt: '2026-05-17 14:22',
      source: 'local',
      desc: '从 IT 设备入库到资产盘点的全生命周期管理',
      color: 'indigo',
      conversations: [
        { id: 101, title: '盘点流程优化', summary: '12 条消息', time: '2 小时前' },
        { id: 102, title: '资产分类字典扩展', summary: '8 条消息', time: '昨天' },
      ],
    },
    {
      id: 2,
      name: '客户工单中心',
      code: 'cs_ticket',
      status: 'updating',
      env: '测试环境',
      apaasAppId: 'A20260315',
      models: 6, forms: 11, roles: 4, dicts: 9,
      updatedAt: '2026-05-17 09:08',
      source: 'local',
      desc: '客服工单流转、SLA 看板、客户回访闭环',
      color: 'sky',
      conversations: [
        { id: 103, title: 'SLA 看板字段调整', summary: '6 条消息', time: '今天 09:05' },
      ],
    },
    {
      id: 3,
      name: '差旅报销审批',
      code: 'travel_app',
      status: 'completed',
      env: '生产环境',
      apaasAppId: 'A20260308',
      models: 5, forms: 9, roles: 6, dicts: 7,
      updatedAt: '2026-05-16 18:31',
      source: 'imported',
      desc: '员工差旅申请、报销单据、多级审批',
      color: 'emerald',
      conversations: [],
    },
    {
      id: 4,
      name: '生产工单调度',
      code: 'mfg_work',
      status: 'generating',
      env: '—',
      apaasAppId: null,
      models: 7, forms: 0, roles: 0, dicts: 5,
      updatedAt: '2026-05-17 16:02',
      source: 'local',
      desc: '生产订单拆解、车间派工、产能看板',
      color: 'amber',
      conversations: [
        { id: 104, title: '车间工序模型设计', summary: '23 条消息', time: '刚刚' },
      ],
    },
    {
      id: 5,
      name: '合同审批',
      code: 'contract_v3',
      status: 'draft',
      env: '—',
      apaasAppId: null,
      models: 4, forms: 0, roles: 0, dicts: 3,
      updatedAt: '2026-05-15 11:40',
      source: 'local',
      desc: '合同模板维护、电子签章、归档检索',
      color: 'rose',
      conversations: [
        { id: 105, title: '初稿需求梳理', summary: '4 条消息', time: '2 天前' },
      ],
    },
    {
      id: 6,
      name: '供应商门户',
      code: 'supplier_portal',
      status: 'completed',
      env: '生产环境',
      apaasAppId: 'A20260229',
      models: 9, forms: 16, roles: 7, dicts: 14,
      updatedAt: '2026-05-13 10:15',
      source: 'local',
      desc: '供应商注册、准入审核、采购协同',
      color: 'indigo',
      conversations: [],
    },
  ];

  const conversations = [
    { id: 201, title: '资产管理系统 — 新增报废流程', appId: 1, agent: 'builder', updatedAt: '今天 14:22', messages: 18, pinned: true },
    { id: 202, title: '客户工单中心 — SLA 字段调整', appId: 2, agent: 'builder', updatedAt: '今天 09:08', messages: 6, pinned: false },
    { id: 203, title: '生产工单调度 — 车间工序', appId: 4, agent: 'builder', updatedAt: '刚刚', messages: 23, pinned: false },
    { id: 204, title: '合同审批 — 初稿需求', appId: 5, agent: 'builder', updatedAt: '2 天前', messages: 4, pinned: false },
    { id: 205, title: '差旅报销审批 — 多级审批配置', appId: 3, agent: 'builder', updatedAt: '5 月 14 日', messages: 11, pinned: false },
  ];

  const templates = [
    { code: 'std_design_doc', name: '功能设计文档（标准模板）', category: '通用模板', updatedAt: '2026-05-12', summary: '推荐使用的标准设计文档，含数据模型 / 表单 / 流程 / 权限四大章节。', filename: 'standard_design_doc.md' },
    { code: 'mfg_design_doc', name: '制造行业设计模板', category: '行业模板', updatedAt: '2026-04-28', summary: '面向生产、计划、质量三大场景，预置生产工单、BOM 等基础模型。', filename: 'manufacturing_doc.md' },
    { code: 'crm_design_doc', name: '客户管理（CRM）设计模板', category: '行业模板', updatedAt: '2026-04-20', summary: '客户、商机、跟进、回访的完整模型与表单。', filename: 'crm_doc.md' },
  ];

  const chatThread = [
    { role: 'user', text: '我想搭建一个资产管理系统，主要管理 IT 设备的入库、领用和盘点。', time: '14:18' },
    { role: 'ai', text: '收到。我先帮你梳理一下场景边界，确认几点关键信息：\n\n1. **管理范围**：仅 IT 设备（电脑、服务器、网络设备），还是包含办公家具、研发样机这类非 IT 资产？\n2. **角色**：除了系统管理员、设备使用人，是否需要资产管理员、部门负责人审批角色？\n3. **盘点方式**：是按周期发起全员盘点，还是支持随时抽盘？\n\n如果暂时没想好，可以直接说"按通用方案"，我会按行业最佳实践初始化。', time: '14:18', extras: ['即将更新 数据模型 · 角色'] },
    { role: 'user', text: '只管 IT 设备就行。角色就加一个资产管理员；盘点支持按季度全员盘点 + 随时抽盘。', time: '14:20' },
    { role: 'ai', text: '✅ 已根据需求初始化设计方案，右侧面板可以查看实时配置。\n\n**已生成：**\n- 数据模型 6 个：资产主档、资产分类、领用记录、盘点单、盘点明细、报废申请\n- 表单 11 个：资产入库、资产领用、季度盘点等\n- 角色 3 个：资产管理员、设备使用人、部门负责人\n- 字典 8 个：资产分类、状态、品牌等\n\n接下来你可以：\n- 在右侧检查每个模型字段，点击"确认"标识即可锁定\n- 或者继续告诉我要调整的细节（比如"资产主档加上保修截止日期"）', time: '14:22', extras: ['已更新 数据模型 6 · 表单 11 · 角色 3 · 字典 8'] },
    { role: 'user', text: '资产主档加上"保修截止日期"和"采购来源"，采购来源是字典。', time: '14:23' },
  ];

  // The blueprint shown on the right side of ChatPage — replaces the 5-tab structure.
  // Detailed enough to actually hand off to an AI builder (field-level, layout-level, permission-matrix-level).
  const blueprint = {
    summary: {
      appName: '资产管理系统',
      appCode: 'asset_mgr',
      status: '设计中',
      progress: 68,
      stages: [
        { name: '需求梳理', status: 'done' },
        { name: '数据模型', status: 'done' },
        { name: '表单与流程', status: 'active' },
        { name: '权限与字典', status: 'pending' },
        { name: '部署', status: 'pending' },
      ],
    },

    /* ─── Data models (字段级) ─── */
    models: [
      {
        name: '资产主档', code: 'asset_main', confirmed: true, hot: true,
        desc: '记录每台资产的完整台账，是整个系统的核心主表。',
        fields: [
          { code: 'asset_no',        name: '资产编号',     type: 'String',  size: 64,   pk: true,  unique: true, required: true, comment: '系统自动生成 AST + 6 位流水', recent: false },
          { code: 'asset_name',      name: '资产名称',     type: 'String',  size: 120,                          required: true, comment: '可重复' },
          { code: 'category_id',     name: '资产分类',     type: 'Ref',                fk: 'asset_category.id', required: true, comment: '两级分类' },
          { code: 'brand_code',      name: '品牌',         type: 'Dict',               dict: 'asset_brand' },
          { code: 'model',           name: '型号',         type: 'String',  size: 120 },
          { code: 'serial_no',       name: '序列号 / SN',  type: 'String',  size: 64,  unique: true,           comment: '不可重复，用于唯一定位实物' },
          { code: 'purchase_date',   name: '采购日期',     type: 'Date',                                       required: true },
          { code: 'purchase_source', name: '采购来源',     type: 'Dict',               dict: 'purchase_source', recent: true,  comment: '本次新增字段' },
          { code: 'warranty_until',  name: '保修截止日期', type: 'Date',                                                       recent: true,  comment: '本次新增字段' },
          { code: 'status',          name: '状态',         type: 'Dict',               dict: 'asset_status',  required: true, default: 'in_stock' },
          { code: 'holder_user_id',  name: '当前持有人',   type: 'Ref',                fk: 'sys_user.id' },
          { code: 'holder_dept_id', name: '当前所在部门', type: 'Ref',                fk: 'sys_dept.id',     comment: '随领用记录自动同步' },
          { code: 'location',        name: '存放位置',     type: 'String',  size: 200 },
          { code: 'remark',          name: '备注',         type: 'Text' },
        ],
        indexes: [
          { type: 'unique',    fields: 'asset_no' },
          { type: 'unique',    fields: 'serial_no' },
          { type: 'composite', fields: 'status, holder_dept_id' },
          { type: 'index',     fields: 'category_id' },
        ],
        relations: [
          { type: 'belongs-to', target: 'asset_category', on: 'category_id' },
          { type: 'has-many',   target: 'asset_borrow',   on: 'asset_id' },
          { type: 'has-many',   target: 'asset_scrap',    on: 'asset_id' },
        ],
      },
      {
        name: '资产分类', code: 'asset_category', confirmed: true,
        desc: '主类 / 子类两级分类，作为资产主档的分类外键。',
        fields: [
          { code: 'id',        name: 'ID',       type: 'BigInt', pk: true, autoInc: true },
          { code: 'parent_id', name: '父分类',   type: 'Ref',  fk: 'asset_category.id', comment: 'null 表示根节点' },
          { code: 'code',      name: '编码',     type: 'String', size: 32, unique: true, required: true },
          { code: 'name',      name: '名称',     type: 'String', size: 64, required: true },
          { code: 'sort',      name: '排序',     type: 'Int', default: 100 },
        ],
        indexes: [
          { type: 'unique', fields: 'code' },
          { type: 'index',  fields: 'parent_id, sort' },
        ],
        relations: [
          { type: 'self-ref', target: 'asset_category', on: 'parent_id' },
        ],
      },
      {
        name: '领用记录', code: 'asset_borrow', confirmed: true,
        desc: '每次领用与归还的流水。',
        fields: [
          { code: 'id',           name: 'ID',           type: 'BigInt', pk: true, autoInc: true },
          { code: 'asset_id',     name: '资产',         type: 'Ref',  fk: 'asset_main.asset_no', required: true },
          { code: 'borrow_user',  name: '领用人',       type: 'Ref',  fk: 'sys_user.id',        required: true },
          { code: 'borrow_dept',  name: '领用部门',     type: 'Ref',  fk: 'sys_dept.id',        required: true },
          { code: 'borrow_at',    name: '领用时间',     type: 'DateTime', required: true },
          { code: 'expected_back','name': '预期归还时间', type: 'Date' },
          { code: 'returned_at',  name: '实际归还时间', type: 'DateTime' },
          { code: 'usage',        name: '用途',         type: 'String', size: 200 },
          { code: 'state',        name: '状态',         type: 'Dict', dict: 'borrow_state', default: 'borrowing' },
        ],
        indexes: [
          { type: 'index', fields: 'asset_id, borrow_at' },
          { type: 'index', fields: 'borrow_user' },
        ],
        relations: [
          { type: 'belongs-to', target: 'asset_main', on: 'asset_id' },
        ],
      },
      {
        name: '盘点单', code: 'inv_check', confirmed: false,
        desc: '一次盘点活动的主单（季度盘点 / 抽盘共用）。',
        fields: [
          { code: 'id',         name: 'ID',         type: 'BigInt', pk: true, autoInc: true },
          { code: 'check_no',   name: '盘点单号',   type: 'String', size: 32, unique: true, required: true, comment: 'INV + 6 位流水' },
          { code: 'check_type', name: '类型',       type: 'Dict', dict: 'check_type', required: true, comment: '季度盘点 / 抽盘' },
          { code: 'plan_start', name: '开始日期',   type: 'Date', required: true },
          { code: 'plan_end',   name: '截止日期',   type: 'Date', required: true },
          { code: 'scope_dept', name: '盘点范围（部门）', type: 'RefList', fk: 'sys_dept.id', comment: '空表示全公司' },
          { code: 'status',     name: '状态',       type: 'Dict', dict: 'check_status', default: 'draft' },
          { code: 'creator',    name: '创建人',     type: 'Ref', fk: 'sys_user.id', required: true },
        ],
        indexes: [
          { type: 'unique', fields: 'check_no' },
          { type: 'index',  fields: 'status, plan_start' },
        ],
        relations: [
          { type: 'has-many', target: 'inv_check_item', on: 'check_id' },
        ],
      },
      {
        name: '盘点明细', code: 'inv_check_item', confirmed: false,
        desc: '盘点单下的逐条资产明细。',
        fields: [
          { code: 'id',         name: 'ID',           type: 'BigInt', pk: true, autoInc: true },
          { code: 'check_id',   name: '盘点单',       type: 'Ref',  fk: 'inv_check.id', required: true },
          { code: 'asset_id',   name: '资产',         type: 'Ref',  fk: 'asset_main.asset_no', required: true },
          { code: 'expected',   name: '台账值',       type: 'String', size: 200, comment: '盘点时快照' },
          { code: 'actual',     name: '实盘值',       type: 'String', size: 200 },
          { code: 'result',     name: '盘点结果',     type: 'Dict', dict: 'check_result', comment: '一致 / 盈余 / 缺失' },
          { code: 'remark',     name: '备注',         type: 'Text' },
          { code: 'checked_by', name: '盘点人',       type: 'Ref',  fk: 'sys_user.id' },
          { code: 'checked_at', name: '盘点时间',     type: 'DateTime' },
        ],
        indexes: [
          { type: 'index', fields: 'check_id' },
          { type: 'index', fields: 'asset_id' },
        ],
        relations: [
          { type: 'belongs-to', target: 'inv_check', on: 'check_id' },
          { type: 'belongs-to', target: 'asset_main', on: 'asset_id' },
        ],
      },
      {
        name: '报废申请', code: 'asset_scrap', confirmed: false,
        desc: '资产报废处置的流程主单。',
        fields: [
          { code: 'id',          name: 'ID',         type: 'BigInt', pk: true, autoInc: true },
          { code: 'scrap_no',    name: '报废单号',   type: 'String', size: 32, unique: true, required: true, comment: 'SCR + 6 位' },
          { code: 'asset_id',    name: '资产',       type: 'Ref',  fk: 'asset_main.asset_no', required: true },
          { code: 'apply_user',  name: '申请人',     type: 'Ref',  fk: 'sys_user.id', required: true },
          { code: 'apply_dept',  name: '申请部门',   type: 'Ref',  fk: 'sys_dept.id', required: true },
          { code: 'reason',      name: '报废原因',   type: 'Text', required: true },
          { code: 'dispose_way', name: '处置方式',   type: 'Dict', dict: 'dispose_way', required: true, comment: '回收 / 转捐 / 销毁' },
          { code: 'status',      name: '审批状态',   type: 'Dict', dict: 'approval_status', default: 'pending' },
        ],
        indexes: [
          { type: 'unique', fields: 'scrap_no' },
          { type: 'index',  fields: 'apply_user, status' },
        ],
        relations: [
          { type: 'belongs-to', target: 'asset_main', on: 'asset_id' },
        ],
      },
    ],

    /* ─── Forms (布局级) ─── */
    forms: [
      {
        name: '资产入库', code: 'form_asset_in', model: 'asset_main', type: '录入表单', confirmed: true,
        sections: [
          { title: '基本信息', fields: [
            { code: 'asset_name', widget: 'Input', col: 12 },
            { code: 'category_id', widget: 'TreeSelect', col: 12 },
            { code: 'brand_code', widget: 'DictSelect', col: 8 },
            { code: 'model', widget: 'Input', col: 8 },
            { code: 'serial_no', widget: 'Input', col: 8 },
          ]},
          { title: '采购信息', fields: [
            { code: 'purchase_date', widget: 'DatePicker', col: 8 },
            { code: 'purchase_source', widget: 'DictSelect', col: 8 },
            { code: 'warranty_until', widget: 'DatePicker', col: 8 },
          ]},
          { title: '存放信息', fields: [
            { code: 'holder_dept_id', widget: 'DeptSelect', col: 12 },
            { code: 'location', widget: 'Input', col: 12 },
            { code: 'remark', widget: 'Textarea', col: 24 },
          ]},
        ],
        actions: ['暂存', '提交入库'],
        rules: [
          '资产名称不能为空',
          '同一序列号不可重复',
          '采购日期 ≤ 今天',
          '保修截止 ≥ 采购日期',
        ],
      },
      { name: '资产领用', code: 'form_asset_borrow', model: 'asset_borrow', type: '录入表单', confirmed: true, sections: [{ title: '主信息', fields: [{ code: 'asset_id' },{ code: 'borrow_user' },{ code: 'expected_back' },{ code: 'usage' }] }], actions: ['提交'], rules: ['资产状态必须为「入库」'] },
      { name: '资产归还', code: 'form_asset_return', model: 'asset_borrow', type: '录入表单', confirmed: true, sections: [{ title: '归还信息', fields: [{ code: 'returned_at' },{ code: 'state' }] }], actions: ['提交归还'], rules: ['仅当 state = borrowing 时可归还'] },
      { name: '季度盘点', code: 'form_quarterly_check', model: 'inv_check', type: '流程表单', confirmed: false, sections: [{ title: '盘点设置', fields: [{ code: 'check_type' },{ code: 'plan_start' },{ code: 'plan_end' },{ code: 'scope_dept' }] }], actions: ['发起盘点'], rules: ['plan_end > plan_start'] },
      { name: '盘点明细录入', code: 'form_inv_item', model: 'inv_check_item', type: '子表单', confirmed: false, sections: [{ title: '逐条录入', fields: [{ code: 'asset_id' },{ code: 'actual' },{ code: 'result' },{ code: 'remark' }] }], actions: ['提交'], rules: [] },
      { name: '资产报废申请', code: 'form_asset_scrap', model: 'asset_scrap', type: '流程表单', confirmed: false, sections: [{ title: '报废申请', fields: [{ code: 'asset_id' },{ code: 'reason' },{ code: 'dispose_way' }] }], actions: ['提交审批'], rules: ['资产必须未被领用'] },
    ],

    /* ─── Workflows (流程级) — NEW ─── */
    workflows: [
      {
        name: '资产报废审批', code: 'wf_asset_scrap', confirmed: false,
        trigger: '提交「资产报废申请」表单',
        nodes: [
          { name: '申请',         role: '设备使用人',      action: '提交报废申请', sla: '—' },
          { name: '部门负责人',   role: '部门负责人',     action: '同意 / 驳回',   sla: '24h' },
          { name: '资产管理员',   role: '资产管理员',     action: '复核 / 驳回',   sla: '24h' },
          { name: '财务审批',     role: '财务',           action: '同意 / 驳回',   sla: '48h', condition: '资产原值 ≥ 10000 元' },
          { name: '归档',         role: '系统',           action: '自动归档',     sla: '—' },
        ],
      },
      {
        name: '季度盘点流程', code: 'wf_quarterly', confirmed: false,
        trigger: '每季度首月 1 号 09:00 自动发起',
        nodes: [
          { name: '生成盘点单', role: '系统',         action: '按范围生成盘点明细', sla: '—' },
          { name: '部门盘点',   role: '部门负责人',   action: '逐条录入实盘',       sla: '7d' },
          { name: '差异处理',   role: '资产管理员',   action: '处理盈余 / 缺失',   sla: '3d', condition: '存在 result != 一致' },
          { name: '生成报告',   role: '系统',         action: '自动汇总并归档',     sla: '—' },
        ],
      },
    ],

    /* ─── Roles (权限矩阵级) ─── */
    roles: [
      {
        name: '资产管理员', code: 'role_asset_admin', users: '系统管理员组（5 人）',
        scope: '全公司',
        matrix: [
          { module: '资产主档',     perms: ['查', '增', '改', '删'] },
          { module: '资产分类',     perms: ['查', '增', '改'] },
          { module: '领用记录',     perms: ['查', '改'] },
          { module: '盘点单',       perms: ['查', '增', '改', '删'] },
          { module: '报废申请',     perms: ['查', '审批', '复核'] },
          { module: '字典管理',     perms: ['查', '改'] },
        ],
      },
      {
        name: '设备使用人', code: 'role_user', users: '全员（约 1,200 人）',
        scope: '本人持有 / 申请',
        matrix: [
          { module: '资产主档',     perms: ['查（本人）'] },
          { module: '领用记录',     perms: ['查（本人）', '增'] },
          { module: '报废申请',     perms: ['查（本人）', '增'] },
        ],
      },
      {
        name: '部门负责人', code: 'role_dept_head', users: '部门负责人组（68 人）',
        scope: '本部门',
        matrix: [
          { module: '资产主档',     perms: ['查（本部门）'] },
          { module: '领用记录',     perms: ['查（本部门）'] },
          { module: '盘点单',       perms: ['查', '执行盘点'] },
          { module: '报废申请',     perms: ['审批（本部门）'] },
        ],
      },
    ],

    /* ─── Dicts (字典项级) ─── */
    dicts: [
      {
        name: '资产分类', code: 'dict_asset_category', confirmed: true, hierarchical: true,
        items: [
          { code: 'it_pc',     label: 'IT 设备',     children: [
            { code: 'it_pc_lap',  label: '笔记本电脑' },
            { code: 'it_pc_desk', label: '台式电脑' },
            { code: 'it_pc_disp', label: '显示器' },
            { code: 'it_pc_peri', label: '外设' },
          ]},
          { code: 'it_server', label: '服务器与网络', children: [
            { code: 'it_server_blade', label: '服务器' },
            { code: 'it_server_sw',    label: '交换机' },
            { code: 'it_server_fw',    label: '防火墙' },
            { code: 'it_server_ap',    label: '无线 AP' },
          ]},
          { code: 'it_mob',    label: '移动设备',     children: [
            { code: 'it_mob_phone', label: '手机' },
            { code: 'it_mob_pad',   label: '平板' },
            { code: 'it_mob_card',  label: '物联卡' },
          ]},
        ],
      },
      {
        name: '资产状态', code: 'dict_asset_status', confirmed: true,
        items: [
          { code: 'in_stock',  label: '入库',     tone: 'sky' },
          { code: 'allocated', label: '已领用',   tone: 'brand' },
          { code: 'in_repair', label: '维修中',   tone: 'amber' },
          { code: 'idle',      label: '闲置',     tone: 'gray' },
          { code: 'scrapped',  label: '已报废',   tone: 'rose' },
          { code: 'lost',      label: '遗失',     tone: 'rose' },
        ],
      },
      {
        name: '采购来源', code: 'dict_purchase_source', confirmed: true, recent: true,
        items: [
          { code: 'self_purchase', label: '自购' },
          { code: 'lease',         label: '租赁' },
          { code: 'donation',      label: '捐赠' },
          { code: 'transferred',   label: '内部调拨' },
          { code: 'project',       label: '项目专项' },
        ],
      },
      {
        name: '设备品牌', code: 'dict_asset_brand', confirmed: true,
        items: [
          { code: 'lenovo',  label: 'Lenovo' }, { code: 'dell',    label: 'Dell' },
          { code: 'apple',   label: 'Apple' },  { code: 'huawei',  label: 'Huawei' },
          { code: 'hp',      label: 'HP' },     { code: 'cisco',   label: 'Cisco' },
          { code: 'h3c',     label: 'H3C' },    { code: 'mi',      label: 'Xiaomi' },
        ],
      },
      {
        name: '处置方式', code: 'dict_dispose_way', confirmed: false,
        items: [
          { code: 'recycle', label: '回收' },
          { code: 'donate',  label: '转捐' },
          { code: 'destroy', label: '销毁' },
          { code: 'auction', label: '拍卖' },
          { code: 'transfer', label: '调拨' },
        ],
      },
      {
        name: '盘点结果', code: 'dict_check_result', confirmed: false,
        items: [
          { code: 'match',   label: '一致',   tone: 'emerald' },
          { code: 'surplus', label: '盈余',   tone: 'sky' },
          { code: 'short',   label: '缺失',   tone: 'rose' },
          { code: 'damaged', label: '已损坏', tone: 'amber' },
        ],
      },
    ],
  };

  // AI Coding workspaces (CodingPage)
  const workspaces = [
    {
      id: 'ws-1',
      name: '差旅报销表单',
      type: 'form-component',
      typeLabel: '表单组件',
      status: 'building',
      progress: 64,
      lastActivity: '正在写入 components/TravelForm.vue',
      tokensUsed: 12400,
      filesWritten: 8,
      filesPlanned: 12,
      time: '刚刚',
    },
    {
      id: 'ws-2',
      name: '客户工单看板',
      type: 'form-page',
      typeLabel: '页面',
      status: 'ready',
      progress: 100,
      lastActivity: '生成完成，可预览',
      tokensUsed: 23150,
      filesWritten: 14,
      filesPlanned: 14,
      time: '10 分钟前',
    },
    {
      id: 'ws-3',
      name: '资产分类树选择器',
      type: 'form-component',
      typeLabel: '表单组件',
      status: 'ready',
      progress: 100,
      lastActivity: '生成完成，已发布到组件市场',
      tokensUsed: 8420,
      filesWritten: 6,
      filesPlanned: 6,
      time: '昨天 18:21',
    },
    {
      id: 'ws-4',
      name: '审批历史时间线',
      type: 'form-component',
      typeLabel: '表单组件',
      status: 'idle',
      progress: 0,
      lastActivity: '等待启动',
      tokensUsed: 0,
      filesWritten: 0,
      filesPlanned: 0,
      time: '2 天前',
    },
  ];

  const codingSteps = [
    { name: '读取项目结构', status: 'done', detail: '已扫描 14 个相关文件' },
    { name: '生成设计方案', status: 'done', detail: '已确定组件拆分：5 个 Vue 文件 + 1 个 store' },
    { name: '并行写入组件', status: 'active', detail: '正在写入 TravelForm.vue（4/8）' },
    { name: '注入依赖与样式', status: 'pending', detail: '等待开始' },
    { name: '本地编译验证', status: 'pending', detail: '等待开始' },
  ];

  const codingChat = [
    { role: 'user', text: '帮我生成一个差旅报销表单组件，包含申请人、目的地、出差日期、明细子表、附件上传。' },
    { role: 'ai', text: '收到。我先扫描项目结构，然后按 Element UI 表单规范拆分组件：\n\n- `TravelForm.vue`（主表单）\n- `TravelDetailTable.vue`（明细子表）\n- `AttachmentUploader.vue`（附件）\n- `useTravelForm.ts`（state + 校验）\n\n我会一次性并行写完，不会反复读文件。', toolCalls: ['read_project_structure', 'list_components/form'] },
    { role: 'ai', text: '✅ 项目结构扫描完成。开始并行写入 5 个文件。', isToolStatus: true },
  ];

  const marketplace = [
    { id: 'm1', name: '可拖拽审批流时间线', category: 'form-component', categoryLabel: '表单组件', author: '前端组 · 周航', version: '1.4.0', downloads: 842, tags: ['审批', '时间线', '可拖拽'], desc: '用于审批历史展示的纵向时间线，支持节点状态、操作人、备注。', color: 'indigo' },
    { id: 'm2', name: '资产分类树选择器', category: 'form-component', categoryLabel: '表单组件', author: 'AI Coding · admin', version: '2.0.1', downloads: 1230, tags: ['资产', '树形', '多选'], desc: '两级分类树 + 搜索高亮，可挂接到任意主档表单。', color: 'emerald' },
    { id: 'm3', name: '工单 SLA 看板', category: 'form-page', categoryLabel: '页面', author: '后端组 · 李宁', version: '1.0.2', downloads: 412, tags: ['SLA', '看板', '工单'], desc: '一屏纵览工单 SLA 状态，自动按超时风险排序。', color: 'amber' },
    { id: 'm4', name: '差旅报销明细子表', category: 'form-component', categoryLabel: '表单组件', author: 'AI Coding · admin', version: '0.9.3', downloads: 198, tags: ['差旅', '子表', '金额'], desc: '可增减行、自动汇总、币种切换的报销明细子表。', color: 'sky' },
    { id: 'm5', name: '人员选择（含部门树）', category: 'form-component', categoryLabel: '表单组件', author: '基础组 · 王琪', version: '3.2.0', downloads: 2104, tags: ['人员', '部门', '基础'], desc: '人员选择基础组件，支持单选 / 多选 / 含部门树。', color: 'indigo' },
    { id: 'm6', name: '统一登录回调接口', category: 'backend-api', categoryLabel: '后端接口', author: '后端组 · 陈晨', version: '1.1.0', downloads: 76, tags: ['登录', 'SSO', '后端'], desc: '提供 SSO 登录后的用户信息同步与租户匹配。', color: 'rose' },
  ];

  const adminTenants = [
    { id: 1, name: '得帆云示例租户', code: 'definesys-demo', users: 24, apps: 12, plan: '内部测试', status: 'active', expiry: '永久' },
    { id: 2, name: '某汽车制造客户', code: 'auto-mfg', users: 8, apps: 4, plan: '标准', status: 'active', expiry: '2027-03-01' },
    { id: 3, name: '某连锁零售客户', code: 'retail-chain', users: 12, apps: 7, plan: '企业', status: 'active', expiry: '2026-12-31' },
    { id: 4, name: '某物流客户（试用）', code: 'logi-trial', users: 3, apps: 1, plan: '试用', status: 'trial', expiry: '2026-06-15' },
  ];

  const mcpServers = [
    {
      id: 'mcp-1', name: '得帆云 aPaaS Tools', code: 'apaas-tools', status: 'connected',
      transport: 'sse', endpoint: 'https://apaas-poc.definesys.cn/mcp/sse',
      tools: 14, lastUsed: '2 分钟前', usage: 824, version: '2.3.1',
      tags: ['官方', '应用配置', '部署'],
      desc: '官方 MCP，提供应用 / 模型 / 表单 / 权限 / 部署等 14 个工具。',
      official: true,
    },
    {
      id: 'mcp-2', name: '组件市场检索', code: 'marketplace-search', status: 'connected',
      transport: 'sse', endpoint: 'https://agent.dfy.definesys.cn/mcp/marketplace',
      tools: 5, lastUsed: '昨天 16:08', usage: 312, version: '1.0.4',
      tags: ['官方', '组件'],
      desc: '在 AI Coding 中按需检索组件市场已有产物，避免重复开发。',
      official: true,
    },
    {
      id: 'mcp-3', name: '需求文档检索（飞书）', code: 'feishu-docs', status: 'connected',
      transport: 'http', endpoint: 'https://internal-mcp.demo/feishu',
      tools: 3, lastUsed: '今天 11:30', usage: 142, version: '0.4.2',
      tags: ['自定义', '文档'],
      desc: '把租户飞书空间里的设计文档作为上下文喂给 AI。',
      official: false,
    },
    {
      id: 'mcp-4', name: '内部 ERP 字段映射', code: 'erp-fields', status: 'error',
      transport: 'stdio', endpoint: 'erp-bridge://localhost',
      tools: 8, lastUsed: '4 小时前', usage: 56, version: '0.2.0',
      tags: ['自定义', 'ERP'],
      desc: '把内部 ERP 系统的字段定义映射到 aPaaS 数据模型字段。',
      official: false,
      error: '连接超时（10s），请检查 erp-bridge 是否启动。',
    },
    {
      id: 'mcp-5', name: '生产工单 SOP 库', code: 'sop-library', status: 'disabled',
      transport: 'sse', endpoint: 'https://internal-mcp.demo/sop',
      tools: 6, lastUsed: '5 天前', usage: 18, version: '0.1.1',
      tags: ['自定义', '制造'],
      desc: '提供生产 SOP 检索能力，给智能搭建生成流程时引用。',
      official: false,
    },
    {
      id: 'mcp-6', name: 'GitHub Repo 检索', code: 'github-search', status: 'connected',
      transport: 'http', endpoint: 'https://mcp.github.com',
      tools: 4, lastUsed: '3 天前', usage: 6, version: '1.2.0',
      tags: ['第三方', '代码'],
      desc: '为 Vibe Coding 模式提供跨仓库代码检索能力。',
      official: false,
    },
    {
      id: 'mcp-7', name: '钉钉审批联动', code: 'dingtalk-approval', status: 'connected',
      transport: 'http', endpoint: 'https://oapi.dingtalk.com/mcp',
      tools: 7, lastUsed: '昨天', usage: 92, version: '0.6.0',
      tags: ['自定义', '审批'],
      desc: '在搭建审批流程时直接挂载钉钉审批节点。',
      official: false,
    },
    {
      id: 'mcp-8', name: '内部知识库（私有）', code: 'kb-private', status: 'connected',
      transport: 'sse', endpoint: 'https://kb.internal.demo/mcp',
      tools: 2, lastUsed: '今天 09:14', usage: 248, version: '1.5.0',
      tags: ['自定义', '知识库'],
      desc: '租户私有知识库，向量检索 + 全文检索。',
      official: false,
    },
  ];

  /* ─── Sandboxes (code-server containers per workspace) ─── */
  const sandboxes = [
    {
      id: 'sbx-7f3a', name: '差旅报销表单',     workspace: 'ws-1', flavor: '睿鲸',
      user: 'marshub', cpu: 1.2, cpuMax: 2, mem: 1.8, memMax: 4, disk: 0.6,
      idle: '0 min', status: 'active',     ttl: '剩余 1h 58m', created: '今天 14:22', image: 'node:20-alpine + apaas-bridge',
    },
    {
      id: 'sbx-2b1c', name: 'apaas-builder-ai · frontend', workspace: 'vibe', flavor: 'Vibe',
      user: 'marshub', cpu: 0.4, cpuMax: 4, mem: 3.1, memMax: 8, disk: 2.4,
      idle: '0 min', status: 'active',     ttl: '剩余 47 min',  created: '今天 13:50', image: 'code-server 4.112.0',
    },
    {
      id: 'sbx-9e44', name: '客户工单看板',     workspace: 'ws-2', flavor: '睿鲸',
      user: 'marshub', cpu: 0.0, cpuMax: 2, mem: 0.4, memMax: 4, disk: 0.3,
      idle: '12 min', status: 'idle',      ttl: '剩余 1h 48m', created: '今天 10:10', image: 'node:20-alpine + apaas-bridge',
    },
    {
      id: 'sbx-c821', name: '资产分类树选择器', workspace: 'ws-3', flavor: '睿鲸',
      user: '李宁',   cpu: 0.0, cpuMax: 2, mem: 0.0, memMax: 4, disk: 0.5,
      idle: '4h 02m', status: 'recycling', ttl: '即将回收',     created: '昨天 18:21', image: 'node:20-alpine + apaas-bridge',
    },
    {
      id: 'sbx-d115', name: '审批流时间线组件',  workspace: 'ws-x', flavor: '睿鲸',
      user: '周航',   cpu: 1.8, cpuMax: 2, mem: 3.4, memMax: 4, disk: 0.9,
      idle: '0 min', status: 'active',     ttl: '剩余 26 min', created: '今天 13:14', image: 'node:20-alpine + apaas-bridge',
    },
  ];

  /* ─── CI/CD pipelines ─── */
  const pipelines = [
    {
      id: 'run-1284', name: '差旅报销表单',  source: '睿鲸 · ws-1',  trigger: '自动', user: 'AI',
      time: '14:22', durationS: 0, status: 'running', branch: 'apaas-form-component',
      stages: [
        { name: 'Lint',    status: 'done',    durationS: 4 },
        { name: 'Build UMD', status: 'done',  durationS: 23 },
        { name: 'Unit Test', status: 'running', durationS: 12 },
        { name: 'E2E',     status: 'pending', durationS: 0 },
        { name: '发布到组件市场', status: 'pending', durationS: 0 },
      ],
    },
    {
      id: 'run-1283', name: '资产管理系统 · 增量部署', source: '智能搭建 · 资产管理系统', trigger: '手动', user: 'marshub',
      time: '13:58', durationS: 142, status: 'success', env: 'test',
      stages: [
        { name: '解析 diff',       status: 'done', durationS: 8 },
        { name: '校验配置',         status: 'done', durationS: 14 },
        { name: '调用 aPaaS API',  status: 'done', durationS: 96 },
        { name: '回归校验',         status: 'done', durationS: 24 },
      ],
    },
    {
      id: 'run-1282', name: 'apaas-builder-ai · frontend', source: 'Vibe · sbx-2b1c · main', trigger: 'git push', user: 'marshub',
      time: '13:32', durationS: 86, status: 'success', branch: 'main', commit: 'a3f9b21',
      stages: [
        { name: 'Lint',        status: 'done', durationS: 6 },
        { name: 'Build (vite)', status: 'done', durationS: 42 },
        { name: 'Unit Test',   status: 'done', durationS: 18 },
        { name: '部署到 staging', status: 'done', durationS: 20 },
      ],
    },
    {
      id: 'run-1281', name: '客户工单看板',  source: '睿鲸 · ws-2', trigger: '自动', user: 'AI',
      time: '10:48', durationS: 67, status: 'failed', branch: 'apaas-form-page',
      stages: [
        { name: 'Lint',        status: 'done',   durationS: 5 },
        { name: 'Build UMD',   status: 'failed', durationS: 62, error: 'SyntaxError: Unexpected token (form-list/index.vue:48)' },
        { name: 'Unit Test',   status: 'skip',   durationS: 0 },
        { name: '发布到组件市场', status: 'skip',  durationS: 0 },
      ],
    },
    {
      id: 'run-1280', name: '生产工单调度 · 全量部署', source: '智能搭建', trigger: '手动', user: 'marshub',
      time: '昨天 18:14', durationS: 312, status: 'success', env: 'prod',
      stages: [
        { name: '解析配置',    status: 'done', durationS: 12 },
        { name: '校验',        status: 'done', durationS: 8 },
        { name: '调用 aPaaS API', status: 'done', durationS: 268 },
        { name: '回归校验',    status: 'done', durationS: 24 },
      ],
    },
    {
      id: 'run-1279', name: '人员选择组件 v3.2.1', source: '睿鲸 · 王琪', trigger: '手动', user: '王琪',
      time: '昨天 16:02', durationS: 88, status: 'success', branch: 'apaas-form-component',
      stages: [
        { name: 'Lint',        status: 'done', durationS: 4 },
        { name: 'Build UMD',   status: 'done', durationS: 28 },
        { name: 'Unit Test',   status: 'done', durationS: 32 },
        { name: 'E2E',         status: 'done', durationS: 14 },
        { name: '发布到组件市场', status: 'done', durationS: 10 },
      ],
    },
  ];

  /* ─── Platform environments (aPaaS) ─── */
  const environments = [
    {
      id: 'dev',   name: '开发环境',  endpoint: 'https://apaas-dev.definesys.cn/backend',
      tenant: '743906758237356033', tenantName: '得帆云示例租户（开发）',
      health: 'ok', heartbeat: '30s 前', deployedApps: 9, default: false, keyExpiry: '2027-01-15',
    },
    {
      id: 'test',  name: '测试环境',  endpoint: 'https://apaas-test.definesys.cn/backend',
      tenant: '743906758237356033', tenantName: '得帆云示例租户（测试）',
      health: 'ok', heartbeat: '1m 前',  deployedApps: 7, default: true, keyExpiry: '2027-01-15',
    },
    {
      id: 'prod',  name: '生产环境',  endpoint: 'https://apaas-poc.definesys.cn/backend',
      tenant: '743906758237356033', tenantName: '得帆云示例租户',
      health: 'warn', heartbeat: '1m 前',  deployedApps: 12, default: false, keyExpiry: '2026-05-31', keyWarn: true,
    },
  ];

  /* ─── Deployment history ─── */
  const deployments = [
    { id: 'dep-209', app: '资产管理系统',  appCode: 'asset_mgr',     env: 'test',  version: 'v1.4.3', user: 'marshub', time: '14:24', status: 'success', changes: '增量：+ 报废审批节点 · 字段 +2',  duration: '2m 22s' },
    { id: 'dep-208', app: '差旅报销表单',  appCode: 'asset_mgr',     env: 'prod',  version: 'v0.9.4', user: 'AI',      time: '13:32', status: 'success', changes: '组件发布：v0.9.4',  duration: '1m 46s' },
    { id: 'dep-207', app: '客户工单中心',  appCode: 'cs_ticket',     env: 'test',  version: 'v2.1.0', user: 'marshub', time: '09:08', status: 'success', changes: '调整 SLA 字段',     duration: '1m 12s' },
    { id: 'dep-206', app: '生产工单调度',  appCode: 'mfg_work',      env: 'prod',  version: 'v1.0.0', user: 'marshub', time: '昨天',  status: 'success', changes: '首次全量部署',     duration: '5m 12s' },
    { id: 'dep-205', app: '客户工单看板',  appCode: 'ws-2',          env: 'test',  version: 'v0.0.1', user: 'AI',      time: '昨天',  status: 'failed',  changes: '组件构建失败',     duration: '1m 07s', error: 'SyntaxError' },
    { id: 'dep-204', app: '资产管理系统',  appCode: 'asset_mgr',     env: 'prod',  version: 'v1.4.2', user: 'marshub', time: '5/16',  status: 'success', changes: '增量：+ 盘点结果字典', duration: '2m 08s' },
    { id: 'dep-203', app: '合同审批',      appCode: 'contract_v3',  env: 'dev',   version: 'v0.1.0', user: 'marshub', time: '5/15',  status: 'success', changes: '草稿试部署',     duration: '0m 58s' },
  ];

  /* ─── (mcpServers already declared above this block) ─── */
  void 0;

  /* ─── App SPECs — Design docs sit in here, versioned per app ─── */
  const specs = [
    {
      id: 'spec-1', app: '资产管理系统', appCode: 'asset_mgr', appId: 1, color: 'indigo',
      currentVersion: 'v3', status: 'draft', updatedAt: '今天 14:23', author: 'marshub + AI',
      diff: { add: 2, modify: 4, remove: 0 },
      sections: ['需求摘要', '数据模型 (6)', '表单 (6)', '流程 (2)', '角色权限 (3)', '字典 (6)'],
      versions: [
        { v: 'v3', status: 'draft',  time: '今天 14:23', author: 'marshub + AI', note: '+ 报废审批流程 · + 保修截止日期、采购来源字段' },
        { v: 'v2', status: 'deployed-test', time: '5/15 18:02', author: 'marshub', note: '调整资产分类字典层级 · 部署到测试环境' },
        { v: 'v1', status: 'deployed-prod', time: '5/10 11:30', author: 'marshub + AI', note: '首版：6 模型 / 4 表单 / 1 流程 · 部署到生产' },
        { v: 'v0', status: 'archived', time: '5/9',        author: 'AI 起草',    note: '由设计文档模板自动生成的初稿' },
      ],
      origin: '设计文档模板 · 通用',
    },
    {
      id: 'spec-2', app: '客户工单中心', appCode: 'cs_ticket', appId: 2, color: 'sky',
      currentVersion: 'v2', status: 'deployed', updatedAt: '今天 09:08', author: 'marshub',
      diff: { add: 0, modify: 1, remove: 0 },
      sections: ['需求摘要', '数据模型 (6)', '表单 (11)', '流程 (3)', '角色权限 (4)', '字典 (9)'],
      versions: [
        { v: 'v2', status: 'deployed-test',  time: '今天 09:08', author: 'marshub', note: '调整 SLA 字段类型' },
        { v: 'v1', status: 'deployed-prod',  time: '5/12',       author: 'marshub + AI', note: '首版部署到生产' },
      ],
      origin: '客户管理（CRM）设计模板',
    },
    {
      id: 'spec-3', app: '生产工单调度', appCode: 'mfg_work', appId: 4, color: 'amber',
      currentVersion: 'v1', status: 'draft', updatedAt: '刚刚', author: 'marshub + AI',
      diff: { add: 7, modify: 0, remove: 0 },
      sections: ['需求摘要', '数据模型 (7)', '表单 (0)', '流程 (0)', '角色权限 (0)', '字典 (5)'],
      versions: [
        { v: 'v1', status: 'draft', time: '刚刚', author: 'marshub + AI', note: '基于「制造装备」行业包初始化' },
      ],
      origin: '行业知识库 · 制造装备 v2.1',
    },
    {
      id: 'spec-4', app: '合同审批', appCode: 'contract_v3', appId: 5, color: 'rose',
      currentVersion: 'v0', status: 'draft', updatedAt: '2 天前', author: 'marshub',
      diff: { add: 4, modify: 0, remove: 0 },
      sections: ['需求摘要', '数据模型 (4)', '表单 (0)', '流程 (0)', '角色权限 (0)', '字典 (3)'],
      versions: [
        { v: 'v0', status: 'draft', time: '5/15', author: 'marshub', note: '初稿，待 AI 协助完善流程' },
      ],
      origin: '从零开始（无模板）',
    },
  ];

  /* ─── Industry knowledge packs (Palantir-style ontology) ─── */
  const industryPacks = [
    {
      id: 'pkg-mfg',  name: '制造装备', code: 'manufacturing', tone: 'amber',
      version: 'v2.1', installed: true, default: true,
      summary: '面向离散制造与连续生产，覆盖订单 → 计划 → 派工 → 质检 → 入库全链路。',
      stats: { entities: 12, relations: 30, workflows: 8, dicts: 24, forms: 18, roles: 6 },
      adopted: ['生产工单调度', '资产管理系统', '某汽车制造客户'],
      maintainer: '得帆云 · 行业卓越中心',
      updated: '5/14',
    },
    {
      id: 'pkg-crm',  name: '客户运营', code: 'crm-ops', tone: 'sky',
      version: 'v3.0', installed: true, default: false,
      summary: '客户 360 + 商机 + 工单 + SLA + 回访的完整对象图谱。',
      stats: { entities: 9, relations: 22, workflows: 6, dicts: 18, forms: 14, roles: 5 },
      adopted: ['客户工单中心', '某连锁零售客户'],
      maintainer: '得帆云 · 客户成功部',
      updated: '5/12',
    },
    {
      id: 'pkg-logi', name: '智慧物流', code: 'logistics', tone: 'emerald',
      version: 'v1.4', installed: false,
      summary: '运单 / 仓配 / 路由 / 异常处理，含 GIS 字段类型与司机签收节点。',
      stats: { entities: 11, relations: 26, workflows: 7, dicts: 21, forms: 15, roles: 5 },
      adopted: ['某物流客户（试用）'],
      maintainer: '物流行业小组',
      updated: '5/03',
    },
    {
      id: 'pkg-govt', name: '政企服务', code: 'govt-svc', tone: 'rose',
      version: 'v0.9', installed: false,
      summary: '事项审批、办件流转、政务字典（行政区划 / 事项分类标准编码）。',
      stats: { entities: 8, relations: 16, workflows: 5, dicts: 36, forms: 12, roles: 6 },
      adopted: [],
      maintainer: '政企行业小组（Beta）',
      updated: '4/28',
    },
  ];

  /* ─── Active pack ontology (entities + relations) shown in detail ─── */
  const industryOntology = {
    pack: 'pkg-mfg',
    entities: [
      { code: 'work_order',  name: '生产工单',   fields: 18, x: 50, y: 50,  hot: true,  tone: 'brand' },
      { code: 'bom',         name: 'BOM 物料清单', fields: 12, x: 50, y: 220, tone: 'brand' },
      { code: 'process',     name: '工序',       fields: 8,  x: 260, y: 50,  tone: 'brand' },
      { code: 'workshop',    name: '车间',       fields: 6,  x: 260, y: 220, tone: 'sky' },
      { code: 'machine',     name: '设备',       fields: 14, x: 260, y: 380, tone: 'sky' },
      { code: 'operator',    name: '操作工',     fields: 10, x: 470, y: 220, tone: 'amber' },
      { code: 'qc_record',   name: '质检记录',   fields: 11, x: 470, y: 50,  tone: 'rose' },
      { code: 'material',    name: '原材料',     fields: 9,  x: 50, y: 380, tone: 'brand' },
      { code: 'fg_inv',      name: '成品库存',   fields: 8,  x: 470, y: 380, tone: 'emerald' },
    ],
    relations: [
      { from: 'work_order', to: 'bom',       label: 'consumes' },
      { from: 'work_order', to: 'process',   label: 'has steps' },
      { from: 'process',    to: 'workshop',  label: 'runs in' },
      { from: 'process',    to: 'machine',   label: 'uses' },
      { from: 'machine',    to: 'operator',  label: 'operated by' },
      { from: 'work_order', to: 'qc_record', label: 'inspected by' },
      { from: 'bom',        to: 'material',  label: 'composed of' },
      { from: 'work_order', to: 'fg_inv',    label: 'produces' },
    ],
    workflows: [
      { name: '工单发起 → 计划排程',     nodes: 4, sla: '24h' },
      { name: '车间派工 → 工序确认',     nodes: 5, sla: '4h'  },
      { name: '在制品转序 → 质检',       nodes: 6, sla: '2h'  },
      { name: '成品入库 → 工单关闭',     nodes: 4, sla: '24h' },
      { name: '异常停机 → 修复 → 复工', nodes: 7, sla: '60min' },
    ],
    dictHighlight: [
      { code: 'wo_status',  name: '工单状态',   items: 8 },
      { code: 'qc_result',  name: '质检结果',   items: 5 },
      { code: 'machine_state', name: '设备状态', items: 6 },
      { code: 'priority',   name: '优先级',     items: 4 },
    ],
  };

  const projects = [
    {
      id: 1, name: '得帆云示例租户', code: 'definesys-demo', customer: '内部 / 示例',
      stage: '运行中', stageTone: 'emerald', progress: 100,
      appCount: 6, memberCount: 8, deployedCount: 3, status: 'active',
      industry: 'pkg-mfg', industryName: '制造装备', industryVersion: 'v2.1',
      envs: ['dev', 'test', 'prod'], defaultEnv: 'test',
      lead: 'marshub', updatedAt: '今天 14:23',
      summary: '内部演示与 dogfooding 项目，包含资产管理、工单、报销等多个应用。',
      members: [
        { name: 'marshub', role: '项目负责人', avatar: 'M', tone: 'brand' },
        { name: '李宁',    role: '实施顾问',   avatar: '李', tone: 'sky' },
        { name: '周航',    role: '前端开发',   avatar: '周', tone: 'emerald' },
        { name: '王琪',    role: '前端开发',   avatar: '王', tone: 'emerald' },
        { name: '陈晨',    role: '后端开发',   avatar: '陈', tone: 'amber' },
        { name: '张工',    role: '客户业务',   avatar: '张', tone: 'rose' },
      ],
      apps: [1, 2, 3, 4, 5, 6],
      milestones: [
        { time: '5/10', text: '资产管理系统首版部署到生产', done: true },
        { time: '5/14', text: '采用制造装备行业包 v2.1',     done: true },
        { time: '5/17', text: '客户工单 SLA 改造',           done: true },
        { time: '5/22', text: '生产工单调度上线试运行',       done: false },
        { time: '6/05', text: '合同审批一期验收',             done: false },
      ],
    },
    {
      id: 2, name: '某汽车制造客户', code: 'auto-mfg-2026', customer: '某汽车制造 · 数字化项目',
      stage: '设计中', stageTone: 'sky', progress: 35,
      appCount: 4, memberCount: 5, deployedCount: 1, status: 'active',
      industry: 'pkg-mfg', industryName: '制造装备', industryVersion: 'v2.1',
      envs: ['dev', 'test'], defaultEnv: 'dev',
      lead: '李宁', updatedAt: '今天 11:02',
      summary: '汽车主机厂的整车装配 + 备料 + 质检系统数字化。一期 4 个应用。',
      members: [
        { name: '李宁',    role: '项目负责人 + 实施', avatar: '李', tone: 'brand' },
        { name: '张工',    role: '客户业务方',         avatar: '张', tone: 'rose' },
        { name: '周航',    role: '前端开发',           avatar: '周', tone: 'emerald' },
        { name: '客户 IT 王', role: '客户 IT',         avatar: '王', tone: 'amber' },
        { name: 'marshub', role: '观察员',             avatar: 'M', tone: 'sky' },
      ],
      apps: [],
      milestones: [
        { time: '4/20', text: '需求调研 + Kick-off',           done: true },
        { time: '5/10', text: '导入制造装备行业包并派生定制', done: true },
        { time: '5/30', text: '4 个应用 SPEC 评审',            done: false },
        { time: '6/15', text: '一期试运行',                    done: false },
      ],
    },
    {
      id: 3, name: '某连锁零售客户', code: 'retail-2026', customer: '某连锁零售 · 总部数字化',
      stage: '试运行', stageTone: 'amber', progress: 72,
      appCount: 7, memberCount: 6, deployedCount: 4, status: 'active',
      industry: 'pkg-crm', industryName: '客户运营', industryVersion: 'v3.0',
      envs: ['dev', 'test', 'prod'], defaultEnv: 'test',
      lead: '李宁', updatedAt: '昨天',
      summary: '连锁零售总部的会员、商品、订单、供应链协同的统一搭建。',
      members: [
        { name: '李宁', role: '项目负责人', avatar: '李', tone: 'brand' },
        { name: '王琪', role: '前端开发',   avatar: '王', tone: 'emerald' },
        { name: 'marshub', role: '架构顾问', avatar: 'M', tone: 'sky' },
      ],
      apps: [],
      milestones: [],
    },
    {
      id: 4, name: '某物流客户（试用）', code: 'logi-trial', customer: '某物流公司',
      stage: '调研', stageTone: 'gray', progress: 8,
      appCount: 1, memberCount: 3, deployedCount: 0, status: 'trial',
      industry: 'pkg-logi', industryName: '智慧物流', industryVersion: 'v1.4',
      envs: ['dev'], defaultEnv: 'dev',
      lead: 'marshub', updatedAt: '5/15',
      summary: '试用客户，正在评估是否引入。',
      members: [
        { name: 'marshub', role: '项目负责人', avatar: 'M', tone: 'brand' },
        { name: '客户 IT 赵', role: '客户 IT', avatar: '赵', tone: 'rose' },
      ],
      apps: [],
      milestones: [],
    },
  ];

  /* ─── Agents (3 智能体 + their Skills / MCP / Knowledge bindings) ─── */
  const agents = [
    {
      id: 'builder', name: '睿鲸 AI Builder', icon: 'chat', tone: 'ai',
      role: '业务搭建', desc: '从对话出发，把零碎需求整理成标准 SPEC 设计文档，并驱动 aPaaS 平台生成应用。',
      model: 'Claude Haiku 4.5', modelOptions: ['Claude Haiku 4.5', 'Qwen-Max', 'MiniMax abab6'],
      systemPrompt: '你是得帆云 aPaaS Builder 的业务搭建助手，目标是把用户的业务需求转化为标准设计文档（SPEC），同时驱动 aPaaS API 生成对应的模型、表单、流程、权限。',
      contextWindow: 200000, maxOutput: 8192,
      skills: [
        { code: 'apaas-app-builder', name: '应用搭建', desc: '把 SPEC 翻译为 aPaaS YAML 配置 + 调用执行引擎' },
        { code: 'apaas-app-updater', name: '应用增量更新', desc: '对已部署应用做增量改动 + diff' },
        { code: 'apaas-api-reference', name: 'API 参考', desc: '查询 aPaaS API 文档' },
        { code: 'std-design-doc', name: '标准设计文档', desc: '按章节模板生成 / 校验设计文档' },
        { code: 'requirements-elicit', name: '需求挖掘', desc: '多轮追问 + 角色 / 边界澄清' },
      ],
      mcps: ['mcp-1', 'mcp-3', 'mcp-8'],
      knowledge: { industryPacks: ['pkg-mfg', 'pkg-crm'], specTemplates: ['std_design_doc', 'mfg_design_doc', 'crm_design_doc'] },
      activeCalls: 18, todayCalls: 84,
    },
    {
      id: 'whale', name: '睿鲸 AI Coding', icon: 'whale', tone: 'brand',
      role: '低代码组件生成', desc: '把组件需求翻译为符合 aPaaS 规范的 Vue 组件，并发布到组件市场。',
      model: 'Claude Haiku 4.5', modelOptions: ['Claude Haiku 4.5', 'Qwen-Coder', 'DeepSeek Coder'],
      systemPrompt: '你是得帆云 aPaaS 的组件生成助手，目标是生成符合平台规范的 Vue 自开发组件（表单组件 / 页面 / 列表视图 / 后端接口），并打包为 UMD。',
      contextWindow: 200000, maxOutput: 8192,
      skills: [
        { code: 'form-component', name: '表单组件生成', desc: '按 Element UI 2.x 规范生成表单组件' },
        { code: 'form-page', name: '页面生成', desc: '生成 form-page 整页组件' },
        { code: 'backend-api', name: '后端接口生成', desc: '生成 aPaaS 后端 OpenAPI 接口' },
        { code: 'umd-build', name: 'UMD 打包', desc: '编译为可挂载到平台的 UMD bundle' },
      ],
      mcps: ['mcp-1', 'mcp-2'],
      knowledge: { industryPacks: [], specTemplates: [] },
      activeCalls: 3, todayCalls: 12,
    },
    {
      id: 'vibe', name: 'Vibe Coding', icon: 'code', tone: 'emerald',
      role: '全代码工作区助手', desc: 'code-server 内置 Chat 扩展，帮你直接编辑 / 重构本项目代码。Cursor 风格。',
      model: 'MiniMax abab6', modelOptions: ['Claude Haiku 4.5', 'Qwen-Coder', 'MiniMax abab6'],
      systemPrompt: '你是嵌入 code-server 工作区里的代码助手，可以读写工程文件、执行命令、查看 git 状态。优先用项目内已有模式。',
      contextWindow: 200000, maxOutput: 8192,
      skills: [
        { code: 'project-search', name: '项目检索', desc: 'ripgrep + 语义搜索' },
        { code: 'multi-edit', name: '多文件编辑', desc: '并行修改多个文件 + diff 预览' },
        { code: 'terminal-exec', name: '终端执行', desc: '运行 npm / git / 测试命令' },
        { code: 'git-aware', name: 'Git 上下文', desc: '理解 branch / commit / 未提交变更' },
      ],
      mcps: ['mcp-2', 'mcp-6'],
      knowledge: { industryPacks: [], specTemplates: [] },
      activeCalls: 1, todayCalls: 7,
    },
  ];

  /* ─── Skill catalog (all available skills) ─── */
  const skillCatalog = [
    { code: 'apaas-app-builder',  name: '应用搭建',         category: 'aPaaS', desc: 'SPEC → YAML → 执行引擎', maintainer: '得帆云', usedBy: ['builder'] },
    { code: 'apaas-app-updater',  name: '应用增量更新',     category: 'aPaaS', desc: '对已部署应用做增量改动', maintainer: '得帆云', usedBy: ['builder'] },
    { code: 'apaas-api-reference',name: 'API 参考',         category: 'aPaaS', desc: '查询 aPaaS API 文档',  maintainer: '得帆云', usedBy: ['builder'] },
    { code: 'std-design-doc',     name: '标准设计文档',     category: '通用', desc: '按章节模板生成 / 校验',   maintainer: '得帆云', usedBy: ['builder'] },
    { code: 'requirements-elicit',name: '需求挖掘',         category: '通用', desc: '多轮追问 + 角色澄清',     maintainer: '得帆云', usedBy: ['builder'] },
    { code: 'form-component',     name: '表单组件生成',     category: '代码生成', desc: 'Element UI 2.x 表单',   maintainer: '得帆云', usedBy: ['whale'] },
    { code: 'form-page',          name: '页面生成',         category: '代码生成', desc: 'form-page 整页组件',     maintainer: '得帆云', usedBy: ['whale'] },
    { code: 'backend-api',        name: '后端接口生成',     category: '代码生成', desc: 'aPaaS OpenAPI',         maintainer: '得帆云', usedBy: ['whale'] },
    { code: 'umd-build',          name: 'UMD 打包',         category: '代码生成', desc: '编译为 UMD bundle',     maintainer: '得帆云', usedBy: ['whale'] },
    { code: 'project-search',     name: '项目检索',         category: '工作区', desc: 'ripgrep + 语义搜索',     maintainer: '社区',   usedBy: ['vibe'] },
    { code: 'multi-edit',         name: '多文件编辑',       category: '工作区', desc: '并行修改 + diff',         maintainer: '社区',   usedBy: ['vibe'] },
    { code: 'terminal-exec',      name: '终端执行',         category: '工作区', desc: '运行命令',                maintainer: '社区',   usedBy: ['vibe'] },
    { code: 'git-aware',          name: 'Git 上下文',       category: '工作区', desc: '理解 branch / commit',    maintainer: '社区',   usedBy: ['vibe'] },
  ];

  return { apps, conversations, templates, chatThread, blueprint, workspaces, codingSteps, codingChat, marketplace, adminTenants, mcpServers, sandboxes, pipelines, environments, deployments, specs, industryPacks, industryOntology, projects, agents, skillCatalog };
})();
