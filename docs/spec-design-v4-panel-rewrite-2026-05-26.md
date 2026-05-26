# SPEC: design-v4 4 panel 重写 (照抄 Claude Design 截图)

> 2026-05-26 大下 session 接手用. 用户反馈: 当前 native panel 只是"功能 skeleton",
> 跟 design 截图视觉/交互差距巨大. 本 SPEC 列 4 panel 真实需求 + 数据结构 +
> backend 接入点 + 实施分解.

## 现状基线 (commit `13bad85`)

- 顶部 5 tab + 设计 tab 重构 (左菜单 list + 右 designer 4 sub)
- 4 panel skeleton: FormDesigner / ListDesigner / ProcessDesigner / DataModelDetail / DictEditor / RoleManage
- backend: 7 POST CRUD endpoint (`/api/applications/{id}/crud/...`)
- 已装: @antv/x6 3.1.7, tslib 2.8.1, vuedraggable 4.1.0

## 差距清单

### 1. 设计/表单 (FormDesignerPanel)
| 维度 | design 截图 | 现状 |
|---|---|---|
| 左 sidebar | 3 sub-tab "页面/组件/数据"; 组件 list 19 widget (基础输入 14 + 日期 5) 可拖入 canvas | 没有 sidebar, 直接显字段 table |
| 中央 | 真表单 preview (WYSIWYG) — 字段卡片可拖排序 / 点选高亮 / 显占位符 / 显字段类型 chip | 字段 table (#/字段名/Key/类型/必填/注释/操作 7 列) |
| 字段卡片 | 标题 + 必填星号 + 类型 chip (user/select/daterange/number/textarea/file) + 占位 input/下拉/选项 chips | 行 |
| 右侧 | 属性面板 (字段名/Key/类型/占位符/必填/可编辑/开启 AI 校验/选项 list + 新增/AI 排序 prompt) | 无 |
| 底部 | "+ 从组件库拖入字段 · 或 AI 添加" 占位 + 提交申请/取消按钮 | "+ 新增字段" CTA disabled |
| AI 助手 | inline 右侧 panel: chips (分析当前表单/添加字段/生成测试数据) + 提示 list + 输入框 | FAB |

### 2. 设计/数据 (新 DataSchemaEditor)
**design 截图显**: 应用 → 设计/数据 sub 显数据表 schema 编辑器 (不是字典 list).

| 元素 | 内容 |
|---|---|
| 表头 | `leave_requests` MySQL **主表** badge. "11 字段 · 1,284 行 · 主键 id · 1 外键" |
| 右上 | "AI 推荐索引" / "同步" / "+ 新增字段" |
| sub-tabs | **Schema** / 数据 / SQL / 关系 |
| 字段 table 列 | 字段 / 类型 / NULL / 键 (PK/FK/IDX badge) / 默认值 / 注释 / 操作 |
| 字段行示例 | `id BIGINT ✓ PK AUTO 主键` / `applicant_id BIGINT ✓ FK - 申请人 → employees.id` / `status VARCHAR(16) ✓ IDX pending 审批状态` |

**注意**: 这跟现在的"数据/数据模型"sub 重叠. 需决定:
- 选项 A: 设计 tab 加 5th sub "数据" (跟"页面/组件/数据" sidebar 对齐)
- 选项 B: 数据 tab 整改成 schema 编辑器 (跟 design 截图对齐), 砍掉字典 sub
- 选项 C: 两个共存 — 设计/数据 是表 schema, 数据 tab 是模型/字典/字段权限

### 3. 设计/流程 (ProcessDesignerPanel — 已有 x6 但节点少)
| 维度 | design 截图 | 现状 |
|---|---|---|
| 左 sidebar | 24 节点分 4 类: **入口/出口 4** (开始/结束/定时触发/Webhook), **审批 5** (指定人/角色/上级/会签/抄送), **逻辑 5** (条件/多分支/并行/汇聚/等待), **动作 5** (填写表单/写入数据表/读取数据/AI 判定/AI 生成) | 4 节点 (开始/用户任务/网关/结束) |
| 中央顶部 | "请假审批流" + "1 入口 · 8 节点 · 8 连线 · 最近运行 12 分钟前" + 自动布局 / AI 优化 / 试跑 / 部署 | 节点统计 + "适应画布/保存/查看" |
| 中央 canvas | x6 8 节点 BPMN | x6 4 mock 节点 |
| 右侧属性 | 节点 Key (n3) / 审批人 chip + / 审批策略 (单人审批 ▾) / SLA (2 小时) / 超时自动通过/允许加签/允许退回 switches / 问 AI prompt | 无 |

### 4. 权限 (RoleManagePanel → 矩阵 view)
| 维度 | design 截图 | 现状 |
|---|---|---|
| 主视图 | **角色 × 资源矩阵** (4 角色 × 10 资源). 列分组: 页面/数据/流程/应用设置 | master-detail (左角色 list + 右成员 table) |
| 右上 | 矩阵 / 角色列表 toggle + AI 建议 + 新增角色 | 仅角色 list |
| 矩阵 cell | 全部 (X) / 读写 (RW) / 只读 (R) / 禁止 4 状态 chip | 无 |
| 角色行 | 头像 + 名称 + 人数 | 名称 + code |
| 图例 | 底部 "全部 X / 读写 RW / 只读 R / 禁止" | 无 |

## 详细实施计划 (下 session)

### Phase A — 表单设计器重写 (最重要, ~1500 行)

#### A1. 新组件 `FormBuilderPanel.vue` (替 FormDesignerPanel)
3 列布局:
```
+--------+-------------------------+---------+
| 组件库 |   表单 preview canvas    | 属性面板 |
| 200px  |   flex: 1                | 280px   |
+--------+-------------------------+---------+
```

**左 sidebar 组件库** (`FormComponentLibrary.vue`):
- 顶部 search 框
- 分类 collapsible:
  - **基础输入 14**: 单行文本/多行文本/富文本/数字/金额/评分/滑块/开关/多选/单选/下拉单选/下拉多选/标签/颜色
  - **日期/时间 5**: 日期/时间/日期时间/日期区间/月份
  - **选择 (新加)**: 人员/部门/角色/字典/级联
  - **媒体**: 图片/附件/签名
  - **关联**: 引用其他表/子表/汇总
- 每项 chip: icon + name (12px)
- click → 加入 canvas 末尾 OR drag → 拖到 canvas 指定位置

**中央 canvas** (`FormPreviewCanvas.vue`):
- 标题 + 描述 inline 可编辑
- 字段卡片 list (vuedraggable v-model="fields"):
  - 每张卡: 标题 + 必填星 + 类型 chip + 真实预览组件 (input/select/textarea/file 等)
  - hover 高亮 / click 选中 (selectedFieldId emit)
  - 右侧拖把手 / 删除按钮
- 末尾占位: "+ 从组件库拖入字段 · 或 AI 添加"

**右属性面板** (`FormFieldPropsPanel.vue`):
- 已选字段时显;
- 字段名称 / 字段 Key / 类型 ▾ / 占位符 / 必填 / 可编辑 / 开启 AI 校验 switches
- 选项 list (select/radio/checkbox 时):
  - 每项: chip + 删除 / + 新增选项
- 底部: "问 AI: 把字段按使用频率排序" prompt 输入

**数据结构** (frontend state):
```ts
interface FormField {
  id: string         // uuid
  code: string       // field_code, e.g. 'leave_f2'
  name: string       // 字段名称, '请假类型'
  type: FieldType    // 19 widget 之一
  placeholder?: string
  required: boolean
  editable: boolean
  ai_validate: boolean
  options?: Array<{ code: string; name: string }>  // for select/radio
  // ... 类型特定 props
}
```

**Backend 接入** (已有, P2 加 reorder):
- list_apaas_app_models?with_fields=true → 拿现有字段
- POST /crud/model-field/add → 新增
- POST /crud/model-field/update → 改名/类型
- POST /crud/model-field/disable → 删 (apaas 不真删)
- **新加 POST /crud/model-field/reorder** — 排序变更 (P2 加 MCP 工具)

### Phase B — 数据 schema 编辑器 (~800 行)

#### B1. 新组件 `DataSchemaEditor.vue`
布局: 全宽 schema view, 顶部信息卡 + tab + 字段 table

**Header** (`SchemaHeader.vue`):
- 表名 (mono, big) + DB type badge (MySQL/PG) + 主表/子表 badge
- 统计行: "N 字段 · M 行 · 主键 X · K 外键"

**4 sub-tab**: Schema / 数据 / SQL / 关系

**Schema tab** — 字段 table:
- 列: # / 字段 / 类型 / NULL / 键 / 默认值 / 注释 / 操作 (8 列)
- 键 badge: PK (蓝) / FK (紫 + → target.column) / IDX (橙) / UNIQ (绿)
- 类型: 完整 SQL 类型 (BIGINT/VARCHAR(16)/DATE/DECIMAL(4,1)/TEXT/TIMESTAMP/...)
- NULL: checkbox (toggle)
- 行内编辑 (click cell → input/select inline)

**Backend**:
- 复用 list_apaas_app_models (返字段元信息)
- 现有 add/update/disable_apaas_model_field MCP
- 暂不支持改类型/索引 (apaas 平台限制), display only

### Phase C — 流程 24 节点 + 属性面板 (~600 行)

#### C1. 扩 ProcessDesignerPanel 节点 list
左 sidebar 改 collapsible 4 分类:
```ts
const NODE_CATEGORIES = [
  { code: 'entry', label: '入口/出口', nodes: [
    { type: 'start', label: '开始', icon: '⏻', color: '#10b981' },
    { type: 'end', label: '结束', icon: '⊗', color: '#dc2626' },
    { type: 'timer', label: '定时触发', icon: '⏰' },
    { type: 'webhook', label: 'Webhook', icon: '🔗' },
  ]},
  { code: 'approval', label: '审批', nodes: [
    { type: 'assignee_approval', label: '指定人审批', icon: '👤' },
    { type: 'role_approval', label: '角色审批', icon: '👥' },
    { type: 'manager_approval', label: '上级审批', icon: '👔' },
    { type: 'parallel_approval', label: '会签 / 或签', icon: '🤝' },
    { type: 'cc', label: '抄送', icon: '📢' },
  ]},
  { code: 'logic', label: '逻辑', nodes: [
    { type: 'condition', label: '条件分支', icon: '⊻' },
    { type: 'multi_branch', label: '多分支', icon: '⋔' },
    { type: 'parallel_gateway', label: '并行网关', icon: '∥' },
    { type: 'merge', label: '汇聚', icon: '⋎' },
    { type: 'wait', label: '等待', icon: '⏳' },
  ]},
  { code: 'action', label: '动作', nodes: [
    { type: 'fill_form', label: '填写表单', icon: '📝' },
    { type: 'write_data', label: '写入数据表', icon: '💾' },
    { type: 'read_data', label: '读取数据', icon: '📖' },
    { type: 'ai_judge', label: 'AI 判定', icon: '✨' },
    { type: 'ai_generate', label: 'AI 生成', icon: '🪄' },
  ]},
]
```

#### C2. 节点属性面板 (`ProcessNodePropsPanel.vue`)
按节点 type 显不同 props:
- approval 节点: 名称 / Key (n3) / 审批人 (人员选择器) / 审批策略 (下拉) / SLA / switches
- condition: 条件表达式 (codemirror)
- write_data: 目标表 / 字段映射
- ai_judge: prompt + 输出变量

#### C3. Backend 接入
- list_apaas_app_processes (复用) / set_apaas_app_process 写回 BPMN
- BPMN XML 生成 — 现有 generator 已支持 (commit 之前的 P0 任务 #49)

### Phase D — 权限矩阵 (~600 行)

#### D1. 新组件 `PermissionMatrix.vue`
布局:
```
+----------+-------------------------------------+
| 角色\资源 | 页面            | 数据      | 流程  |
|          | F1  F2  F3 ...   | T1 T2 ... | P1   |
+----------+-------------------------------------+
| 管理员 3 | 全 全 全          | 全 全     | 全    |
| 审批人 12| 读写 只读 读写    | 只读 读写 | 只读  |
| 发起人 240| 读写 读写 只读   | 禁止 禁止 | 禁止  |
| 查看者 88| 只读 只读 只读    | 禁止 禁止 | 禁止  |
+----------+-------------------------------------+
```

**Header**:
- 标题 + 统计 "4 角色 · 10 授权对象 · 343 成员"
- 右上 toggle "矩阵 (active) / 角色列表"
- "AI 建议 / + 新增角色"

**矩阵 cell**:
- 4 状态: 全部 (X 橙) / 读写 (RW 蓝) / 只读 (R 灰) / 禁止 (灰 disabled)
- click → 弹 dropdown 改状态
- 多 cell select → 批量改

**列分组** (sticky header):
- 页面 (form list 全)
- 数据 (table list)
- 流程 (process list)
- 应用设置

**底部图例**: 全部 X / 读写 RW / 只读 R / 禁止

#### D2. Backend
- list_apaas_app_roles (复用)
- list_apaas_app_menus 拿页面 list
- list_apaas_app_models 拿数据表 list
- list_apaas_app_processes 拿流程 list
- 新 MCP: get_role_resource_matrix(env_id, apaas_app_id) → 返完整矩阵
- 新 MCP: set_role_resource_permission(env_id, role_id, resource_type, resource_id, permission)

## 顶部 nav 对齐 design

design 顶部还有: **构建 / 应用(active) / 数据源 / 接口 / 文档 / 报表 / 模型 / 管理** — 8 个 nav.
我们现状: 首页 / 应用 / 睿鲸 AI Builder / 睿鲸 AI Coding / Vibe Coding / 数据库连接 / DB 问数.

P3 留尾: 主 nav 对齐 (新加"数据源/接口/文档/报表/模型/管理"几个 stub 页), 暂不强求.

## 应用栏对齐 design

design 应用栏: ← 应用列表 | 员工请假审批 + 已发布 chip | 设计/数据/流程/权限/日志 | **开发 / 生产 toggle** | 保存 / 发布到生产

现状: ← 应用 | 图书借阅管理系统 | 自开发 | 部署 | 历史 | 更多 | ↗

差距:
- 缺 "已发布"状态 chip + "开发/生产" 切换 toggle
- 缺 "保存" 按钮 (现有 [部署] 类似)
- "发布到生产" 顶部 CTA (现有"部署"approx)

## 顶部 5 sub-tab 名

design 顶部 5 tab: **设计 / 数据 / 流程 / 权限 / 日志** ← 已对齐 ✓

## 数据 tab vs 设计/数据 sub 决策

**推荐选项 C**:
- 顶部 **数据 tab** = 模型 / 字典 (跟现有保留, 不动)
- 设计 tab 内**新加"数据"sub** = 数据表 schema 编辑器 (类似 design 截图)
- 区别: 数据 tab 是应用全局元数据视图; 设计/数据 是当前选中页面的数据绑定

但用户截图显示数据 tab 直接显 schema 编辑器, 没数据/数据模型分流. 可能 design 没区分这两个层次. **下 session 跟用户对齐**.

## Phase 排序 + 估时

| Phase | Item | 估时 | 行数 |
|---|---|---|---|
| A | FormBuilder (拖拽+组件库+属性) | 6h | ~1500 |
| B | DataSchemaEditor (schema view) | 3h | ~800 |
| C | Process 24 节点 + 属性 | 3h | ~600 |
| D | PermissionMatrix | 3h | ~600 |
| 总 | | 15h | ~3500 |

**3 session 拆**:
- session 1: Phase A (form designer 拖拽)
- session 2: Phase B + Phase D 并行 (schema + 矩阵)
- session 3: Phase C (流程 24 节点扩 + 属性) + 应用栏 polish + handoff

## 关键文件位置 (handoff 用)

```
frontend/src/components/v3/
├── AppConfigTopTabs.vue       (顶部 5 tab, 不动)
├── AppConfigSubNav.vue        (旧 sub-nav, v-if=false, 可删)
├── FormDesignerPanel.vue      (446 行, 重写成 FormBuilderPanel)
├── ListDesignerPanel.vue      (503 行, 重写成完整列设计 + 查询条件)
├── ProcessDesignerPanel.vue   (622 行, 扩 24 节点 + 属性)
├── DataModelDetailPanel.vue   (450 行, 跟 schema editor 合并)
├── DictEditorPanel.vue        (478 行, 保留)
└── RoleManagePanel.vue        (455 行, 加矩阵 view, master-detail 退役)

frontend/src/views/ChatPage.vue
  L180-280  template (mdsh designer shell)
  L2280     SECTION/TOP_TAB 映射
  L2330     DESIGNER_SUBS = [form, list, process, page]
  L11400    .mdsh-* CSS

backend/app/routes/applications/
├── section_content.py    (9 GET list endpoint, 已就绪)
└── crud_endpoints.py     (7 POST CRUD endpoint, 已就绪)
```

## 依赖 (已就绪, 不用再装)

```json
"@antv/x6": "^3.1.7",
"tslib": "^2.8.1",
"vuedraggable": "^4.1.0",  // ← 本 commit 加, 下 session 用
"element-plus": "^2.4.0",  // 已有
"@element-plus/icons-vue": "^2.x"  // 已有
```

## 设计稿 reference

用户截图 4 张 (本 SPEC commit message 链接), 实物路径 (如有保存) 待补.

设计语言: Geist font + 蓝 `#1f72d4` + Inter fallback. tokens 在 `frontend/src/styles/design-v3-tokens.css`.
