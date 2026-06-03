# ai-builder 当前代码审计报告

> 日期: 2026-06-03  
> 范围: `/Users/mars/Vibe Coding/ai-builder` 当前工作区。  
> 用途: 交给 Claude 做代码修改前的工程侧审计输入。  
> 说明: 本报告合并本次快速审计、现有 `docs/audit-2026-05-29-codebase-health.md`、以及 `docs/deploy-readiness-2026-05-30/04-security-findings.md` 中已修正的安全结论。若三者冲突，以本文和 2026-05-30 安全报告为准。

## 1. 当前验证结果

### 1.1 前端构建

命令:

```bash
cd frontend
npm run build
```

结果: 失败。

原因: `vue-tsc -b` 阶段失败，错误量较大，类型问题集中在:

- `ChatPage.vue`: 大量未使用变量、空值风险、未定义符号，例如 `pendingInitialConversationPromise`。
- `StructuredDocDiffRenderer.vue` / `DataSchemaEditor.vue` / `ProcessDesignerPanel.vue`: `undefined` 与必填类型不匹配。
- `AgentConversation.vue` / `useStreamMessages.ts`: 访问可能不存在的数组元素或字段。
- `GlobalNavRail.vue`: API/store 类型不一致。

补充:

```bash
cd frontend
npm run build:nocheck
```

结果: 成功。说明当前生产包可以绕过类型检查构建，但正式类型门禁不通过。

风险:

- 继续用 `build:nocheck` 发版会掩盖真实 UI 空值和事件绑定问题。
- Claude 修改前端时应先修与本次任务直接相关的类型问题，至少保证目标路径不新增类型错误。

### 1.2 后端测试

命令:

```bash
cd backend
./.venv/bin/pytest -q
```

结果: `471 passed, 6 failed`。

失败集中在:

1. JWT `aud` 字段与测试解码方式不兼容。
   - `tests/test_auth_switch_tenant.py`
   - 原因: 测试直接 `jwt.decode(..., algorithms=[...])`，但 token 现在带 `aud=ai-builder-web`。

2. `create_access_token` 旧签名兼容断裂。
   - `tests/test_platform_admin_tenant_context.py`
   - 原因: 测试传 `{"sub": user.id}`，当前实现只兼容 `User | int`。

3. 平台管理员登录测试误走真实 aPaaS 登录。
   - `tests/test_platform_admin_tenant_context.py`
   - 原因: 单测未隔离外部 aPaaS 依赖。

4. `query_models` fake client 与真实接口契约不一致。
   - `tests/test_step_executor_model_merge.py`
   - 原因: `execute_create_model` 调用 `client.query_models(app_id, with_fields=False)`，测试 fake 不接受该参数。

建议:

- 先修测试契约，不要为了绿测试回退业务逻辑。
- 后端 CI 应保留全量 pytest；前端 CI 应恢复 `npm run build` 而不是只跑 `build:nocheck`。

## 2. 必须优先处理的问题

### P0: 代码修改前先恢复工程门禁

目标:

- `npm run build` 通过。
- `./.venv/bin/pytest -q` 通过。

原因:

- 当前前端类型门禁失效，Claude 做 UED 和路由调整时容易把空值/事件错误继续扩大。
- 后端 6 个失败虽然多为测试契约问题，但会干扰后续判断“修改是否引入回归”。

建议执行顺序:

1. 修后端 6 个测试失败。
2. 修前端与目标页面相关的类型错误。
3. 对短期内不可能一次清完的前端历史类型错误，建立临时基线清单，避免新改动增加错误数。

### P0: 安全报告优先级以 2026-05-30 版为准

不要直接照抄旧 `docs/audit-2026-05-29-codebase-health.md` 的 P0 SSRF 结论。后续安全报告已明确修正:

- 旧 P0 `exchange_apaas_token` SSRF 链路已被中和，不应作为最高优先级照抄。
- 真正高危应优先看:
  - 平台反向代理鉴权和全局 token 问题。
  - README/git 历史密钥泄漏。
  - `verify=False`。
  - docker.sock + code-server 暴露。
  - Git token Fernet dev fallback。
  - 浏览器导航 SSRF。

Claude 若处理安全问题，应先读:

- `docs/deploy-readiness-2026-05-30/04-security-findings.md`
- 相关真实代码

## 3. 代码结构风险

### 3.1 前端核心页面过大

当前体量:

- `frontend/src/views/ChatPage.vue`: 约 14,702 行。
- `frontend/src/views/CodingPage.vue`: 约 4,676 行。
- `frontend/src/views/AIChatPage.vue`: 约 2,681 行。
- 多个配置面板超过 1,000 行。

风险:

- UED 改动容易牵动无关逻辑。
- 难以做局部类型修复。
- 阶段状态、对话状态、配置状态、部署状态混在同一页面里，回归风险高。

建议:

- 不要一次性重写 `ChatPage.vue`。
- 先加阶段条、主 CTA、入口收敛等低风险 UED 改动。
- 再按阶段拆 composable 和子组件:
  - 需求输入
  - 设计文档
  - 配置预览
  - 变更计划
  - 部署
  - 二次开发 IDE 打开态

### 3.2 后端 route 和服务层边界不清

高风险文件:

- `backend/app/routes/applications/__init__.py`
- `backend/app/routes/coding.py`
- `backend/app/routes/chat.py`
- `backend/app/routes/generation_steps.py`
- `backend/app/mcp_server.py`
- `backend/app/coding/workspace.py`

风险:

- 路由层包含大量业务编排、平台调用、状态变更和异常处理。
- 权限、租户、平台 token 自愈逻辑散落。
- 一处修复可能造成多入口行为不一致。

建议:

- 修改时优先抽公共 helper，不要复制一套鉴权/租户/平台调用逻辑。
- 涉及 aPaaS token 刷新时，先读现有 `call_apaas_with_relogin` 和 `_relogin_apaas_env` 的真实签名。
- 保持 “路由层薄、服务层可测、平台 client 隔离”。

## 4. 与 UED 目标直接相关的代码建议

### 4.1 取消独立 Coding 入口

产品口径:

- 不再提供独立 `/coding` 主导航入口。
- 创建、调整、二次开发都在 AI Builder 中完成。
- 自开发资产库作为产物/历史工作区管理，不作为独立创作入口。
- 用户点击自开发资产后直接打开 IDE，并带入应用、资产、工作区、安装目标。

代码处理建议:

- 从主导航组件中移除 Coding 入口。
- 如果保留 `/coding` 路由，仅作为内部兼容路由，不在 UI 暴露。
- 从应用详情或 AI Builder 内部动作进入二次开发。
- 自开发资产卡片 click 行为改为打开 IDE，而不是进入 Coding 列表/落地页。
- IDE 打开态必须校验当前用户对工作区和应用的访问权限。

### 4.2 首页不需要“从模板创建应用”

产品口径:

- 创建应用只保留:
  - 描述需求
  - 上传设计文档

代码处理建议:

- 删除或隐藏首页模板创建入口。
- 如果行业包/模板能力仍存在，不作为创建应用主入口展示。
- 首页第一屏不要同时展示二次开发、模型、流程、权限、平台管理等概念。

### 4.3 AI Builder 作为唯一工作台

目标:

- 建应用、改应用、二次开发都落到 AI Builder 的阶段式工作台。

推荐阶段:

```text
需求 -> 设计文档 -> 配置 -> 变更计划 -> 部署 -> 二次开发
```

说明:

- 二次开发不是每个应用必经阶段，但应从当前应用上下文触发。
- 二次开发的 IDE 是工具态，不是独立产品态。
- 安装回应用后，应回到 AI Builder / 应用配置上下文。

### 4.4 取消 Coding 入口不只是删除导航

本次补充排查发现，旧 Coding 心智散落在路由、按钮、会话 handoff、管理文案和临时 demo 页里。Claude 修改时不要只删左侧导航。

已定位的重点位置:

- `frontend/src/router/index.ts`
  - `/ide` 当前直接 redirect 到 `/coding`。
  - `/coding` 仍是正式路由。
  - `/extension-demo`、`/section-nav-demo` 仍是可访问 demo 路由。
- `frontend/src/views/ChatPage.vue`
  - 存在 `openCodingWorkspace` / `handoffToCodingForAppDev`，通过 `sessionStorage('ai_builder_pending_coding')` 把 AI Builder 上下文转交给 CodingPage。
  - 页面按钮和提示仍出现 “AI Coding”“Vibe Coding” 心智。
- `frontend/src/views/ProjectOverview.vue`
  - 项目开发、页面开发、打开工作区都 `router.push('/coding')`。
- `frontend/src/components/v3/CustomPagePreviewPanel.vue`
  - “去 IDE 改源码”按钮仍跳 `/coding?app_id=...`。
- `frontend/src/components/v2/ExtensionSectionPanel.vue`
  - “用 AI Coding 开发自开发包”卡片仍打开 `/coding?app_id=...` 新标签。
- `frontend/src/components/v2/LandingComposer.vue`
  - 用户输入 prompt 后仍可能跳 `/coding`。
- `frontend/src/views/v2/RuntimePage.vue`
  - 发布/运行页仍有 `router.push('/coding')`。
- `frontend/src/components/v2/RailSidebar.vue`
  - “自开发资产库”仍作为一级 rail item；如果产品口径是只做应用/AI Builder 内部资产入口，应从主 rail 降级。
- `frontend/src/views/PlatformTenants.vue`
  - 管理页仍展示 “Vibe Coding 工作区”配额。
- `frontend/src/views/v2/McpHubPage.vue`
  - MCP 范围文案仍包含 “睿鲸 AI Coding / Vibe Coding 全代码”。
- `frontend/src/components/BuilderCommandPalette.vue`
  - `DevOps 总览` meta 仍写 “第一阶段 mock”，正式产品入口不应暴露 mock 口径。
- `frontend/src/views/QuickDbPage.vue`
  - 可见文案仍有 “选模板风格”。它不等同于“从模板创建应用”，但若首页移除模板创建，需要把该能力定位为配置辅助，而不是创建主路径。

处理建议:

1. 保留 `backend/app/routes/coding.py`、`frontend/src/api/coding.ts`、`frontend/src/stores/coding.ts` 作为内部 IDE / workspace 能力可以接受，但 UI 不再把它命名成独立产品。
2. `/coding` 如果短期不能删除，应改成兼容路由或重定向到 AI Builder 内部 IDE 打开态，不再作为用户可见入口。
3. AI Builder 内的二次开发动作应直接打开 IDE 抽屉或应用上下文 IDE 页，并带 `app_id`、`workspace_id`、资产类型、安装目标。
4. 全局可见文案统一把 “AI Coding / Vibe Coding / Coding 工作区” 改成 “二次开发 / IDE 工作区 / 自开发资产”，但 API 名和内部 store 名可以先不动。
5. 临时 demo 路由可以保留为 internal/dev only，但不要出现在导航、命令面板、公开验收路径里。

## 5. 旧报告中仍可保留的待办

`docs/audit-2026-05-29-codebase-health.md` 中以下类别仍可作为待办来源，但执行前必须复核当前代码:

- aPaaS 401 自愈漏点。
- 前端假功能和 alert/disabled 状态。
- 失败伪装成功的状态语义问题。
- 吞异常和重试风暴。
- 死代码和调试脚本清理。

注意:

- 旧报告 P0 SSRF 结论已被后续安全报告修正，不要照抄为最高优先级。
- 旧报告里的位置可能随近期提交漂移，Claude 必须重新 `rg` 和读代码。

## 6. 建议给 Claude 的执行顺序

1. 先读本文和 `docs/ued-optimization-audit-2026-06-03.md`。
2. 确认产品口径:
   - 无独立 Coding 入口。
   - AI Builder 内完成创建、调整、二次开发。
   - 自开发资产点击直接打开 IDE。
   - 无“从模板创建应用”。
3. 修工程门禁:
   - 后端 6 个测试失败。
   - 前端目标路径类型错误。
4. 做 UED 入口收敛:
   - 首页双入口。
   - 左侧导航移除 Coding。
   - 自开发资产库点击打开 IDE。
   - AI Builder 增加阶段感和主 CTA。
5. 跑验证:
   - `npm run build` 或至少记录剩余类型错误基线。
   - `npm run build:nocheck`。
   - `./.venv/bin/pytest -q`。
   - 本地浏览器检查 `/`, `/apps`, `/chat`, 自开发资产打开 IDE 态, `/platform-admin`。
