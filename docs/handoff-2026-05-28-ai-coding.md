# Handoff 2026-05-28 — AI Coding 应用类型 + PRD 主线方向确立

> 分支 `local/ui-redesign-2026-05-20`，所有 commit **未 push**。
> 方向锚详见 memory `ai_coding_prd_direction.md`（新 session 必读）。

## 一句话
给应用加了 **low-code / ai-code 类型标签**（完整落地 + 浏览器实测），并确立"**按 PRD 大改 vibe-coding**"的方向。中途第一刀走偏（错做成低代码侧）后纠正。

## 这个 session 的 commits（ai-coding，从早到晚）
- `aa7bfb3` 第一刀 plan（9 任务）
- `8da8fa3`/`ab6f91b` app_prototypes 表 + fix
- `bc2ecc8` 原型 prompt / `57a684d` SSE 生成 endpoint / `a23187a` 读取 endpoint / `62cb94c` Task4 fix
- `8f4b7a7` 前端骨架+6Tab / `8ecb29b` 左对话 SpecChatPanel / `1efc02f` 预览 Tab
- `1a98e61` **Application 加 app_type + source_workspace_id**
- `d8479ef` vibe 登记 → `f4f8bc7` 修登记位置 → `635c438` 修租户（最关键）
- `310134d` merge 响应带 app_type / `5169538` 前端类型标签 + DB 迁移
- `17cf16b` **点 ai-code 应用 → 分流到 vibe workspace 工作台**

⚠️ HEAD 历史里夹着**别的 session/线**的 commit：`e097c81`(config-assistant) `e41d542`(spec-design) `b3a6a21`/`4e8a6d1`(custom-page) —— 这些是 **low-code/apaas 侧（别动）**。

## 落地 + 验证
- 应用分两类型：`Application.app_type`（low-code=ai-builder/SPEC，ai-code=vibe-coding）+ `source_workspace_id`，DB 启动迁移自动加列
- vibe workspace 创建/列表幂等登记 ai-code 应用：`online_coding._register_ai_code_app`（当前租户优先 + upsert 同步名/租户）
- 应用列表类型标签（低代码蓝 / AI 代码绿）+ 点 ai-code → vibe workspace 工作台
- 后端 3 测试过；**浏览器实测过**：列表 5 个（CRM + 报销系统 = ai-code，化工/图书/任务 = low-code），名字标签都对

## 搁置（第一刀走偏的产物 — 不是 PRD 主线，别当真）
`frontend/src/views/AICodingWorkspace.vue` + `components/ai-coding/WorkspaceTabs.vue` + `PreviewTab.vue` + `api/prototype.ts` + 后端 `models/app_prototype.py` + `routes/applications/prototype.py`（HTML 原型生成）。
→ 第一刀错把"6 Tab 工作台"接到 **low-code SpecDesignPanel** + 静态 HTML 原型。PRD 主线重做时这个 6 Tab 壳可复用，但需求/预览要接 **ai-code（vibe workspace）**，不是 SPEC/HTML 原型。

## 留尾 / 下一步（新 session 起手）
1. **后端 404 挂了** —— 我后台临时跑的后端（`bc7k8naq7`）被终止后没恢复。**用户用自己终端重启**：`cd backend && ./venv/bin/python run.py`（启动跑 DB 迁移）。
2. **验证 `17cf16b` 分流**：重启后点 CRM/报销系统应进 `/vibe-coding/workspaces/{ws}` 工作台（这刀因后端 404 没浏览器实测）。
3. 点 ai-code 应用进去还是**现状 vibe coding 沙箱**（对话+IDE+预览），**不是** PRD 6 Tab 主工作台 —— 这是 PRD 主线要做的。
4. **PRD 主线第一刀**：读架构文档 `docs/internal/INTELLIGENT_DEV_AGENT_ARCHITECTURE_V1_2026-04-19.md` → 摸 `orchestrator/`+`agents/` 现状 → brainstorm（①系统想法入口 + ②主工作台改接 ai-code + 现有串行 pipeline 升级成 ⑤并行 Swarm DAG）。
5. **铁律**：别动 apaas/low-code（SpecDesignPanel/spec/custom-page）。

## 现成基础（PRD ⑤Swarm/⑧可观测 不用从零）
`backend/app/orchestrator/`（Phase 状态机 + Coordinator + Driver）+ `backend/app/agents/`（BaseAgent + Brainstorm/Coding/Verification/iteration + EventPublisher SSE + TraceWriter）。现状串行 phase pipeline，PRD 要升级并行 DAG + handoff。
