# Handoff 2026-06-03 — AI Coding UED 对齐 + 模型治理 + 租户隔离

> 分支 `dev`(已全推, 顶 `a3f31bf`)。本 session 16 个 commit:`3c49136`(起) → `a3f31bf`(顶)。
> 主线:把 **AI Coding** 的体验对齐 **AI Builder / Claude Code**,顺手挖出并修了几个**模型兜底 + 租户隔离**的真问题。

---

## TL;DR(这次干完的)

1. **AI Coding 体验对齐**(对标 Builder):确认门 / 澄清门 / 「AI 思考中 Ns」计时 / 输入区常驻 + 排队消息 + 停止键 / 紧凑原生模型选择 / SPEC 收进「产物·开发文档」/ 撤语音对称。
2. **澄清升级成可点选项卡片**(`ask_clarifying_question` 工具,结构化 question+options)—— **已 live 实证**:grounded 在 通用B2B CRM 真实销售阶段上、多轮、点选自动发+置灰、刷新可还原。这是用户最早要的「选项澄清」。
3. **edit_file 红绿 diff + write_file 行号**(对齐 Claude Code,自写 LCS 零依赖)。
4. **去内置兜底模型**:Builder/Coding 都不再兜底,没配模型就提示「去平台管理 → 模型配置加」。**同时**删了 Builder 跨租户借模型的兜底(那是**租户隔离泄漏** —— 拿别租户 API Key 跑当前租户)。
5. **app 记忆持久化**(`Conversation.coding_app_id`):刷新/侧栏点开仍记得绑的是哪个应用。
6. **自开发资产库租户隔离**:老 workspace 缺 tenant_id 按 user_id 兜底导致 admin 切租户看到别租户资产 → 用会话租户推断真实归属 + 回填自愈。
7. **续轮场景误判 unsupported_script 根治**(确认 SPEC 后不再被丢)。

---

## Commit 一览(arc)

| commit | 内容 |
|---|---|
| `3c49136` | 右栏「开发文档」一等文档(对标 Builder 设计文档) |
| `f7f938b` | SPEC 确认门(出 SPEC 停住等确认) |
| `9aaf31b` | typing「AI 思考中 Ns」计时 |
| `3c963a6` | 撤 composer 语音按钮(对称) |
| `119b0bd` | 澄清门(markdown 版,后被 `79b3266` 升级成 chips) |
| `13dd0ee` | 输入区常驻 + 排队消息 + 停止生成 |
| `2641390` | 续轮场景误判 unsupported_script 根治 |
| `def6c6f` | 模型选择改紧凑原生 select |
| `c28e91c` | app 记忆持久化(coding_app_id) |
| `58aa37b` | SPEC 收进产物·开发文档 + 确认条「查看开发文档」 |
| `11d1166` | 清理旧模型选择器 popover 死代码(spawned task) |
| `c91e69f` | 自开发资产库租户隔离 |
| `b88aa7e` | 去内置兜底模型 + 提示去平台管理 |
| `6a1edf7` | 删 Builder 跨租户借模型兜底(隔离泄漏) |
| `79b3266` | 澄清 → 可点选项卡片(ask_clarifying_question) |
| `a3f31bf` | edit 红绿 diff + write 行号 |

---

## ⚠️ 重要事实 / Gotchas(下个 session 必读)

### 模型配置(全库实测)
- **种子不再自动给每个租户灌默认模型**——全库 69 租户**只有 4 条** `llm_configs`(都是 `dolphin.ai` gpt-5.5 / omnigate / purpose=all / default):租户 **1(Default)/39(交付团队)/57(产品租户)/60(mars)**。
- **去兜底后**:没配模型的租户(含 **售前POC=59**),Builder/Coding 一律提示「去平台管理 → 模型配置加」。这是**用户拍板的 A 方案**(每租户自己配,最透明,不要自动兜底)。
- **之前那个莫名 minimax 不是用户配的**,是 `agents/coding/llm_config.py` 的 `.env` 兜底默认 `api.minimax.chat/v1`(已删)。Builder 那边的 gpt-5.5 是**跨租户借来的**(已修)。
- **omnigate 网关**:`http://ai-agent.dfy.definesys.cn/omnigate/0/v1`,模型 `gpt-5.5`,OpenAI 兼容,可用。

### 测试用租户
- **产品租户(57)** = 最佳测试租户:有模型(gpt-5.5) + **4 个真实应用**(图书借阅/化工交接班/超大型制造/**通用B2B CRM** app_id=4 apaas_app_id=849609751397400576 env=56)。
- mars(60):模型 + 1 应用(易景QMS, env=59)。
- **售前POC(59):0 模型 0 …** → 现在会提示去配模型,别用它测 Coding。

### 本地环境
- 本地 DB 实际是 **SQLite**(aiosqlite),不是 config.py 默认的 MySQL。查表用 `PRAGMA`,列名 `config_name`(不是 `name`)。
- 改后端**必须重启** preview backend 才生效(改 pipeline/agent/routes)。preview serverId 每次重启会变,用 `preview_list` 查。
- `.venv/bin/python` 是 3.13(系统 `python3` 是 3.9,跑不了 `str|None`)。测试:`.venv/bin/python -m pytest`。
- **预存红测试**(与本次无关,别管):`tests/test_spec_section_o1.py`(import 不存在的 SpecSection)、`tests/test_step_executor_model_merge.py`(2)、`tests/test_auth_switch_tenant.py`+`test_platform_admin_tenant_context.py`(JWT audience 环境问题)。跑测试时 `--ignore` 掉前两个。

### Claude-in-Chrome 实测踩坑
- 中途若 preview server 被重启,**浏览器会缓存重启前的旧 JS bundle** → 新 SSE 事件(clarify/SPEC)**实时**不渲染,但**刷新就全有**(历史回放路径完好)。不是代码 bug。正常使用(首次加载)无此问题。
- 扩展偶尔断连,重试即可。原生 `<select>` 用 `javascript_tool` 设 value + dispatch `change` 来选。

---

## 🔜 下个 session 接着干

### 立即可做(小)
1. **澄清时的步骤胶囊文案** still 写「开发 SPEC 待确认」(其实是澄清)。`useCodingPipeline.ts` 的 `STEP_HANDLER.brainstorm.done` 是硬编码 `'开发 SPEC 待确认'`;clarify 时应显示「需澄清」之类。纯 label,条件化即可。
2. **完整 live E2E 收尾**:本 session 验到了 模型→绑定→grounding→澄清 chips(多轮)→刷新回放;**没一路等到** SPEC→确认门→codegen→edit diff(gpt-5.5 一轮 ~60-90s 太慢)。下次在 产品租户+通用B2B CRM 答完第 2 轮澄清,看 SPEC 收进产物 + 确认门 + 点确认后 codegen 的红绿 diff 真跑。(这几个已各自 temp preview 实测观感 + 后端单测锁逻辑。)

### 中(产品方向,之前分析出的)
3. **把 app 上下文真正喂进 codegen agent**:目前 grounding 只塑形 SPEC 文本,`CodingAgent` 的 `AgentContext` 不带 apaas_app_id/models/menus,生成的代码对接真实应用靠 SPEC 文字。要真集成得把 app 上下文(或 grounding 读到的结果)thread 进 codegen。
4. **B 方案(可选)**:若想租户开箱即用又不违反"无隐藏兜底",可让 seeding 给每租户建一条**可见可管**的 gpt-5.5(平台管理里看得到、能删)。用户当前选 A(不自动配),要做 B 得他点头。

### 测试基线
- coding/builder 相关 ~100+ 测试绿(本 session 新增:确认门/澄清门/澄清 chips/app 绑定/续轮场景兜底/租户隔离/无模型提示/Builder 不跨租户)。

---

## 关键文件(本 session 碰过)

**后端**
- `app/coding/pipeline.py` — 确认门/澄清门/澄清 chips(`ask_clarifying_question` 工具 + `__clarify__`)/续轮场景兜底/app 绑定回读/无模型预检。核心。
- `app/agents/coding/agent.py` — `before_tool_call` 给 edit_file 透传 old+new(diff 用)。
- `app/agents/coding/llm_config.py` — 去 minimax 兜底 + `NoLLMConfigError` + `NO_MODEL_HINT`。
- `app/ai_chat/agent.py` — Builder `_resolve_llm_config` 删跨租户兜底 + 统一文案。
- `app/routes/coding.py` — `_get_default_coding_model_id` 去 settings.llm_model 兜底;`list_workspaces` 租户隔离收紧。
- `app/coding/workspace.py` — `stamp_tenant_id` 回填。
- `app/models/__init__.py` + `app/database.py` — `Conversation.coding_app_id` 列 + ALTER。

**前端**
- `views/CodingPage.vue` — agentMessages 映射(clarify→ask / SPEC 收里程碑)/`onAnswerAsk`/确认条「查看开发文档」/FileCard old-content/历史回放 CLARIFY+JSON→chips。
- `views/coding/useCodingPipeline.ts` — clarify SSE handler / AbortController(停止)/ edit_file old+new / agent_tool 读 `parsed.input`。
- `views/coding/useStreamMessages.ts` — StreamMessage 加 `clarify` 类型 + `oldContent`。
- `components/FileCard.vue` — 重写:LCS 红绿 diff + 行号。
- `components/common/AgentConversation.vue` — typing 计时 prop(早前)。
- `components/FileCard.vue` / `api/coding.ts`(coding_app_id 字段)。

**测试(新增)**
`test_pipeline_brainstorm_gate` / `test_coding_clarification_gate`(含结构化 chips)/ `test_coding_continuation_scene_fallback` / `test_coding_app_binding_persistence` / `test_coding_workspace_tenant_isolation` / `test_coding_no_model_prompt` / `test_aichat_no_cross_tenant_model`。

---

## 一句话给下个 session
**Coding 体验/模型/隔离这一大轮已落地 + 大部分 live 实证(产品租户+通用B2B CRM)。** 接着干就两件小的(胶囊文案 + 跑完整 codegen diff 那段),和一件中的(app 上下文喂进 codegen)。模型用 omnigate gpt-5.5,测试租户用 产品租户(57)。
