# 表单级权限上设计器 — 设计 Spec

**日期**：2026-05-29
**分支**：`local/ui-redesign-2026-05-20`（⚠️ 共享分支 → 路径限定提交 `git commit -- <path>`）
**状态**：待用户评审（brainstorm 已定方向，用户多次"你定"授权推进到 spec/plan）
**所属**：权限"就近配"方向第一刀（独立功能，非视觉收口线）
**前置**：视觉收口 session 已落地（HEAD `6ab0ad8`，含 designer 面板状态组件/token + 删全族「用对话改」死按钮）。

---

## 一句话

把**表单级权限**（角色 × 这个表单 × 查看/编辑/删除/新增/导入… + 数据范围）从中心「权限」矩阵里"拆出来、就近配"到**表单设计器的第 5 个子 tab「权限」**，用现成的真 apaas API（`list_apaas_form_permissions` 读 + `set_apaas_form_permissions` 读-改-写整表覆盖）。**不做字段级**（apaas 无现成 API，需侦察，留专项），不做菜单可见性，不删中心矩阵（留作总览）。

---

## 决策（brainstorm + 用户"你定"已定）

| 维度 | 决策 | 依据 |
|---|---|---|
| target | **表单级**权限（非字段级） | 字段级 apaas 无可集成 API（侦察 spike 才知道）；表单级有现成真 API |
| 放置 | 设计器**第 5 个子 tab「权限」**（表单/列表/流程/schema/**权限**） | 用户选；跟 designer 子 tab 结构一致，最"就近" |
| 数据模型 | apaas 表单权限：数据权限(查看/编辑/删除 + 数据范围) + 操作权限(新增/导入/…) | apaas `detailPageConfigById` 返回的 `advancedPermissionGroups`/`operationPermissionGroups` |
| 默认列 | 查看/编辑/删除/新增/导入 + 每行**数据范围**(全部/仅本人/本部门);其余(暂存/批量删/批量审批/分享/复制新增)收进「更多」 | 避免一上来矩阵过密 |
| 写入 | `set_apaas_form_permissions` **读-改-写整表覆盖**;form_code 后端内部查 | apaas 是 overwrite API，必须先 list 再合并再 set，否则清掉别的角色 |
| 中心矩阵 | **保留作总览**，不删 | 两者同一 RMW API → 数据一致;保留鸟瞰 |
| 范围外 | 字段级权限、菜单可见性、删中心矩阵 | 各留专项 |

---

## 真 apaas API（实证，写计划/实现时按 anchor 重读核对）

> ⚠️ 行号是 anchor 提示;本机工具间歇返损坏，实现前先 Read 真实区域核对。

- **读** `list_apaas_form_permissions`：`backend/app/mcp_server.py:~4779` → `apaas_client.query_detail_page_config()`（`GET /xdap-app/formConfig/query/detailPageConfigById?formId&appId`）。返回 `data_permissions[]`（subject{role_type,role_id,role_name} + can_view/can_edit/can_delete）+ `operation_permissions[]`（can_add/can_import/can_draft/can_copy_add/can_batch_*/can_share_form）。
- **写** `set_apaas_form_permissions`：`mcp_server.py:~5080` → `apaas_client.create_form_permissions()`（`POST /common/resource/formPermission`）。payload 由 `_build_perm_payload_from_simple_rules`（`:~4983`）构建：`{formCode, appId, tenantId, formId, dataPermissionGroups[], operationPermissionGroups[]}`，每组带 `permissionOperationType{...bool}` + `permissionObjects[{permissionObjectType:'ROLE_USER', permissionObjectValue:role_id, permissionRange{rangeType:'ALL'|'SELF'|...}}]`。**整表覆盖**。
- **现成 RMW 范例** `set_role_resource_permission`：`mcp_server.py:~3342` —— 中心矩阵 form cell 走的就是它（读 list → 排除目标角色 → 合并新规则 → set 全量;form_code 由 `list_apaas_app_menus` 反查 resource_id→form_id→form_code）。**本刀照它的范式做**。

---

## 架构

### 前端

**1. 新组件 `frontend/src/components/v3/FormPermPanel.vue`**
- props：`{ appId:number, apaasAppId:string, envId:number, formId:string, menuName?:string }`（ChatPage designer shell 现有 `selectedApaasMenuFormId` 等可传）。
- 渲染 **角色 × 动作 矩阵**：行=角色，列=默认动作(查看/编辑/删除/新增/导入) + 末列**数据范围**下拉(全部/仅本人/本部门);「更多」展开其余操作权限列。复用 RoleManage 矩阵视觉 + `<SkeletonCard>`(加载)/`<EmptyState>`(无角色)/`<ErrorCard>`(错误) + `<BaseBadge>`。
- preview/edit 双模式(同其它 designer 面板 + "业务视角预览"banner)。preview 只读;edit 可勾选 + 改数据范围 + 保存。
- 加载：拉角色列表 + `GET .../forms/{formId}/permissions` → 归一成矩阵。
- 保存：收**完整** 角色×权限 集 → `POST .../forms/{formId}/permissions` → 重载。

**2. `frontend/src/views/ChatPage.vue` 接线**
- `DESIGNER_SUBS` 加 `{ code:'perm', label:'权限' }`（现为 form/list/process/data）。
- mdsh-body：`designerSub === 'perm'` 时渲染 `<FormPermPanel :app-id :apaas-app-id :env-id :form-id :menu-name />`。
- **只加分支，不动其它 designer 子 tab 逻辑。**

**3. 类型**：新增 perm 矩阵的 TS interface（角色行 + 动作布尔 + 数据范围枚举）。

### 后端 `backend/app/routes/applications/`（2 路由，照 `set_role_resource_permission` 范式）

- **`GET /applications/{app_id}/forms/{form_id}/permissions`**：app_id → 反查 apaas_app_id + env_id（同其它 section_content 端点）→ 取角色列表(`/section-content/roles` 或 `/role-resource-matrix` 复用，确切来源见待澄清1) + `list_apaas_form_permissions(form_id)` → 归一成 `{roles:[], matrix:{role_id:{view,edit,delete,add,import,...,range}}}` 返回。
- **`POST /applications/{app_id}/forms/{form_id}/permissions`**：收完整矩阵 → 内部查 form_code(`list_apaas_app_menus`) → `_build_perm_payload_from_simple_rules` → `set_apaas_form_permissions`（**RMW 整表覆盖**）→ 返回结果。

---

## 数据流

```
designer 选 MODEL 菜单(有 formId/apaasAppId/envId) → 点「权限」子 tab
  → GET forms/{formId}/permissions → 角色 + 当前表单权限 → 矩阵渲染
edit 模式勾选/改数据范围 → 保存
  → POST(完整矩阵) → 后端查 form_code → RMW set_apaas_form_permissions → 重载
```

---

## 验收标准

1. app_id=22 选一个表单 → 「权限」子 tab 显**真**角色×动作矩阵(读自 apaas，非 mock)。
2. edit 模式改某角色某动作 → 保存 → 重载后保持;**且其它角色权限未被清**(RMW 正确性，最关键)。
3. 中心「权限」→角色矩阵的 form cell 与此处一致(同一 API)。
4. preview/edit 模式、加载/空/错误态正常(复用共享组件)。
5. vue-tsc `-b` 零新增(基线 402)。浅+暗渲染正常。

---

## 风险与缓解（**写 apaas 是最大风险**）

| 风险 | 缓解 |
|---|---|
| **overwrite 清掉别的角色**(set 是整表覆盖) | 严格 RMW：保存前必 list 当前全量 → 合并 → set 完整集;照 `set_role_resource_permission` 范式;**首次真写前先只读验 + 拿测试角色小心验**，确认 RMW 后再放开 |
| 改的是**真部署应用**生产权限数据(app_id=22) | 实现阶段：先把**读**跑通验证(只读零风险);写之前**停下找用户确认**(难撤销/对外) |
| form_code 反查失败 | 照 set_role_resource_permission 的 list_apaas_app_menus 反查;查不到给明确错误不静默 |
| 数据范围 rangeType 语义不全 | 默认只暴露 ALL/SELF/CURRENT_USER_DEPT 三种;其余 apaas range 类型留 P2 |
| 触"铁律"(动 apaas/低代码) | 用的是 apaas **官方权限写 API**(非破坏);ChatPage 只加 designer 子 tab 分支不动既有逻辑 |
| 本机工具间歇损坏 | anchor 行号先 Read 核对;精密改动交叉验证 |

---

## 铁律 / 非目标

- **非目标**：字段级权限(需 apaas 侦察 spike，留专项)、菜单可见性、删除/重构中心角色矩阵、ProcessDesigner/SpecDesign 相关。
- ChatPage 改动限定：**只**加 `DESIGNER_SUBS` 一项 + 一个 `v-else-if` 渲染分支。

---

## 执行纪律（写进 plan）

1. **先做读**(GET 端点 + FormPermPanel 只读渲染) → 验证真数据 → 提交。
2. **写端点 + edit 模式**单独一刀,**第一次真写 apaas 前停下找用户确认**,首写用测试角色验 RMW 不误清。
3. 每步 vue-tsc 零新增 + 浅/暗截图 + 路径限定提交。

---

## 待澄清(写计划时定，非阻塞)

1. `list_apaas_app_roles` 的确切端点/返回(取角色行用) —— 实现前 grep 核。
2. 数据范围 `rangeType` 的完整可选集 + 中文标签映射 —— 读 apaas 返回样本定。
3. FormPermPanel 与 RoleManagePanel 矩阵组件能否抽公共(YAGNI：先各写，重复明显再抽)。
