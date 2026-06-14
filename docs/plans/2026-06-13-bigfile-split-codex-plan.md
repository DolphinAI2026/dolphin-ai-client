# ⚠️ 已作废 — 见 `docs/superpowers/plans/2026-06-14-ai-builder-architecture-hardening-plan.md`

> **本文已于 2026-06-14 并入统一主计划,不再单独执行。**
> Wave 1B(deploy_service)、Wave 2(mcp_server 拆包)已由 Codex 完成(在途未提交);
> Wave 1A(workspace 模板)→ 主计划 Phase 4A;Wave 3/4(applications/auth)→ Phase 4B/4C;
> Wave 5(ChatPage/CodingPage)→ Phase 7。以下内容仅作历史参考。

---

# 大文件拆分工单(给 Codex 执行)— 2026-06-13(历史)

> 基于 `docs/analysis-2026-06-12-modules-agents-knowledge.md` §1.3 骨架,所有行号/事实已按 2026-06-13 当前代码(dev `60187437`)重新核验。
> 执行者:Codex。每个 Wave 一个或多个独立 PR,严格按本文顺序。

---

## 0. 全局护栏(每个任务都适用)

1. **纯搬移,零行为变化。** 本工单全部是结构重构:搬代码、留 façade、改 import。任何"顺手修 bug/改逻辑"都不做(发现 bug 记 TODO 注释或在 PR 描述里报告,不改)。
2. **外部 import 一律不破。** 被拆文件保留原路径作 façade(re-export 全部被外部引用的符号)。动手前先 grep 列出每个 importer 引用的符号,生成 re-export 清单,拆完逐一核对。
3. **每步验证门(改后端)**:
   ```bash
   cd backend && ./.venv/bin/python -c "import app.main"   # import 完整性
   ./.venv/bin/python -m pytest tests/test_tool_registry.py -q   # mcp 相关改动必跑
   ./.venv/bin/python -m pytest -q --collect-only 2>&1 | tail -2  # collect 无新错(基线 738 collected)
   ./.venv/bin/python -m pytest -q                          # 全量(见下方预存败基线)
   ```
4. **每步验证门(改前端)**:
   ```bash
   cd frontend && npx vue-tsc -b   # 必须 exit 0(当前基线就是 0, strict 已是 true)
   npx vite build                  # 必须成功
   ```
5. **基线(2026-06-13 实测)**:`test_tool_registry.py` 30 passed;pytest collect 738 无错;`vue-tsc -b` exit 0。⚠️全量 pytest 本地(SQLite)历史上有 ~6 个环境性预存败——动手前先跑一次全量记下失败清单,之后只要求"不新增失败"。
6. **commit 粒度**:一个搬移单元一个 commit(如"mcp_tools: 搬 process 域");commit message 用中文,模式 `refactor(scope): 内容`。
7. **禁区(不要动)**:
   - SPEC 设计三件套(SpecDesignPanel 等 ~4.1K 行,`SPEC_TAB_ENABLED=false` 关死):用户决策"别删",绕开。
   - 业务事件域(mcp_server 12 个工具 + business_events.py):功能暂停但保留,只搬不删。
   - routes/coding.py 的旧浏览器 IDE 面已由原生代码工作区替代；后续重构不要恢复旧兼容端点或扩展代理。
   - `step_executor.py` / `generator_v2.py` / `incremental_executor.py` / agent 各循环:属"0-1 引擎二合一"和"agent 引擎收敛"专项,不在本工单。
   - `spec_sections.py` 路由器未注册(前端 SpecDesignPanel 调用必 404):这是待裁决 bug,不在本工单内修。

### 0.1 对 06-12 分析文档的勘误(已完成项,别重复做)

| 06-12 文档说 | 2026-06-13 现状 |
|---|---|
| applications/__init__.py 4228 行,含 config-chat 死区 2842-3716 | **已删**:现 3098 行,`models/config_chat.py`、`config_chat_sessions.py` 均不存在,仅剩 1 处注释提及 |
| GET /{app_id} 影子路由双注册(742/1928) | **已修**:现仅 :739 一处 |
| routes/coding.py 3835 行含死尾 165 行(pipeline 旧副本+裸 LLMClient) | **已删**:现 3665 行,grep 无 LLMClient |
| tsconfig strict 被改 false | **已恢复 true**,`vue-tsc -b` exit 0 |
| mcp_server 10592 行 / 125 工具 | 现 10025 行 / **120 工具** |

---

## Wave 1A:workspace.py 模板落盘(5677 → 约 3400)

**文件**:`backend/app/coding/workspace.py`
**机制已存在**:`templates/` 目录(repo 根下 `backend/templates/`,已有 `cli-generated/`、`backend-api/`);`CLI_TEMPLATE_DIR` 定义在 :331,`CLI_TEMPLATE_MAP` :333;`_scaffold_from_template(ws_path, template_dir, replacements)` 在 :5651,已被 :5159/:5175/:5360 使用。**照抄这套机制**,先读懂 `_scaffold_from_template` 的占位符替换格式,新模板用同一格式。

步骤:
1. 清点 :3314-5650 区间所有内联模板字符串(`= """` / `= '''` 大段),按"生成到工作区的目标文件路径"归类。注意 :74 `_VIBE_SERVE_JS` 等文件头部的模板常量也在清点范围。
2. 每类落盘成 `backend/templates/<template-name>/<文件树>`;带插值的字符串把 f-string 变量改成 `_scaffold_from_template` 的 replacements 占位符。
3. 原代码改为 `_scaffold_from_template(...)` 调用。
4. ⚠️ :2072 与 :2292 有硬编码 `/Users/mars/.nvm/...` 路径——它在生成的 JS 模板字符串内部(`process.env.DF_APAAS_CLI_PATH || '<硬编码>'`)。**落盘时原样保留**(这是生成代码的运行时 fallback,改它=改行为,只在 PR 描述里标注)。
5. 验收:对同一 project_type 各 scaffold 一次,落盘前后生成的工作区文件树 `diff -r` 全等(写个临时脚本对比,放 PR 描述,不进仓)。

## Wave 1B:routes/coding.py 部署编排抽离(3665 → 约 2800)

**文件**:`backend/app/routes/coding.py` → 新建 `backend/app/coding/deploy_service.py`

事实(已核):`_build_and_upload_kits` :2882,`_deploy_to_app_impl` :3401(:3510 端点转调它);`app/agents/coding/tools.py:312` `from app.routes import coding as coding_routes` 反向 import 路由层(:188/:373 注释自述复用 `_deploy_to_app_impl`)。

步骤:
1. 把 `_build_and_upload_kits`、`_deploy_to_app_impl` 及其私有 helper 闭包(从 :2882 起整段清点依赖)搬到 `app/coding/deploy_service.py`,签名不变。
2. routes/coding.py 端点改成 thin wrapper 转调 service;原函数名在 routes/coding.py 留 `from app.coding.deploy_service import _build_and_upload_kits, _deploy_to_app_impl` 兼容别名(防漏网 importer)。
3. `agents/coding/tools.py` 改 import `app.coding.deploy_service`(消除 agents→routes 反向依赖,这是本任务的主要收益)。
4. 顺带收口 IDE helper 双份:`routes/coding.py:86 _ensure_vibe_workspace_file` vs `coding/pipeline.py:96 ensure_vibe_workspace_file`(还有 pipeline.py:116 ensure_cursor_rules)。先 diff 两份实现;不一致处**保留各自调用方现行为**——即只把"逐字相同"的部分合并到 `app/coding/ide_setup.py`,有分叉的留原地并加注释标明分叉点。
5. 验收:`import app.main` 通过;`pytest -q` 不新增失败;grep 确认 agents/ 下无 `routes.coding` import。

## Wave 2:mcp_server.py 拆包(10025 → façade ~100 + 包)

**文件**:`backend/app/mcp_server.py` → `backend/app/mcp_tools/` 包。分 3-4 个 PR。

事实(已核):
- `mcp = FastMCP(...)` 在 :347;120 个 `@mcp.tool()`;工具实现自 :365 起,域分段有现成注释带(`═══`/`───` 分隔,见 :1240/:1557/:2795/:3393/:4234/:5371... 全列表 `grep -n "═════\|─────" app/mcp_server.py`)。
- **22 个外部 importer**(动手第一步全列符号):app/mcp_inprocess.py、app/main.py、app/coding/read_query.py、app/coding/pipeline.py、app/routes/requirements.py、app/routes/applications/{__init__,business_events,section_content}.py、app/ai_chat/mcp_bridge.py、app/services/spec_markdown_generator.py + 12 个 tests/。
- **安全网**:`tests/test_tool_registry.py:426 _extract_mcp_tool_names_from_source` 用 AST 解析**单文件** `app/mcp_server.py` 提取 @mcp.tool 名,与 tool_registry.yaml 比对 drift(:447)。拆包必须同步改它。

目标结构:
```
app/mcp_tools/
  __init__.py        # 空壳或只 re-export core
  core.py            # :83-364 段:配置/内部 HTTP helper/_resolve_identity/trusted_identity/FastMCP 实例 mcp
  app_lifecycle.py   # 按域一文件,顶部 from .core import mcp, <共享helper>
  apaas_read.py
  process.py         # 含其 ~30 个私有 helper
  dict_model.py
  menu_form.py
  form_components.py
  roles_perms.py
  business_events.py # 暂停域,照搬不删
  self_dev.py
  dev_workspace.py
  browser.py         # 含 CDP 桥
  config_skills.py
  issue_assistant.py
```
原 `app/mcp_server.py` 变 façade:
```python
from app.mcp_tools.core import *        # noqa
from app.mcp_tools.core import mcp      # 显式
# 逐个 import 域模块 —— 副作用即 @mcp.tool 注册,顺序保持原文件域顺序
from app.mcp_tools import app_lifecycle, apaas_read, process, ...  # noqa
# + 按第 1 步清单显式 re-export 外部 importer 用到的每个符号
```

PR 切分与步骤:
1. **PR-1(地基)**:建 core.py(搬 :83-364);改 `_extract_mcp_tool_names_from_source` 支持"单文件或 `app/mcp_tools/*.py` 全包扫描"双模式;先搬 1 个小域(如 config_skills)验证全链路。验收:`pytest tests/test_tool_registry.py -q` 30 passed(工具数不变即 drift check 过)。
2. **PR-2/PR-3(搬域)**:每 PR 搬 4-6 个域。**纪律**:整函数剪切粘贴,不改一行实现;域内私有 helper 跟着域走;被 ≥2 个域引用的 helper 上移 core.py(每次上移在 PR 描述记录)。
3. **PR-4(收尾)**:mcp_server.py 只剩 façade;grep 全仓确认没人 import 已搬符号失败;tests/ 里 12 个测试文件若直接 patch `app.mcp_server.<symbol>`,monkeypatch 目标路径**必须改到新模块**(monkeypatch 打在 façade 的 re-export 上不生效——这是本任务最容易翻车的点,逐个测试文件过)。
4. 循环依赖红线:core.py 禁止 import 任何域模块;域模块之间禁止互相 import(要共享就上移 core)。

## Wave 3:applications/__init__.py 拆子模块(3098 → <600)

**文件**:`backend/app/routes/applications/__init__.py`

事实(已核):config-chat 死区已删;现结构 = :36 `from ._helpers import *` + 内联路由(约 :40-2090)+ :2094-2137 既有 include 区(change_plans/generate/docs/preflight/deploy_history/extension/section_content/logs_endpoint/spec_chat/spec_apply/spec_versions/business_events 共 12 个,**模式成熟,照抄**)。

步骤:
1. 清点 :40-2090 内联路由,按资源分组拆成新子模块(沿用目录内既有命名风格):`crud.py`(应用 CRUD/列表/详情,含 :739 GET /{app_id})、`lifecycle.py`(生成/发布/状态类)、`apaas_menus.py`(菜单桥接类)。具体边界以"同资源前缀的端点聚一起"为准,Codex 清点后在 PR 描述里给分组表。
2. 共享 helper 已经在 `_helpers.py`,新子模块直接 `from ._helpers import ...`(显式列名,别学 `import *`)。
3. `__init__.py` 最终只留:router 定义、helpers re-export(兼容)、全部 include_router。
4. ⚠️ include 顺序影响路由匹配(`/{app_id}` 这类通配端点必须在具体路径之后注册)。搬移后用脚本对比拆分前后 `app.routes` 全表:
   ```bash
   ./.venv/bin/python -c "from app.main import app; print('\n'.join(sorted(f'{sorted(r.methods)} {r.path}' for r in app.routes if hasattr(r,'methods'))))"
   ```
   拆分前跑一次存档,拆分后 diff 必须全等(顺序敏感场景以此为准绳)。

## Wave 4:auth.py 三件套纯搬移(2748 → 3 × ~900)

**文件**:`backend/app/routes/auth.py` → `auth/` 包(`__init__.py` façade + `login.py` 认证/token + `tenants_admin.py` + `tenant_members.py`)。
方法同 Wave 3:先 grep 外部 importer 与符号,纯剪切,façade re-export,路由全表 diff 全等。
⚠️ `apaas_client.py` **本工单不拆**(80 方法单类但内聚;连接池/typed errors 是行为改动,另立项)。

## Wave 5:前端三页

### 5A. AIChatPage 双 SSE reducer 收口(先做,最便宜)
事实(已核):`AIChatPage.vue:1951 handleSseEvent` 与 `composables/useAiChatSession.ts:454`(自述"忠实复制")双份并存。
步骤:逐 case diff 两份 reducer → 若仍一致,AIChatPage 改用 `useAiChatSession`(它已是完整会话编排,见其 :661 onEvent 接线);若已漂移,先把漂移 case port 进 composable 再切。验收:`vue-tsc -b`、`vite build`、手测一轮对话(流式/工具卡/中断)。

### 5B. ChatPage.vue 三刀(14180 行,全仓最大;每刀一个 PR)
段边界(已核):template 1-812 / script 814-7964 / style scoped 7966-13804 / style 全局 13806-14180。

**前置 PR**:开 `noUnusedLocals` 临时跑一次 `vue-tsc` 列 unused 清单(改回后提交清单进 PR 描述),删确认无引用的死符号与死 import(如 SectionNav)。**SPEC 三件套相关符号除外**。

**第 1 刀(边界最清晰):部署/更新进度面板** → `components/chat/DeployProgressPanel.vue` + `composables/useDeployPipeline.ts`
- script 侧锚点(已核)::996-1002 deployHistory 簇、:1426-1449 startDeploy* 簇、:3209-3220 deployConfirm 簇、:4427-4726+ 主簇(deployOpen/deploySteps/deployExecuting/deployPercent/deployGroups/openDeployPanel/loadDeployStatus/persistDeployError...)。从这些锚点拉完整依赖闭包(顺着模板引用与函数调用)。
- 方法:状态+逻辑进 composable;模板块整段搬进新 SFC;**对应 CSS 类簇从 style 段一起搬走**(grep 模板里的 class 名反查 style 段,搬干净后 grep 确认 ChatPage 不再引用)。宿主与面板间的共享状态(如当前 app id、会话引用)走 props/emits,清单在 PR 描述里列明。
**第 2 刀:文档版本 4 个 dialog** → `DocVersionsDialogs.vue` + `useDocVersions.ts`(同法)。
**第 3 刀:平台配置 tab 壳** → `useAppConfigTabs.ts`(纯 script 抽离,模板留宿主)。

每刀验收:`vue-tsc -b` exit 0、`vite build` 过、ChatPage 行数下降数字写进 PR、对应功能手测(部署面板开合/步骤执行/文档版本对比回滚)。

### 5C. CodingPage.vue(4987 行,62% CSS;可选,放最后)
顺着 `views/coding/` 既有子组件模式(FileTree/CodeViewer/useCodingPipeline 已拆),再抽:会话列表侧栏 → `coding/SessionListPane.vue`;聊天输入区(排队消息/模型选择/停止) → `coding/ChatComposer.vue`。CSS 随组件走,方法同 5B。

---

## 执行顺序与依赖

```
Wave 1A(workspace 模板)──┐
Wave 1B(deploy_service)──┼─ 互相独立,可并行/任意顺序
Wave 5A(reducer 收口)  ──┘
Wave 2(mcp 拆包, 3-4 PR)── 独立,但工程量最大,放 1 之后
Wave 3(applications)、Wave 4(auth)── 依赖 Wave 2 经验(façade 模式),其实也独立
Wave 5B(ChatPage 三刀)── 前置 PR 后三刀依次
Wave 5C ── 可选
```

预期净效果:mcp_server 10025→façade、workspace 5677→~3400、routes/coding 3665→~2800、applications/__init__ 3098→<600、auth 2748→3 份、ChatPage 14180→~9000(三刀后,CSS 随走)。

## Codex 注意事项汇总(翻车点)

1. monkeypatch/import 目标:测试 patch `app.mcp_server.X` 在符号搬走后会 patch 到 façade 副本上失效——**所有 patch 路径改到符号新家**。
2. FastMCP 注册靠 import 副作用:façade 必须 import 全部域模块,漏一个=该域工具集体消失,`test_tool_registry` drift check 会抓住(这就是先修测试钩子的原因)。
3. FastAPI 路由注册顺序敏感:用上文"路由全表 diff"做等价性证明,别靠肉眼。
4. Vue 拆分时 scoped CSS 跟组件走,`:deep()` 选择器搬家后作用域变化要逐个检查(搬出去后 `:deep` 的锚点元素可能已不在同一组件)。
5. 全程不改 tool_registry.yaml(工具名/白名单零变化)。
6. 遇到"看起来是 bug"的代码(如已知的 spec_sections 未注册):不修,记录到 PR 描述的"发现但未动"清单。
