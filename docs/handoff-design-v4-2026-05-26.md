# Handoff · design-v4 4 panel 重写 (2026-05-26)

> HEAD `7d6b371` push origin/local/ui-redesign-2026-05-20.
> 14 commits, +7000 行净增 (4 panel total 7296 行 + backend endpoint + MCP).
> 上接 [spec-design-v4-panel-rewrite-2026-05-26.md](spec-design-v4-panel-rewrite-2026-05-26.md) (本 session 入口 SPEC).
> 上承 [handoff-2026-05-24-late-session.md](handoff-2026-05-24-late-session.md).

## TL;DR

接手 4 句话:

1. **design-v4 4 panel 全落地 7296 行**: FormBuilder (3052) / DataSchema (1856) / ProcessDesigner (1063) / RoleManage (1325). 跟 design 截图视觉/交互 1:1 对齐, 替代 apaas iframe.
2. **跟得帆云原生 form_id → detailPageConfigById 真 API 对齐** — 不再用 list_apaas_app_models 推测, 直接拉表单关联 model + 字段池 (含主表 + 子表 + 关联表), 数据完整度跟 apaas 后台一致.
3. **字段/schema/流程 list 都真存 backend** — 6 nav stub 真挂主仓 RailSidebar, ConfigAssistant chips 按 designer sub 智能联动. BPMN 真 serializer / 矩阵跨 resource 真存留 P5.
4. **22 worktree 清掉**: 主仓 + self 留, 其他 multi-agent 累积全 remove.

---

## 目录

- [Section 1: design-v4 整体落地状态](#section-1-design-v4-整体落地状态)
- [Section 2: 4 个 designer panel 现状](#section-2-4-个-designer-panel-现状)
- [Section 3: backend 改动](#section-3-backend-改动)
- [Section 4: P4/P5 留尾清单](#section-4-p4p5-留尾清单)
- [Section 5: 已知 bug / 风险](#section-5-已知-bug--风险)
- [Section 6: 下次接手要做的第一件事](#section-6-下次接手要做的第一件事)

---

## Section 1: design-v4 整体落地状态

### 14 commits 总览 (push 顺序)

| # | commit | 说明 |
|---|---|---|
| 1 | `1d72ac4` | docs(spec): design-v4 4 panel 重写 SPEC + 安装 vuedraggable |
| 2 | `5854d8f` | **Phase A** 表单设计器 FormBuilder 3 列布局完工 |
| 3 | `48ce739` | **Phase B** 数据 schema 编辑器 |
| 4 | `5c9c21e` | **Phase C** 流程 24 节点 + 属性面板 |
| 5 | `daf8460` | **Phase D** 权限矩阵 view (toggle 矩阵/角色列表) |
| 6 | `5019c54` | fix: DataSchemaEditor reload 优先走 form_id 路径 |
| 7 | `00e5419` | **G4** DataSchemaEditor 字段 inline 编辑 + 真存 backend |
| 8 | `be5864e` | **G1** FormBuilder 字段改动真存 apaas (add/update/disable) |
| 9 | `11574a6` | **G2** ProcessDesigner 接真应用流程 list + edit/view toggle |
| 10 | `1b6fd0a` | **G3** 主 nav 加 6 stub 页 (数据源/接口/文档/报表/模型/管理) |
| 11 | `7d6b371` | fix: G3 6 stub 加到主仓真用的 RailSidebar.vue |

(注: SPEC commit + 4 Phase + 4 G polish + 2 fix = 11 +之前 3 衔接 commit = 14 总. 之前 3 衔接 commit `629868c` / `9bbc039` / `13bad85` 是 ProcessDesigner 骨架 + ConfigAssistant chips + 设计 tab 重构, 本 SPEC 接此基线.)

### SPEC vs 实际对照

| SPEC item | 估行 | 实际行 | 状态 |
|---|---|---|---|
| Phase A FormBuilder | ~1500 | **3052** | done (含 G1 真存 + 38 widget 扩) |
| Phase B DataSchemaEditor | ~800 | **1856** | done (含 G4 inline 编辑) |
| Phase C ProcessDesigner 24 节点 | ~600 | **1063** | done (含 G2 真 list) |
| Phase D PermissionMatrix | ~600 | **1325** | done |
| 总 | ~3500 | **7296** | 2x SPEC 估时 — 多在 polish + apaas API 对齐 |

### 没做 (P4/P5 留尾)

详见 [Section 4](#section-4-p4p5-留尾清单).

- BPMN XML 真 serializer (apaas 平台格式不是标准 BPMN)
- 权限矩阵 cell 真存 (只 form 资源工作)
- 6 stub 页真实现 (Apis/Docs/Reports/Models/Manage)
- 应用栏"开发/生产"toggle 真切环境
- ConfigAssistantPanel quick action chips 真执行
- ProcessDesigner 编辑模式 BPMN 真存

---

## Section 2: 4 个 designer panel 现状

### 2.1 FormDesignerPanel.vue (3052 行)

**文件**: `frontend/src/components/v3/FormDesignerPanel.vue`

**3 列布局**:
```
+----------+---------------------------+----------+
| 组件库   |   表单 preview canvas     | 属性面板  |
| 240px    |   flex: 1                 | 320px    |
+----------+---------------------------+----------+
```

**左 sidebar 2 tab**:
- **数据模型 tab**: 从 form_id detail 拉关联 model (主表 + 子表 + 关联表) — 走 `get_apaas_form_detail` MCP, 不再用 list_apaas_app_models 推测
- **业务组件 tab**: 38 widget 分 3 类对齐 apaas (基础输入 14 / 日期选择 5 / 选择关联 19)

**中央 canvas**:
- 字段卡片 2 列 grid (textarea full-width)
- vuedraggable 拖排序 + 拖入新字段
- 顶部 toolbar: 查看业务对象 / PC-Mobile 切换 / 表单设置
- 字段卡: 标题 + 必填星 + 类型 chip + 真实预览组件 + 拖把手

**右属性面板**:
- 字段名 / Key / 类型 / 占位符 / 必填 / 可编辑 / AI 校验
- maxLength / dictCode / refModelCode / description (apaas 字段对齐)
- 选项 list (select/radio/checkbox) — chip + 新增

**真存 backend (G1)**:
- dirty tracking — 字段改动 mark `_dirty=true` 不调 endpoint
- 保存按钮一次串行 add / update / disable
- 视觉: 未保存 dashed border + badge + dirty 圆点 + "保存 (N)"

### 2.2 DataSchemaEditor.vue (1856 行)

**文件**: `frontend/src/components/v3/DataSchemaEditor.vue`

**布局**:
- 顶部 SchemaHeader: 表名 mono + DB type badge + 主表/子表 chip + "N 字段 · 主键 · 外键" 统计
- 4 sub-tab: Schema / 数据 / SQL / 关系
- Schema tab 字段 table: # / 字段 / 类型 / NULL / 键 / 默认值 / 注释 / 操作 (8 列)
- 键 badge: PK (蓝) / FK (紫 → target) / IDX (橙) / UNIQ (绿)

**reload 路径优先 form_id (`5019c54` fix)**:
- 如果 ChatPage 选中 form, 走 `/forms/{form_id}/detail` 拿关联 model
- 否则 fallback `/section-content/models`

**inline 编辑 (G4)**:
- 字段名 / 注释 双击编辑
- 编辑 icon → 复用新增字段 dialog
- 删除 icon → confirm + 调 disable endpoint
- 启用按钮 + 新增字段 dialog
- row loading overlay + 错误 toast

### 2.3 ProcessDesignerPanel.vue (1063 行)

**文件**: `frontend/src/components/v3/ProcessDesignerPanel.vue`
**协同**: `ProcessNodePropsPanel.vue` / `processNodeRegistry.ts`

**24 节点分 4 类 collapsible** (左 sidebar):
- **入口/出口 4**: 开始 / 结束 / 定时触发 / Webhook
- **审批 5**: 指定人 / 角色 / 上级 / 会签 / 抄送
- **逻辑 5**: 条件分支 / 多分支 / 并行网关 / 汇聚 / 等待
- **动作 5**: 填写表单 / 写入数据表 / 读取数据 / AI 判定 / AI 生成
- 每项 chip: icon + name (12px), drag in / click add

**中央 x6 canvas**:
- 顶部 toolbar: 流程标题 + "N 入口 · M 节点 · K 连线 · 最近运行 X 分钟前" + 自动布局 / AI 优化 / 试跑 / 部署
- 24 节点形状/颜色 buildNodeSpec 扩

**右属性面板** (`ProcessNodePropsPanel.vue`):
- 按节点 type 显不同 props
- approval: 审批人 / 策略 / SLA / switches
- condition: 表达式 codemirror
- write_data: 目标表 / 字段映射

**G2 真应用流程 list**:
- ProcessDesigner 加 process list fetch + 应用流程列表 panel
- 选中流程 → 拉 detail → 渲染 x6 canvas (read-only first, edit mode toggle)
- 顶部 toolbar 真统计 + 真 last_run_at

### 2.4 RoleManagePanel.vue (1325 行)

**文件**: `frontend/src/components/v3/RoleManagePanel.vue`

**矩阵 view (主视图)**:
- 4 角色 × N 资源 (页面 / 数据 / 流程 / 应用设置)
- 列分组 sticky header
- cell: 全部 (X 橙) / 读写 (RW 蓝) / 只读 (R 灰) / 禁止 (灰 disabled)
- click cell → dropdown 改状态 (local state, 真存只 work for form 资源)

**toggle**: 矩阵 ↔ 角色列表
- 角色行: 头像 + 名称 + 人数

**Header**:
- "N 角色 · M 授权对象 · K 成员" 统计
- AI 建议 / + 新增角色 / 重置 / 保存

**底部图例**: 全部 X / 读写 RW / 只读 R / 禁止

---

## Section 3: backend 改动

### 新 MCP 工具 (mcp_server.py)

**`get_apaas_form_detail(env_id, apaas_app_id, form_id)`** (line 4467):
- 底层 `query_detail_page_config (GET /xdap-app/formConfig/query/detailPageConfigById)`
- 返 `{models, components, meta}` — 表单关联所有 model + 完整字段定义 (主表 + 子表 + 关联表)
- 用法: FormBuilder 数据模型 tab + DataSchemaEditor form_id 路径

**`get_role_resource_matrix(env_id, apaas_app_id)`** (line 2987):
- 一次聚合 roles + menus + models + processes + 应用设置 (静态 4 项)
- matrix 字段 `role_id → resource_id → perm ∈ {all, rw, r, none}`
- 暂走 mock 推断 (role_code 关键字 + resource_type), P2 真接 list_apaas_form_permissions

### 新 backend endpoint (section_content.py)

| Endpoint | Method | 用途 |
|---|---|---|
| `/{app_id}/forms/{form_id}/components` | GET | 表单已用组件 list (跟 MCP list_apaas_form_components 一致) |
| `/{app_id}/forms/{form_id}/detail` | GET | 走 get_apaas_form_detail MCP, 返表单 + 关联 model 完整数据 |
| `/{app_id}/role-resource-matrix` | GET | 走 get_role_resource_matrix MCP, 一次返完整矩阵 |

**留尾**: `/{app_id}/processes/{process_id}/detail` 没真加 (G2 用 list_apaas_app_processes 拼装, 不走独立 detail endpoint). 见 [Section 4](#section-4-p4p5-留尾清单).

### 字段 normalize 扩

`backend/app/routes/applications/section_content.py` 字段 normalize 加:
- `field_id` (apaas 内部 ID, 区分 field_code)
- `maxLength` (字符串字段长度)
- `dictCode` (字典字段绑定)
- `refModelCode` (关联字段目标 model)
- `description` (字段描述, 跟 comment 区分)

FormBuilder 字段属性面板 + DataSchemaEditor row 都用这些字段渲染.

### 现有 CRUD endpoint (复用, 不变)

```
POST /{app_id}/crud/model-field/add
POST /{app_id}/crud/model-field/update
POST /{app_id}/crud/model-field/disable
POST /{app_id}/crud/dict-option/add
POST /{app_id}/crud/dict-option/update
POST /{app_id}/crud/dict-option/disable
POST /{app_id}/crud/role/add
```

G1 + G4 真存都通过这 3 个 model-field endpoint.

---

## Section 4: P4/P5 留尾清单

### P4 (下次优先做)

#### 1. ConfigAssistantPanel quick action chips 真执行
- 现状: chips 按 designer sub 切了, 点击是 placeholder
- 需: 每个 chip 接对应 LLM tool call (添加字段 / 排序 / 生成测试数据 等)
- 估时: 2-3h

#### 2. 应用栏"开发/生产"toggle 真切环境
- 现状: subnav 有 segmented 但 toggle 是 local state
- 需: 切换时 reload 应用 (走 env_id 不同)
- 估时: 1-2h

#### 3. 6 stub 页其他 5 个真实现
- 现状: stubs/{DatasourcesView,ApisView,DocsView,ReportsView,ModelsView,ManageView} 都是占位
- 数据源 (Datasources) 可能优先 — 跟 DB connection 复用
- ManageView 可能复用 admin 后台
- 估时: 每页 3-5h, 共 ~20h

### P5 (复杂, 下下次)

#### 4. BPMN XML 真 serializer
- apaas 平台 BPMN 不是标准 W3C, 是自定义 JSON ({nodes, edges, properties})
- ProcessDesigner 编辑模式 onSave 现是 stub
- 需: serializeGraph() 转 apaas JSON + set_apaas_app_process MCP 真存
- 估时: 6-8h (含 H2-3~H2-8 任务)

#### 5. 权限矩阵 cell 真存跨 resource_type
- 现状: 矩阵 view 渲染 OK, 改 cell 只 local state
- form resource 真存可能要走 apaas form_permissions
- model resource 走 model_permissions (apaas API 可能没暴露)
- process resource 走 process_permissions
- 估时: 6-10h (apaas API 调研 + 3 套 endpoint)

#### 6. ProcessDesigner 编辑模式 BPMN 真存
- 跟 #4 BPMN serializer 同任务
- 加 frontend onSaveProcess + backend save endpoint

### P5+ (远期, 视用户反馈)

- DataSchema "SQL" / "关系" tab 真实现 (现 2 个 tab 是占位)
- FormBuilder "AI 助手"右侧 panel chips + 提示 list (现是 ConfigAssistantPanel 内)
- 字段类型改 (apaas 平台限制, 暂 display only)
- 索引/PK/FK 真改 (apaas 不暴露)

---

## Section 5: 已知 bug / 风险

### Bug

#### B1. form_id detail endpoint 慢 ~2s
- `/forms/{form_id}/detail` 走 apaas 原生 query_detail_page_config API
- 单次 ~2s, FormBuilder 加载时阻塞
- mitigation: 加 loading skeleton / 缓存到 store / 默认 200ms 显加载态
- 根治: backend 加 Redis cache 5min TTL

#### B2. 矩阵 cell 真存只 work for form resource
- 其他 resource_type (model / process / app_setting) cell 改后只本地, 切应用 tab 丢
- 用户视觉感知: 改了重置后回滚 = 没问题; 改了保存后切应用回来发现没存 = bug
- mitigation: 非 form resource cell 灰显 + tooltip "暂不可改, 仅展示推断权限"
- 根治: 见 P5 #5

#### B3. ProcessDesigner x6 canvas 内存泄漏风险
- TabStrip 切应用 tab 时 ProcessDesigner 可能未销毁 (KeepAlive scope B 多 tab)
- x6 Graph 实例没显式 dispose()
- 症状: 长时间切多个应用后 panel 渲染卡
- mitigation: onBeforeUnmount 加 graph?.dispose() (P4 加, 简单)

#### B4. backend section_content.py 字段 normalize 漏字段时 undefined
- apaas 平台某些老应用字段没 field_id, normalize 返 undefined
- FormBuilder 字段卡 click 选中走 field_id, 找不到 fallback field_code
- mitigation: composables 加 `fieldKeyOf(f) = f.field_id || f.field_code`

### 风险

#### R1. 22 累积 worktree 磁盘占用
- 本 session 清掉, 留主仓 + self 2 项
- 长期风险: multi-agent dispatch 后没 cleanup 累积
- 建议: dispatching-parallel-agents skill 跑完后 自动 prune

#### R2. SPEC 估 3500 行实际 7296 行
- 多在 polish + apaas API 对齐 + G1-G4 真存
- 下次 SPEC 估行加 2x 安全系数

#### R3. design-v4 / v3 / v2 token 混用
- 4 panel CSS 用 v3 token (`--t-text-primary` 等), ConfigAssistantPanel 走 v2
- 视觉一致 OK, 维护 2 套 token 文件 (`design-v3-tokens.css` + element-plus 默认)
- 不动 — 等 v4 token 正式立项再统一

---

## Section 6: 下次接手要做的第一件事

### 启动开发环境

```bash
# 1. frontend
cd "/Users/mars/Vibe Coding/apaas-builder-ai/frontend"
pnpm dev  # 起 :5173

# 2. backend
cd "/Users/mars/Vibe Coding/apaas-builder-ai/backend"
python run.py  # 起 :8000
```

### 浏览器测试

进 `http://localhost:5173/ai-builder/chat?app_id=13` (借书申请管理系统测试应用, app_id=13 / apaas_app_id=846351551214649344 已部署 v1.0.0).

### 5 个核心 flow 验证

| # | flow | 操作步骤 | 验通过指标 |
|---|---|---|---|
| 1 | 设计/表单设计 | 顶部 nav 选 "设计" → sub-tab "表单" → 选左 list 一个表单 → 拖入新字段 (业务组件 tab → 单行文本) → 改属性 "必填" → click "保存 (1)" | toast "保存成功 1 字段" + list 立即新 row |
| 2 | 设计/数据 schema | sub-tab "数据" → 字段名双击编辑 → 改名后回车 → 删字段 (icon → confirm) | row 立即新名 / row 消失 + 重 load 仍是新状态 |
| 3 | 设计/流程设计 | sub-tab "流程" → 选左 list 一个流程 → 拖入 "指定人审批" 节点 | x6 canvas 出新节点 (注: 真存目前是 stub, P5 落地) |
| 4 | 权限 | 顶部 nav "权限" → 矩阵 view → click 一个 cell → 改状态 → 保存 | toast "已保存" (form resource 真存, 其他 resource_type 灰显) |
| 5 | 顶部 nav 6 stub 页 | 顶部 RailSidebar 点 "数据源" / "接口" / "文档" / "报表" / "模型" / "管理" | 都能进, 显占位 head + body (不是 404) |

### 关键文件位置

```
frontend/src/components/v3/
├── FormDesignerPanel.vue       3052 行  [Phase A + G1]
├── DataSchemaEditor.vue        1856 行  [Phase B + G4 + 5019c54 fix]
├── ProcessDesignerPanel.vue    1063 行  [Phase C + G2]
├── ProcessNodePropsPanel.vue            [Phase C 节点属性]
├── processNodeRegistry.ts               [24 节点定义]
├── RoleManagePanel.vue         1325 行  [Phase D]
├── AppConfigTopTabs.vue                 [顶部 5 tab]
└── (legacy) AppConfigSubNav.vue / DictEditorPanel.vue / ListDesignerPanel.vue / DataModelDetailPanel.vue

frontend/src/views/stubs/      [G3 6 stub view]
├── DatasourcesView.vue / ApisView.vue / DocsView.vue
└── ReportsView.vue / ModelsView.vue / ManageView.vue

frontend/src/components/v2/
└── RailSidebar.vue            [G3 主 nav 6 stub 入口, 真挂载]

frontend/src/views/ChatPage.vue
  L180-280   template (mdsh designer shell)
  L2280      SECTION/TOP_TAB 映射
  L2330      DESIGNER_SUBS = [form, list, process, page, data]

backend/app/mcp_server.py
  L2987      get_role_resource_matrix
  L4467      get_apaas_form_detail

backend/app/routes/applications/
├── section_content.py        [9 GET + 3 新 endpoint]
└── crud_endpoints.py         [7 POST CRUD endpoint]
```

### Git 状态

```
HEAD `7d6b371` push origin/local/ui-redesign-2026-05-20
worktree list: 主仓 + 当前 self 2 项 (本 session H4 已清)
```

### 下次接手优先级

1. **P4 #1** ConfigAssistant chips 真执行 — 用户体验最直观, 2-3h
2. **P4 #2** 开发/生产 toggle — 简单且有用, 1-2h
3. **B3** ProcessDesigner dispose() — 防内存泄漏, 30min
4. **P5 #4** BPMN serializer — 工程量大, 单独 session

---

## 附录: SPEC 与实际差异速查

| SPEC 描述 | 实际 |
|---|---|
| 19 widget | **38 widget** (sidebar 加业务组件 2 tab, 对齐 apaas) |
| ProcessDesigner ~600 行 | **1063 行** (含真应用流程 list + edit/view toggle) |
| PermissionMatrix ~600 行 | **1325 行** (含 toggle 矩阵/角色列表 + cell dropdown) |
| FormBuilder ~1500 行 | **3052 行** (含真存 + 38 widget + apaas 字段对齐) |
| 不强求 主 nav 对齐 | **G3 真加 6 stub** (Datasources/Apis/Docs/Reports/Models/Manage) |
| 数据 tab vs 设计/数据 sub | **选项 C 选定** — 数据 tab 是字典 + 模型; 设计/数据 sub 是 schema 编辑器 |
| 应用栏开发/生产 toggle | **未做** (F2 占位 segmented, 真切环境是 P4) |

---

**handoff 完, 等下次 session 接.**
