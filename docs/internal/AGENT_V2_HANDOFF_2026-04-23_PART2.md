# 智能开发 Agent V2 —— 会话交接文档（2026-04-23 下午/晚间）

本文承接 `AGENT_V2_HANDOFF_2026-04-23.md`（今天早些时候那份）。当天下午和晚上的会话做了一大批 UX / 架构修复，主要围绕用户实际跑完整路径时暴露的问题。**新会话务必先读 04-20 + 04-23 上午两份，再读本文**。

## 1. 工作目录

```
/Users/mars/Desktop/apaas-build/apaas-builder-ai/.claude/worktrees/competent-chatterjee-6d4c33
```

- 分支：`claude/competent-chatterjee-6d4c33`
- **所有代码改动都只在这个 worktree 里**；不可合 main
- 后端跑在主仓 `backend/venv` 的 uvicorn 下，cwd 指向 worktree/backend（让 `--reload` 监听 worktree 代码）
- 前端 vite 在 5173
- code-server 在 8080

## 2. 本次修的核心问题

用户从头跑了一遍完整链路（国际手机号 / 星级评分组件），暴露了十几个互相独立的问题，按量级分：

### 2.1 Prompt / 语义类（影响 LLM 行为）

**P1 — LLM 忽略 Spec.scenes_required，把所有 7 个场景都写了**
- 根因：[coding/prompts.py](../../backend/app/agents/coding/prompts.py) 的 `_WORKFLOW_FORM_COMPONENT_DUAL` 里多处硬编码 "7 render scenes"、"turn1: [write_file×7]" 这类强指令，压过了 user message 里 Spec 的"必需：edit, read"
- 修复：prompt 多处改写成 "Spec.scenes_required 指定的那些"；[spec_bridge.py](../../backend/app/agents/coding/spec_bridge.py) 的渲染场景段落升级为 `### 🔴 本次只生成以下 scene`，带【必需/可选/未选】三分类 + ⚠ 说明；workflow 新增"scenes_required 正反例"

**P2 — autofix 重试接收端断链**
- 根因：[driver.py](../../backend/app/orchestrator/driver.py) 构造 `fix_hint` 塞进 `ctx.input["fix_hint"]`，但 `backend/app/agents/coding/` 下**全无**代码读这个字段 → 每轮重试的 CodingAgent 看到的 user message 和首轮完全一样，从零再跑一遍
- 修复：[coding/agent.py:199-227](../../backend/app/agents/coding/agent.py) 从 `ctx.input["fix_hint"]` + `ctx.extra["round_index"]` 读出，透传给 `build_user_prompt`；[coding/prompts.py](../../backend/app/agents/coding/prompts.py) 的 `build_user_prompt` 新增 `fix_hint` / `round_index` 参数，`round_index > 0` 时在 user message 最前面插入 `🔴 本次是 Round N` banner，带五条修复规则（跳过首轮动作、先 read 看状态、只改失败 AC、edit_file 定向改不要 write_file 重写、修完再 build）

**P3 — CONFIRM 阶段纠正 Spec 假设被误解成"新建组件"**
- 根因：[routes/coding_v2.py](../../backend/app/routes/coding_v2.py) 的 `refine_brainstorm` 分支"回 UNDERSTAND + 起全新 brainstorm session"，把用户的纠正（如"附件 formValue 是对象数组"）当成一个新需求喂给空白 BrainstormAgent → LLM 去做 scene 检测，重开场景问题
- 修复：`refine_brainstorm` 改成走 iterate 分发（`_run_iterate_dispatch_task(..., from_confirm_phase=True)`）；新参数控制 TRIVIAL 路径不再自动进 GENERATE 跑 coding，而是 apply patch 后停在 CONFIRM 让用户重新审视更新后的 Spec

### 2.2 事件时序 / 前端渲染类

**P4 — 首次生成却显示"🔁 自动修复 · 第 2 轮"**
- 根因：[stores/codingV2.ts](../../frontend/src/stores/codingV2.ts) 的 `scaffold.done` handler 预推了一张 `coding-active` 卡；紧接着 `coding.start` handler 按 `coding-active` 数量 + 1 算 roundNum → 误算成 2
- 修复：`scaffold.done` 删掉多推的 divider + coding-active，统一由 `coding.start` 负责

**P5 — 思考过程卡片文字"先是 A，后变成 B"**
- 根因有两重：
  1. [coding/agent.py](../../backend/app/agents/coding/agent.py) `_call_llm` 里 reasoning_content 和 content 都以 delta 发给前端（同一条目累积），但 aggregate 只发 `full_content`（不含 reasoning）→ aggregate 到达时覆盖条目，reasoning 部分消失
  2. `on_llm_response` 生成 synthetic note（当 LLM 只吐 tool_calls 无 content 时）以 delta 发送，被前端追加到**未封口**的 thinking 条目上 → 卡片尾部突然多出合成文字
- 修复：
  - aggregate 统一含 reasoning + content（`(reasoning or '') + (full or '')`）
  - synthetic note 改发 `agent_thinking`（aggregate）而非 delta
  - 前端 [stores/codingV2.ts](../../frontend/src/stores/codingV2.ts) 配合：`CodingLogEntry` 加 `sealed` 字段；aggregate 写完置 `sealed=true`；delta 看到已封口的 thinking 就新开条目

**P6 — 验收阶段没同步滚动 / Spec 生成完停在半截**
- 根因：[ChatFlow.vue](../../frontend/src/components/coding-v2/ChatFlow.vue) 原有 watchers 只盯 `chatMessages.length` / `streamedText` / `toolTraces.length` / `isThinking`，**没盯 `verifyLog` 和 `codingLog`**；spec-ready 卡 envelope 是 async 拉取，初始 scroll 先跑完、卡片后来撑大错位
- 修复：新加 `verifyLog.length` / `codingLog.length` watch；新加 `scrollToBottomAfterRender`（`await nextTick + 80ms`）watch `currentSpec` / `lastVerificationReport`，等 markdown/表格子组件渲染完再滚

### 2.3 UX / 视觉类

**P7 — 点发送按钮立刻 loading 误导用户**
- 根因：[CodingPageV2.vue](../../frontend/src/views/coding-v2/CodingPageV2.vue) 只有一个共享的 `submitting` ref，同时控制 `onSend`（发消息）和 `onConfirmSpec`（点确认）；纠正消息也让 SpecPreview 的确认按钮变 loading + 文案"正在启动生成…"
- 修复：拆 `submitting` → `sendingMessage`（发消息）+ `confirmingSpec`（点确认）；ChatFlow 的 `confirm-submitting` 只绑 `confirmingSpec`

**P8 — Spec 配置项表格里长值被强制折行**
- 根因：[ComponentSpecSummary.vue](../../frontend/src/components/coding-v2/ComponentSpecSummary.vue) 的 `.prop-table` 没对 td 设 `white-space: nowrap`，90px 宽的"默认值"列把 6 字中文折两行
- 修复：`.prop-table td` 默认 nowrap，`.desc-cell`（说明列）覆盖为 normal；`.table-wrap` 从 `overflow: hidden` 改 `overflow-x: auto` 兜底水平滚动

**P9 — AI 默认假设区域不够突出 + 默认折叠**
- [OpenQuestionsPanel.vue](../../frontend/src/components/coding-v2/OpenQuestionsPanel.vue)：
  - `expanded = ref(true)` 默认展开
  - 整体换琥珀色调（background `#fffbeb`），不加左边框，不加 Q{n} 浅蓝方框
  - 用 `IconWarn.vue` SVG 代替 `⚠` emoji
  - Q{n} 字号从 11px → 14px、align-items: center 和内容垂直居中
  - 展开区顶部加 callout 提示："AI 基于需求自动推断的开发方向，可能与真实意图不一致，请逐条核对"
  - 每条假设的"假设"前缀用琥珀色 tag 样式

### 2.4 构建产物 / 清理类

**P10 — Verify agent 反复读打包后的 UMD 文件，污染推理**
- 现象：用户截图里 verify 阶段连续 6 次 `read_file web/form-component-custom-intl-phone/form-component-custom-intl-phone.umd.js`
- 根因：`_build_dual_project` 产物校验通过后保留了 `web/{outputName}/` + `mobile/{outputName}/`，里面的混淆 UMD 文件对 LLM 分析源码毫无用处
- 修复：[workspace.py:1510-1532](../../backend/app/coding/workspace.py) 新增 `_cleanup_dual_build_artifacts`，在 `_build_dual_project` 返回 `ok` 前清掉两端打包目录（保留 `.zip` 给下载 / 上传市场用）
- 副作用：`routes/coding.py:944` 的 `?type=dist` 下载会拿到 400 → 但全前端都没调它（`grep` 确认），实际上是死代码

### 2.5 历史残留清理

**P11 — 单端 form-component prompt 早废弃但仍是兜底陷阱**
- 根因：[ProjectType 枚举](../../backend/app/coding/workspace.py) 里只有 `FORM_COMPONENT_DUAL`，但 [coding/prompts.py](../../backend/app/agents/coding/prompts.py) dispatcher 的 `else` 分支还 fallback 到 `_WORKFLOW_FORM_COMPONENT`（单端），导致任何未登记的 project_type（backend-feign 等）被喂错 prompt
- 修复：删掉 `_WORKFLOW_FORM_COMPONENT` 整块（约 87 行）；`render_form_component_sections` 去掉 `base_path` 参数、hardcode dual；dispatcher 的 else 分成两支：空 project_type → 默认 dual（测试友好）；非空但未登记 → 显式 `raise ValueError`

## 3. 改动文件清单

**Backend**：
```
backend/app/agents/coding/prompts.py        # scenes_required 改造 + fix_hint + 删单端
backend/app/agents/coding/spec_bridge.py    # 渲染场景段落升级（未选 scene 列表）
backend/app/agents/coding/agent.py          # fix_hint/round_index 透传 + aggregate 合并 reasoning+content + synthetic note 改 aggregate
backend/app/routes/coding_v2.py             # refine_brainstorm 改走 iterate 分发 + from_confirm_phase 参数
backend/app/coding/workspace.py             # _cleanup_dual_build_artifacts（构建后清 UMD）
```

**Frontend**：
```
frontend/src/stores/codingV2.ts                          # sealed 字段 + scaffold.done 不抢发 divider
frontend/src/components/coding-v2/ChatFlow.vue           # 补 verifyLog/codingLog/currentSpec/report 滚动 watch
frontend/src/components/coding-v2/OpenQuestionsPanel.vue # 琥珀色 + 默认展开 + IconWarn
frontend/src/components/coding-v2/ComponentSpecSummary.vue # 配置项表格 nowrap + 横向滚动
frontend/src/views/coding-v2/CodingPageV2.vue            # submitting 拆 sendingMessage/confirmingSpec
```

**Tests**（跟着修）：
```
tests/test_coding_agent_stage_2_3.py      # 删单端 snapshot 测试；加 3 个 fix_hint 测试
tests/test_coding_agent_stage_2_4.py      # synthetic note 测试改 agent_thinking 事件类型
tests/test_coding_agent_adapter.py        # 预置 _messages 跳过 build_initial_user_message（避 WORKSPACE_ROOT 模块级缓存问题）
tests/fixtures/prompt_snapshots/form_component.txt                 # 删除（单端废弃）
tests/fixtures/prompt_snapshots/form_component_dual.txt            # 重新生成
tests/fixtures/prompt_snapshots/form_component_dual_with_summary.txt # 重新生成
```

**全量测试**：426 passed（排除 3 个本就 import-error 的 e2e / complex_form / full_deploy）。

**全部未 commit**。用户偏好 commit message **只允许中文**。

## 4. 未解决 / 下一步

### 4.1 BrainstormAgent 不感知 trigger_type / base_spec
- 现状：[bs_svc.BsTrigger](../../backend/app/services/brainstorm_session_service.py) 有 `ITERATE_MINOR / ITERATE_MAJOR`，DB 也持久化，但 BrainstormAgent 的 prompt **完全不读这个字段**
- 影响：P3 修好了 CONFIRM trivial 路径，但如果纠正被 classifier 判成 minor/major，新起 brainstorm 时 agent 还是不知道有 base_spec 要尊重 → 可能还是重问全套场景
- 建议下一轮做：
  1. `BrainstormAgent.ctx.input` 加 `base_spec_brief: str | None`
  2. `build_user_prompt` 新增 `base_spec_brief` 参数，非空时前置 `## 上一版 Spec（用户正在纠正此 Spec 而非从零开始）` 段
  3. 路由层 `_run_iterate_dispatch_task` 的 minor/major 分支调 `_start_brainstorm_for_iterate` 时把 base_spec 渲染成 brief 塞进 input

### 4.2 Spec 校验规则太宽
- `_has_build_artifacts` 只看"有任意 .js/.css/.html/.jar/.war 就过"，不看文件大小、入口文件名、manifest 完整性
- 用户看过说"大体是正确的，先不动" —— 暂挂

### 4.3 fix_hint banner 有效性
- prompt 里已经插了，但没真实跑过"verify 失败 → retry"场景验证 LLM 是否会照做（跳过 glob、只 edit 失败文件）
- 建议下一会话：故意让 coding 漏一个 AC（如"必填校验"），看 Round 1 思考过程是否直接说"我看到 Round 1 标记，先 read_file 看当前 edit.vue 状态" 而不是从头 glob

### 4.4 上一份 handoff 没做完的事（仍未处理）
- SCAFFOLD phase 实际执行（新建会话首轮卡死的堵点）
- LLM 无 tool_call 路径发 `brainstorm.failed / stuck` 事件
- AutoFix 多轮的 `on_verify_retry` 没发 `orchestrator.phase_changed: generate` SSE
- Agent snapshot 持久化（上 K8s 前提）

## 5. 验证过的数据

- 426/426 pytest passed（排除 3 个预存 import error）
- 前端 HMR 正常吃到所有 .vue 和 store.ts 改动
- 后端多次 uvicorn --reload 走完，`app.main` 导入无错
- 前端截图直接确认：思考卡不再跳变、配置项表格整齐、AI 假设样式到位、验收阶段滚动跟随

**没真实跑过**的关键场景：
- autofix 第 1 轮失败→第 2 轮是否按 banner 指示修
- CONFIRM 阶段 trivial refine 是否产出新 Spec 并停在 CONFIRM
- 构建产物清理后 verify agent 是否真的不再 read UMD

## 6. 文件导航速查

```
后端 — prompt / agent 层（本次改动最密集）
  backend/app/agents/coding/prompts.py           build_user_prompt + 删单端 + scenes_required 改造
  backend/app/agents/coding/spec_bridge.py       渲染场景段"未选 scene"列表
  backend/app/agents/coding/agent.py             build_initial_user_message 透 fix_hint；_call_llm 合并 reasoning+content aggregate；synthetic note 改 aggregate
  backend/app/orchestrator/driver.py             drive_coding_with_autofix 主循环（未动；fix_hint 已从这里流向 agent）
  backend/app/routes/coding_v2.py                refine_brainstorm → iterate 分发；_run_iterate_dispatch_task 加 from_confirm_phase
  backend/app/coding/workspace.py                _cleanup_dual_build_artifacts

前端 — store / UI
  frontend/src/stores/codingV2.ts                sealed 封口 + scaffold.done 不抢发
  frontend/src/components/coding-v2/ChatFlow.vue         6 个 watcher（含 verifyLog/codingLog/currentSpec/report）
  frontend/src/components/coding-v2/OpenQuestionsPanel.vue  琥珀警示样式
  frontend/src/components/coding-v2/ComponentSpecSummary.vue 配置项 nowrap
  frontend/src/views/coding-v2/CodingPageV2.vue  sendingMessage / confirmingSpec 拆分

文档
  docs/internal/AGENT_V2_HANDOFF_2026-04-20.md       架构总纲
  docs/internal/AGENT_V2_HANDOFF_2026-04-23.md       04-23 上午那份（进程重启恢复 + UI 重做）
  docs/internal/AGENT_V2_HANDOFF_2026-04-23_PART2.md 本文
  docs/internal/INTELLIGENT_DEV_AGENT_ARCHITECTURE_V1_2026-04-19.md  架构总纲
```

## 7. 用户风格要点（保留前两份 + 本次观察）

- **直接、严格、不给面子**。UX 细节抠到"思考卡文字跳一下"这种程度
- **希望看根因不看补丁**。每次都要"查一下为什么"、"是同一个问题吗" —— 本次多次让先解释再动手
- **中文沟通**。Commit message 必须中文
- **希望架构性修复**：单端残留能顺手清就清（"单端的按照我的要求之前都会去掉"）
- **修一项要求不引入新问题**："修了这个不要别的又出问题" —— 每轮改完要跑一遍全套测试确认
- **重复一轮的事会烦**：同一个"思考卡变"修过两次才彻底好（先是 sealed fix，再是 aggregate 合并 reasoning+content + synthetic note 改 aggregate）

## 8. 下一会话建议顺序

**优先级 1**：真实跑一遍完整 autofix 场景（故意写个漏 AC 的组件），确认 Round 1 的 fix_hint banner 真的把 LLM 行为改了。如果 LLM 还是从头 glob，考虑加强 prompt / 或者在 CodingAgent 里在 round > 0 时跳过首轮步骤。

**优先级 2**：解决 §4.1 —— 让 BrainstormAgent 感知 base_spec，这样 refine minor/major 路径也能正常工作（不只是 trivial）。

**优先级 3**：把本次所有改动 commit 掉。建议分 3 次 commit（中文）：
1. "前端 UX 修复：思考卡封口 + 滚动同步 + AI 假设样式 + 确认按钮 loading 拆分"
2. "后端 prompt 与 agent 修复：scenes_required 严格遵循 + fix_hint 接通 + 删单端残留 + aggregate 合并 reasoning"
3. "后端 refine 路径改造 + 构建产物清理 + 测试 / snapshot 跟进"

**优先级 4**：上一份 handoff 的未完成项（SCAFFOLD phase 实际执行、agent snapshot 持久化）—— 这些是上 K8s 的前提。

---

**最后提醒接手会话**：本轮大部分问题都是"前一轮改动留了半截"的结果（fix_hint 只发不读、`refine_brainstorm` 只改名没换实现、单端 prompt 没删干净）。**修任何一个功能时都要顺着数据流走完整一圈**：生产端 / 消费端 / 测试都看到，否则就是下一个 bug 的温床。
