# Builder 真实数据化 — 列表 + 权限矩阵去 mock

- 日期: 2026-05-31
- 状态: 设计待评审
- 涉及面板: `ListDesignerPanel.vue`(列表设计) / `RoleManagePanel.vue`(权限) + 少量 backend
- 前置: 子表 scoped 样式修复 (另一条改动, 与本 spec 无关)

## 1. 背景与目标

用户在「列表设计」tab 看到列表显示假数据(企业全称1..5)、行「编辑」弹"P1 接入"占位，质疑功能没做完。盘点后确认 builder 里存在三类 mock，目标是**把它们换成真实数据 / 真实行为**，无真实数据时显诚实的空态而非假数据。

## 2. 范围

**In(本 spec 覆盖):**
- 列表数据行 (ListDesignerPanel)
- 列表行 查看 / 编辑 (P1 占位)
- 角色×资源权限矩阵 (RoleManagePanel)

**Out(明确不做):**
- 权限**写**端 (`set_apaas_form_permissions`) — 已知破坏性 bug(清空读端权限组), 保持禁用现状
- 记录级深链 (带 recordId 的 apaas 编辑页 URL) — 格式无把握, 列为后续增强
- USER/DEPT 个人/部门授权主体 — 留 P2(与现有 `get_form_permissions` 设计一致)
- SpecDesignPanel / SpecChatPanel 的 P2 占位 — 属 spec 线, 不在本次

## 3. 现状盘点

| 类别 | 现状 | 真实端点 |
|---|---|---|
| 列表数据行 | 0 条/拉取失败时 `buildMockRows` 造 5 行假数据 (`MOCK_NAMES`/`MOCK_BOOKS`) | ✅ 已有 `GET /{app_id}/forms/{form_id}/business-data` → apaas `query_apaas_business_data` |
| 行 查看/编辑 | `onRowView`/`onRowEdit` 直接 `alert('...P1 接入...')` | 查看可复用已拉行数据; 编辑用 `get_app_runtime_url`(`access_url`) |
| 权限矩阵 cell | `get_role_resource_matrix` MCP(`mcp_server.py:3095`) 按角色名**推断**, `is_mock=true` | ✅ 读路径已被 `get_form_permissions`(section_content.py:449, 读 `list_apaas_form_permissions`) 验证可行 |

> 注: `数据源`/`mockup` 等匹配多为「数据源」tab 标签, 非 mock 数据。

## 4. 设计

### P1 — 列表 0 条显空态 (小 / 低风险)

- **改动**: `ListDesignerPanel` 数据加载逻辑 (`loadData`, ~line 700-720): 真实拉取成功但返 0 条 → 设 `dataSource='empty'`(新增态), **不再** `buildMockRows`。拉取失败(异常) → `dataSource='error'` 显重试。
- **UI**: 复用 `EmptyState` 组件 (`title="该列表暂无数据" desc="..." #cta` 放「打开应用录入」按钮)。
- **清理**: 删 `MOCK_NAMES`/`MOCK_BOOKS`/`buildMockRows` 及 `dataSource==='mock'` 分支 + `mock 数据` tag。
- **数据流**: 真实 row 有数据→真表; 0 条→空态+CTA; 失败→错误态+重试。

### P2 — 行「查看」detail 抽屉 (中 / 低风险)

- **改动**: `onRowView(row)` 不再 alert; 打开右侧 Drawer。
- **组件**: 抄 `DeployHistoryDrawer.vue` 模式新建轻量 detail 抽屉(或内联 `el-drawer`); 按 `visibleColumns` 渲染 `label: renderCell(row, col)` 全字段。
- **数据**: **直接用列表已拉到的 `row` 对象, 零新端点**。
- **边界**: 字段多时抽屉内滚动; 空值显 `—`。

### P3 — 行「编辑」深链真应用 (中 / 低风险)

- **改动**: `onRowEdit(row)` → 调新 `GET /{app_id}/app-runtime-url`(包 `get_app_runtime_url` MCP) 拿 `access_url` → `window.open(access_url, '_blank')`。
- **v1 粒度**: 应用级 access_url(`get_app_runtime_url` 返的就是应用入口)。表单/记录级深链留后续。
- **错误**: `ok=false`(未部署/无 access_url) → toast 友好提示, 不静默。
- **空态 CTA 复用同逻辑** (P1 的「打开应用录入」按钮)。

### P4 — 权限矩阵接真实读 (中 / 中风险)

- **改动**: `get_role_resource_matrix` MCP(`mcp_server.py:3095`) 内部对每个 form 资源调 `list_apaas_form_permissions`(已验证可读), 填真实 cell; 拿到真值则 `is_mock=false`。
- **主体 v1**: `__ALL_USER__` 行 + 命名角色; USER/DEPT 不进矩阵(留 P2)。
- **前端**: `RoleManagePanel` 无需改结构(已读 `is_mock`); `is_mock=false` 时自动去掉"推断值"footer 提示。
- **写**: `set_apaas_form_permissions` / `set-cell` 端**保持现状禁用/不动**(破坏性 bug)。
- **降级**: 某资源读权限失败 → 该资源 cell 回退推断 + 整体 `is_mock=true`(诚实标注), 不编造。

## 5. 决策记录

1. 编辑深链 = **应用级 access_url**(简单稳健), 记录级深链后续。
2. 空态**带** CTA「打开应用录入」(复用 P3 runtime URL)。
3. 权限矩阵 v1 = **ALL_USER + 命名角色, 只读**。

## 6. 测试与验证

- **P1**: SRM供应商档案管理(0 条)→ 显空态+CTA(非假行); 找一个有数据的表单→显真数据。`vue-tsc -b` 无新增错误。
- **P2**: 有数据表单点「查看」→ 抽屉显该行全字段, 值正确。
- **P3**: 点「编辑」→ 新标签打开真应用(access_url 正确); 未部署应用→友好报错。
- **P4**: 权限 tab → cell 为真实读值(对比 apaas 原生权限配置), footer "推断值"提示消失; 某资源读失败→诚实回退。
- 真机验证走 vite HMR(用户本地栈连真后端); 后端改动需重启后端生效。

## 7. 分阶段交付

P1 → P2 → P3 → P4 顺序实现(每阶段可独立提交/上线)。P1-P3 纯前端+1 个轻量后端代理端点; P4 改 MCP 工具(最重, 单独验)。

## 8. 风险

- P4 贴近权限**写** landmine — 严格只读, 写端一行不碰。
- `get_app_runtime_url` 依赖应用已部署(`apaas_app_id` 存在), 未部署需友好降级。
- 共享分支(`local/ui-redesign-2026-05-20`) — 路径限定提交, 防并行 session 交织。
