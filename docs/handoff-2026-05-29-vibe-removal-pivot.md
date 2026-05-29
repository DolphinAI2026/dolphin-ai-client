# Handoff 2026-05-29 — 砍掉 Vibe Coding + 聚焦低代码（大方向反转）

> 分支 `local/ui-redesign-2026-05-20`（**极活跃**，多 agent 并行 + 频繁 commit；本 session commit 未 push）。
> 方向锚：memory `ai_coding_prd_direction.md`（已更新成本方向，新 session 必读）。

## 一句话
用户决策 **砍掉 Vibe Coding**（拿去做单独产品），睿鲸AI 只聚焦 **低代码平台的智能配置 + 智能开发**。本 session 先按旧 PRD 建了一套 Vibe ai-code 6-tab（A/C/①/⑧），然后用户 pivot → 已删 **Vibe 前端** + 首页收成 AI Builder 单一入口；**Vibe 后端删除是个深 refactor，待下一 session 专门做**，之后转低代码焦点。

## ⚠️ 方向反转（最重要，别再走旧路）
- 2026-05-28 的 PRD 主线（按 PRD 大改 vibe-coding 成「①想法入口 + ②6Tab 主工作台 + ⑤Swarm」）**全部作废**。
- 现在：**Vibe Coding 砍掉、做单独产品**。睿鲸AI = 低代码（Builder/SPEC + 智能配置 + 智能开发）。
- 铁律反转：以前是"别动低代码、只改 vibe"；现在是"删 vibe、聚焦低代码"。

## 本 session 完整弧线
1. 接 `handoff-2026-05-28-ai-coding.md`，按旧 PRD 建了 Vibe ai-code（**前端已删 / 后端待删**）：
   - A walking skeleton 6-tab 主工作台 `7978e6c`
   - C 需求基线 `requirement_write` 工具 `7d67594`
   - ① 入口加深（场景/路径分级/导入）`961981f`
   - ⑧ 可观测（token 捕获 + tab）`6a86f09`
2. 用户 pivot：砍 Vibe、聚焦低代码。
3. **删除阶段1（前端）** `ec35f6a`：删 16 个 vibe 前端文件（`components/ai-coding/*` 6标签 + `VibeChatPanel` + `OnlineCoding*Page` + `AICodingWorkspace` + `AiCodeEntryPage` + `SandboxMonitorPage` + `api/onlineCoding`/`vibeCodingChat`/`prototype`）+ 拆线 `router`(/vibe-coding /online-coding /ai-coding 路由 + full-code 守卫)、`RailSidebar`(Vibe nav)、`LandingComposer`(vibe 模式)、`ShellTopBar`、`Apps`(新建AI应用按钮 + ai-code openApp 分支)。**vue-tsc: 0 dangling / 399 errors（baseline 428，删文件减 29、新增 0）。**
4. **首页 opt** `1016e64`：`LandingComposer` 收成 AI Builder 单一入口（隐藏 mode picker；睿鲸 AI Coding 仍在 nav `/coding` 可达）。

→ **Vibe 已从产品层面彻底消失**。低代码 + 睿鲸 AI Coding + 智能开发流水线都在、可用。

## Git 状态
- 本 session commit（时间序）：`7978e6c → 7d67594 → 961981f → 6a86f09 → ec35f6a → 1016e64`。
- 前 4 个的**前端**已被 `ec35f6a` 删；它们的**后端部分**（C 的 `requirement_write`、⑧ 的 `token_usage`，都在 `vibe_coding/` + `models/vibe_coding`）**随 Stage 2 一起删**。
- 分支极活跃（~20 agent worktree + 频繁 commit），我的 commit 都干净落 tip、无冲突。

## 删 / 留 边界（已与用户确认）
**删（Vibe 全代码沙箱）**：
- 前端：✅ 已删（`ec35f6a`）。
- 后端**待删**：`app/vibe_coding/` 目录、`routes/vibe_coding_chat.py`、`routes/online_coding.py`(+`online_coding_runtime.py`)、`models/vibe_coding.py`、`models/app_prototype.py`、`routes/applications/prototype.py`、`app/coding/vibe_agent.py`。
- 拆线：`main.py`（`include_router` online_coding/online_coding_runtime/vibe_coding_chat ~line 209-211 + vibe docker_runtime 启动钩 ~line 125）、`models/__init__.py`（vibe_coding ~380 + app_prototype ~406 import）、`mcp_server`（vibe 工具）、`database.py`（vibe_coding ALTER 迁移 ~124/126）、`sandboxes.py`。
- DB：drop `vibe_coding_threads/messages/tool_calls`、`online_coding_workspaces`、`app_prototypes`。
- `app_type`：去 ai-code 分类（列可留默认 low-code；`Apps.vue` 标签 ternary line ~116/183 + `.is-ai-code` CSS ~1118/1130 收尾；`schemas.py` / `routes/applications/_helpers.py` 引用）。

**留（焦点）**：低代码 Builder/SPEC（`/chat` ChatPage、`/ai-chat`、SpecDesignPanel、builder_spec、apaas client、generator/validator）、**智能配置**（ConfigAssistant）、**睿鲸 AI Coding**（`/coding` CodingPage + `api/coding` + `routes/coding.py` + `app/coding/` 组件件，用户要留做**公共组件开发/代码管理**）、**智能开发流水线**（`coding_v2`/`coding_v2_spec` + `orchestrator/` + `agents/`，dormant、产物偏 apaas、跟 vibe 零 runtime 耦合）。

## ⚠️⚠️ 后端删除的深坑（Stage 2 — 下一 session 动手前必读）
**后端 AI Coding（留）和 Vibe（删）不可干净分离**：
- `coding.py`(保留) line **361 + 1590** `from app.routes.online_coding import _build_ide_workspace_context / _find_workspace_dir / _repo_path / _summarize_repo / _write_workspace`，且有 `if ws_id.startswith("oc_"):` 分支专门处理 vibe 工作区。
- `online_coding` 又 `import VibeCodingThread`（`app.coding.workspace.WORKSPACE_ROOT` 也共享）。
- → 依赖链 **coding.py → online_coding → VibeCodingThread**。
- `sandboxes.py` / `agents_config.py` / `services/coding_prompt_seed.py` 也碰 vibe 簇。

**所以删 Vibe 后端 = 深 refactor**（不是 rm 文件夹）：得把共享 `workspace/IDE/thread` infra 抽成独立模块、给 AI Coding 自己的 thread/workspace model、重写 `coding.py` 的 `oc_` 分支，再删 online_coding。**别在疲惫时硬搞 —— 删错会崩掉保留的 AI Coding 或后端 `import app.main` 起不来。** 每步 `py_compile` + `python -c "import app.main"` 验证。✅ 干净的 `coding_v2`/`orchestrator`/`agents` 完全不碰 vibe，保留无忧。
- 现状：后端 vibe 代码还全在、routes 还 mount，但前端已不调用 → **死代码、无害**，可安全推迟到专门 pass。

## 下一 session 起手（用户倾向）
1. **直接转低代码焦点**：智能配置 / 智能开发（新功能先走 brainstorming skill）。后端 vibe 死代码无害、可推迟。← 用户倾向
2. 或先做后端 Vibe 删除（深 refactor，按上面坑）。

## 环境
- 后端跑在 `:8000`（`{"status":"ok"}`，已是 8000 不是 8003）；前端 dev server `:5173`。**改后端后用户需手动重启**（`cd backend && ./venv/bin/python run.py`，"address in use" = 它已在跑）。
- preview 工具深链 `/...` 硬刷新会返 `{"detail":"Not Found"}`（dev server SPA fallback 抽风，**非代码问题**；用户真浏览器正常）。vue-tsc baseline ~428 pre-existing errors（与本次无关）。
