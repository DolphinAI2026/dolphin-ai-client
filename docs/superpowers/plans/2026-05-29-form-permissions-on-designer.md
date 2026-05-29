# 表单级权限上设计器 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans（本刀含真 apaas 写 + preview 验证，inline 执行最稳）。Steps 用 checkbox（`- [ ]`）。

**Goal:** 在表单设计器加第 5 个子 tab「权限」，原生配 角色×表单 权限(查看/编辑/删除/新增/导入 + 数据范围)，读写真 apaas(`list/set_apaas_form_permissions`，读-改-写整表覆盖)。

**Architecture:** 新组件 `FormPermPanel.vue`(矩阵**照 `RoleManagePanel.vue` 读着写** —— 同款 role×col 矩阵 + preview/edit + 复用 `states/` 组件 + BaseBadge) + ChatPage 加一个 designer 子 tab 分支 + 后端 2 路由(GET 读归一 / POST 读-改-写)，全照现成 `set_role_resource_permission` 范式。

**Tech Stack:** Vue3 `<script setup lang=ts>`、Element Plus、FastAPI(`backend/app/routes/applications/`)、apaas MCP 工具、vue-tsc `-b` 基线对比、preview 截图验证。

**Spec:** [docs/superpowers/specs/2026-05-29-form-permissions-on-designer-design.md](../specs/2026-05-29-form-permissions-on-designer-design.md)（`a726537`）

---

## 铁律 / 安全闸（每个 task 适用）

1. **apaas 写是 overwrite** —— `set_apaas_form_permissions` 整表覆盖。保存前**必须** list 当前全量 → 合并 → set 完整集，否则清掉别的角色。照 `set_role_resource_permission`(`backend/app/mcp_server.py:~3342`)的 RMW 范式。
2. **🚨 第一次真写 apaas 前停下找用户确认** —— app_id=22 是真部署应用，改的是生产权限数据(难撤销)。Phase A(读)随便跑;Phase B(写)第一次 set 前**必须**人工确认 + 拿测试角色验 RMW 不误清其它角色。
3. **ChatPage 改动限定**：只加 `DESIGNER_SUBS` 一项 + 一个 `v-else-if` 渲染分支，不动既有 designer 逻辑。
4. **先读真代码再改**：下文 anchor 行号是起点，本机工具偶发损坏 → 改前 Read 核对。
5. 全程 token 用 `var(--xxx)`;vue-tsc `-b --force` 零新增(基线 402)。

---

## Verification Protocol（task 引用，不重抄）

- **P-类型**：`cd frontend && ./node_modules/.bin/vue-tsc -b --force 2>&1 | grep -c "error TS"` ≤ 402。
- **P-视觉**：preview(`preview_list` 取 frontend serverId)→ `/ai-builder/chat?app_id=22` → 选一个 MODEL 菜单 → 点「权限」子 tab → 截图(浅 + 暗，暗色用 `document.documentElement.setAttribute('data-theme','dark')`)。
- **P-apaas 一致性**(Phase B)：保存后用 GET 端点 / 中心矩阵复查，确认目标角色改了、**其它角色权限未变**。

---

## File Structure

**新建**
- `frontend/src/components/v3/FormPermPanel.vue` —— 角色×动作 权限矩阵(读优先实现，再加 edit/save)

**修改**
- `frontend/src/views/ChatPage.vue` —— `DESIGNER_SUBS` + mdsh-body 渲染分支
- `backend/app/routes/applications/section_content.py`(或同目录新文件 `form_permissions.py`，按既有组织风格) —— GET + POST 两路由

**只读参考(实现时 Read，不改)**
- `frontend/src/components/v3/RoleManagePanel.vue` —— 矩阵 UI / load / save 模板
- `backend/app/mcp_server.py` —— `list_apaas_form_permissions(~4779)` / `set_apaas_form_permissions(~5080)` / `_build_perm_payload_from_simple_rules(~4983)` / `set_role_resource_permission(~3342)`

---

# Phase A —— 读片（零 apaas 写，安全）

## Task 1：后端 GET 读端点

**Files:** Modify `backend/app/routes/applications/section_content.py`（或新建 `form_permissions.py` 并在 `__init__` 注册，按目录现有风格 —— 先 Read 一个现有端点确认组织方式）

- [ ] **Step 1** Read 一个现有 section_content GET 端点(如 `get_section_content_roles`)+ `set_role_resource_permission` 的读半段，抄 app_id→apaas_app_id/env_id 解析 + MCP 调用 + 角色获取方式(`/section-content/roles` 复用)。
- [ ] **Step 2** 加 `GET /applications/{app_id}/forms/{form_id}/permissions`：解析 env/apaas_app_id → 取角色列表 + 调 `list_apaas_form_permissions(env_id, apaas_app_id, form_id)` → 归一成：
```json
{ "ok": true,
  "roles": [{"role_id":"...","role_name":"..."}],
  "matrix": { "<role_id>": {"view":bool,"edit":bool,"delete":bool,"add":bool,"import":bool,"range":"ALL|SELF|CURRENT_USER_DEPT"} },
  "is_mock": false }
```
（`view/edit/delete` 来自 data_permissions、`add/import` 来自 operation_permissions、`range` 来自 permissionRange.rangeType;映射规则照 `list_apaas_form_permissions` 返回字段。）
- [ ] **Step 3** 失败路径：apaas 401 套 `call_apaas_with_relogin`(参 [[apaas_401_root_cause_2026_05_29]] 教训：读接口别裸调);form 无权限配置返空矩阵 + `ok:true`。
- [ ] **Step 4** 手测：`curl` 本地 `GET /api/applications/22/forms/<formId>/permissions`(formId 用 app_id=22 某表单，从 `list_apaas_app_menus` 或 UI 拿) → 看返真矩阵。**改后端必重启**(run.py reload=False)。
- [ ] **Step 5** Commit：`git commit -m "feat(perm): 后端读表单级权限端点(归一成角色×动作矩阵)" -- backend/app/routes/applications/<file>.py [__init__.py]`

## Task 2：前端 FormPermPanel.vue（只读渲染）

**Files:** Create `frontend/src/components/v3/FormPermPanel.vue`

- [ ] **Step 1** Read `RoleManagePanel.vue` 的矩阵 view(template + `loadMatrix` + 矩阵渲染 + preview banner + 状态态)作模板。
- [ ] **Step 2** 写 `FormPermPanel.vue` 骨架：props `{ appId:number; apaasAppId:string; envId:number; formId:string; menuName?:string }`;`<script setup lang=ts>` 拉 `GET forms/{formId}/permissions` → `roles` + `matrix` ref。**先只做 preview(只读)**。
- [ ] **Step 3** 模板(照 RoleManage 矩阵)：业务视角 banner;角色为行;列 = 查看/编辑/删除/新增/导入 + 末列 数据范围;「更多」展开其余操作权限(暂 disabled 占位也行，标 P2)。cell 用 `<BaseBadge>` 或勾选图标显当前值(preview 只读不可点)。加载→`<SkeletonCard :lines=5>`、无角色→`<EmptyState>`、错误→`<ErrorCard>`(import 自 `@/components/states/`)。token 全 `var(--xxx)`。
- [ ] **Step 4** P-类型(零新增)。
- [ ] **Step 5** Commit：`git commit -m "feat(perm): FormPermPanel 只读矩阵(照 RoleManage)" -- frontend/src/components/v3/FormPermPanel.vue`

## Task 3：ChatPage 接第 5 个 designer 子 tab

**Files:** Modify `frontend/src/views/ChatPage.vue`（`DESIGNER_SUBS` ~line 2576 区；mdsh-body 渲染 ~line 343+）

- [ ] **Step 1** Read `DESIGNER_SUBS`(form/list/process/data)+ mdsh-body 里 designerSub 的渲染分支(FormDesignerPanel/ListDesignerPanel/… 的 v-if/v-else-if)。
- [ ] **Step 2** `DESIGNER_SUBS` 末加 `{ code: 'perm', label: '权限' }`。
- [ ] **Step 3** mdsh-body 渲染链末加分支(照现有 panel 写法、传现成变量)：
```vue
<FormPermPanel
  v-else-if="designerSub === 'perm' && selectedApaasMenuFormId"
  :app-id="existingAppId"
  :apaas-app-id="store.currentApp?.apaas_app_id || ''"
  :env-id="store.currentApp?.platform_env_id || 0"
  :form-id="selectedApaasMenuFormId"
  :menu-name="selectedApaasMenuName"
/>
```
+ `import FormPermPanel from '@/components/v3/FormPermPanel.vue'`(确认 ChatPage import 风格)。**确认 `selectedApaasMenuFormId` 等变量名**(Read 核对，别臆测)。
- [ ] **Step 4** P-类型(零新增)。
- [ ] **Step 5** P-视觉：选表单 → 点「权限」→ 真矩阵渲染(浅+暗)。
- [ ] **Step 6** Commit：`git commit -m "feat(perm): 表单设计器加第5子tab「权限」接 FormPermPanel" -- frontend/src/views/ChatPage.vue`

## Task 4：读片验收

- [ ] **Step 1** P-视觉 app_id=22 选表单 → 「权限」显**真**角色×动作(对比中心矩阵 form cell 一致)。
- [ ] **Step 2** P-类型零新增。读片到此可独立交付(纯读，零 apaas 写风险)。

---

# Phase B —— 写片（🚨 真写 apaas，第一次 set 前必须人工确认）

## Task 5：后端 POST 写端点（RMW 整表覆盖）

**Files:** Modify 同 Task 1 的后端文件

- [ ] **Step 1** Read `set_role_resource_permission`(`mcp_server.py:~3342`)完整 RMW + form_code 反查(`list_apaas_app_menus`)+ `_build_perm_payload_from_simple_rules`(`~4983`)签名。
- [ ] **Step 2** 加 `POST /applications/{app_id}/forms/{form_id}/permissions`，body = 完整矩阵(同 GET 的 matrix 形状)。逻辑：解析 env/apaas_app_id → 反查 form_code → **list 当前全量**(RMW 基线) → 用 body 矩阵构建 simple rules → `_build_perm_payload_from_simple_rules` → `set_apaas_form_permissions`(全量) → 返回。
- [ ] **Step 3** 401 自愈(`call_apaas_with_relogin`);form_code 查不到 → 明确错误码不静默。
- [ ] **🚨 Step 4 安全闸**：**先不接前端**。用 curl 拿 app_id=22 某表单当前权限 → POST **只改一个测试角色的一个动作** → 再 GET 复查：①目标角色改了 ②**其它角色权限完全没变**(RMW 正确)。**这一步前在群里/找用户确认可以动 app_id=22 的真权限**。验通过再继续。
- [ ] **Step 5** Commit：`git commit -m "feat(perm): 后端写表单级权限端点(RMW 整表覆盖，apaas 实测 RMW 不误清)" -- backend/...`

## Task 6：FormPermPanel edit 模式 + 保存

**Files:** Modify `frontend/src/components/v3/FormPermPanel.vue`

- [ ] **Step 1** 加 edit 模式(照 RoleManage preview/edit toggle)：edit 下 cell 可勾选 + 数据范围下拉可改;本地改 matrix ref(不即时写)。
- [ ] **Step 2** 「保存」收**完整** matrix → `POST forms/{formId}/permissions` → 成功 toast + 重载;失败 `<ErrorCard>`/ElMessage。
- [ ] **Step 3** P-类型零新增。
- [ ] **Step 4** P-视觉 + **P-apaas 一致性**：edit 改一个角色 → 保存 → 重载保持 + 其它角色未变(再次确认 RMW)。浅+暗。
- [ ] **Step 5** Commit：`git commit -m "feat(perm): FormPermPanel edit 模式 + 保存(完整矩阵 RMW)" -- frontend/src/components/v3/FormPermPanel.vue`

## Task 7：写片验收 + 全量回归

- [ ] **Step 1** 端到端 app_id=22：选表单 → 权限 tab → edit 改权限 → 保存 → 中心「权限」矩阵 form cell 同步反映(同一 API)。
- [ ] **Step 2** vue-tsc `-b` 终验零新增;6 面快速回归无 regression;`git log` 确认全路径限定提交。
- [ ] **Step 3** 写交接 + 更新 spec 状态为已落地。

---

## Self-Review（plan vs spec）

- **Spec 覆盖**：第5子tab(T3)/角色×动作矩阵(T2,T6)/默认列+数据范围(T2)/真读(T1)/真写 RMW(T5)/中心矩阵不动作总览(✓ 不碰)/preview+edit(T2,T6)/状态态复用(T2)/验收(T4,T7) —— 全覆盖。字段级·菜单可见性·删中心矩阵 = spec 非目标，无 task ✓。
- **占位扫描**：FormPermPanel 矩阵正文是「照 RoleManage 读着写」—— **非占位**(有明确真实模板 + props/数据契约 + 复用组件清单);因 RoleManage 矩阵 ~900 行、盲抄易错且违"先读真代码"铁律，故指模板而非预烤代码。后端端点给了归一形状 + RMW 步骤 + 真实 anchor。
- **类型一致**：matrix 形状(view/edit/delete/add/import/range)GET(T1)/Panel(T2)/POST(T5)/save(T6) 一致;props(appId/apaasAppId/envId/formId/menuName)T2 定义、T3 传入一致。
- **关键差异于视觉刀**：这刀**写真 apaas**，故 T5 Step4 设硬安全闸(人工确认 + 测试角色验 RMW)——这是本计划最重要的非常规点。

**执行顺序**：Phase A(T1→T2→T3→T4，纯读安全)全做完 → 🚨Phase B 第一次写前停下确认 → T5→T6→T7。
