# 交接 — 2026-06-19 大会话(代码工作区:三场景分开 / 小程序预览 / 上下文压缩)

> 换会话接手必读。本会话很长,做了 5 块工作,**全部在本地、未推 origin**,且**分裂在两个分支上**(见 §0,头号事项)。

## §0 ⚠️ 头号事项:工作分裂在两个未合并分支(零冲突可合)

中途丢了分支追踪,导致本会话的工作落到了**两个分支**,在 `7b50bd58` 分叉:

| 分支 | 顶 | 内容 |
|---|---|---|
| **dev** | `a7b4b397` | 统一工作区 Phase1-4 + **三场景重新分开** + **小程序一键预览/自动开/链接修复** + **UX 打磨** + **图片加载失败/agent 误报修复**(~45 commit) |
| **feat/desktop-login-mvp**(当前 HEAD) | `bd8c5ebe` | **#1 上下文滑动窗口压缩**(spec+plan+6 task+critical 修复,9 commit,从 7b50bd58 切——**不含 dev 的工作**) |

- 两侧改的文件**完全不重叠**(已核 `comm -12` 为空)→ **合并零冲突**。
- 推荐:`git checkout dev && git merge feat/desktop-login-mvp`(feat 的 base 7b50bd58 是 dev 祖先,把 9 个上下文压缩 commit 干净并到 dev)→ dev 成单一完整线(符合「一条线」收口意图)。
- ⚠️ **feat 的上下文压缩是在陈旧 base(7b50bd58)上做的**,本地跑测试时不含 dev 的 preview/image 改动;合并后需重跑一次全量 + 真机验。
- **dev 和 feat 都没推 origin。**

## §1 已完成(本会话)

**A. 三场景重新分开(dev: c134107d)** — 撤统一工作区入口改道:应用资产库点应用→应用工作室 `/chat`;自开发资产库点工作区→代码工作区 `/coding?workspace_id=`;二开仍从应用上下文进;左栏去「统一工作区」入口(`/workspace` 路由+代码留存不删,直 URL 可达)。

**B. 小程序代码工作区预览全打通(dev: 0fe13874 + 333ecea8)**
- agent 主动跑预览(提示词加运行/预览硬规则 + 强化 `run_workspace_preview` 工具描述);
- 跑完**自动**开预览位(`previewEpoch` 强制切,自愈轮不打扰);
- 点链接聚焦预览位 + 清干净 url(`new URL(href).origin`),不再 Tauri 主界面被导航走「回不去」;
- serve url 空头支票修复(`start_serve`/`is_serve_running` 现返回 url);30s 超时返回 `starting`;
- UX 打磨:模型名显真实 model(gpt-5.5,非陈旧 config_name「Dolphin-默认」)+ 预览卡去噪 + 打开态文件守卫(坏 fileName 不落红错)。

**C. 图片加载失败 + agent 误报修复(dev: a7b4b397)**
- 图片「加载失败」:`/raw` 端点改 `auth_from_header_or_query`(原生 `<img>` 带不了 header→401)+ 前端 `withAuthToken` 拼 `?token=`;
- agent 误报「真实数据已接通」:`_WORKFLOW_PAGE` 加铁律(build/预览成功 ≠ 真数据接通,真数据只在 aPaaS 平台运行态验)。

**D. #1 上下文滑动窗口压缩(已并入 dev:728c4063..bd8c5ebe)** — DONE,opus 终审通过(逮到并修了 2 个 critical),后端 1165 passed。
- spec `docs/superpowers/specs/2026-06-19-coding-context-compaction-design.md`,plan `docs/superpowers/plans/2026-06-19-coding-context-compaction.md`。
- 机制:Claude Code 式 compaction 适配无状态请求——跨轮 `from_snapshot` 恢复真实消息(含读过的文件结果)+ `ContextCompactor` 滑动窗口 + token 预算触发 + 413 重压重试,压缩态落 `Conversation.coding_agent_state`。
- **🔴 2026-06-20 真机 live 验暴露大坑 + 已修(commit `e1ee0932`)**:#1 的跨轮记忆**只接了 codegen(写)路径**;**读/分析路径 `run_read_query` 每轮 messages 从空起 = 完全无状态**(不是旧摘要,是零历史)。用户一上来点的全是 @skill「分析一下」→「可以的」= 读路径 → 报「没有记忆」。DB 实证所有会话 `coding_agent_state` 全 NULL(读路径不写)。修:抽 `_read_history_messages`(去末尾当前轮+截最近 12 条)+ `run_read_query` 加载 `get_conversation_history` 注入(read_query.py)。7 新测试 + 1198 passed + sonnet 评审 Approved。**残留(已知):写路径 `coding_agent_state` 为 NULL 时仍不吃读轮历史=读写未完全统一记忆(用户选了「读路径记忆」档,「读写统一」留后续)。**
- **⚠️ codegen 路径本身仍未真机 live 验**(重打桌面包 → 纯代码生成多轮迭代「改一处→基于上一轮继续→看是否记得+不重读」)。

**E. #3 @skill 接入 coding(dev:af7a8d07..03c6856d,5 commit)** — DONE,opus 全分支终审 READY TO MERGE,后端 1189 passed/前端 3/3。
- spec `docs/superpowers/specs/2026-06-19-skill-into-coding-design.md`,plan `docs/superpowers/plans/2026-06-19-skill-into-coding.md`。
- 四处接线:① 前端 `CodingPage.vue` 镜像 AIChatPage(`listSkills`+`:skills`+`onSkillPicked`);② 后端 `build_coding_tools` 加 `use_skill`(拷 skill 进 workspace + 喂 `SKILL.md` 正文,路径穿越防护);③ 抽共享 `app/agents/python_runner.py`(`run_python_in_dir`+`build_python_argv`),coding 与 ai_chat **同源委托** + coding 加 `run_python` 工具;④ pipeline **运行时**把 skill manifest 拼到 `resolve_prompt` 之后的系统提示(不碰常量/DB,绕 DB-first 陈旧)。skill 选择走 message 文本(无新 pipeline 字段)。
- **⚠️ 未真机 live 验**(与 #1 一并:重打桌面包 → /coding 输入框 @ 选上传的 superpowers skill → 看 agent 是否调 use_skill / 跑 run_python)。
- DEFER(cosmetic 未修):`python_runner` 截断后缀 `原长度→原始` / `use_skill` resolve 错误 content 英文 / 前端源码串测试可再 co-locate。

**F. #2 token 显示 + 换 session 提醒(dev:5ccd8d8a..b6f4ca1e,6 commit)** — DONE,后端 1191 passed/前端 74 passed。
- spec `docs/superpowers/specs/2026-06-20-coding-token-display-design.md`,plan `docs/superpowers/plans/2026-06-20-coding-token-display.md`。
- 四处接线:① 后端 `CodingAgent.token_usage_snapshot()` spread 进两处 codegen `done` 事件(中间层 `**event` 透传,零改);② 前端纯函数 `contextUsage.ts`(formatTokenCount/contextRatio/contextLevel);③ store + done handler + footer 显示「上下文 X% · 累计 N tok」;④ 占用 ≥80% 黄/超90k 红弹告警 banner +「一键新建会话」(调现成 createWorkspaceConversation)。
- **⚠️ opus 终审逮到真 CRITICAL(逐 task 门漏掉)**:spec 误以为 createWorkspaceConversation/换会话会触发 store reset 清告警态,其实不会 → 一键换session 后 banner 不消、跨会话泄漏。修法:`conversationId` watcher 加 `(id, oldId)` + `if(oldId!=null)` guard 清 token 态(一处覆盖三路径,且跳过 done handler mid-turn 的 null→new 首轮误清)。详见 ledger。
- **⚠️ 未真机 live 验**(与 #1/#3 一并:跑一轮看 footer 出 token,堆到 ≥80% 弹 banner,点一键换 session 看告警消+上下文清零)。

## §2 待做(各自 spec→plan→build,#1 是模板)

- ~~**#2** token 用量显示 + 换 session 提醒~~ **— DONE(见 §1 F)**。
- ~~**#3** @skill 接入 coding~~ **— DONE(见 §1 E)**。
- **#4** handoff 结构化上下文包(现状:app→/coding 的 dispatch 只带一条首消息字符串,丢 Builder 历史/确认的 SPEC)。
- **#1 + #2 + #3 live 验**(见上 D/E/F,一并真机验)。

## §3 durable 踩坑(本会话调研挖出,见记忆 [[miniprogram_preview_onehit_2026_06_19]] 全文)

1. **serve url 空头支票**:`start_serve`/`is_serve_running` 历史只回 port 不回 url,前端 `url?` 永远空 → 一键预览白等。已修。
2. **coding 提示词 DB-first 陈旧**:`resolve_prompt`(pipeline.py:2075,agent_id=whale)有 DB 行就返回,`coding_prompt_seed` insert-only → **改 `AGENT_SYSTEM_PROMPT` 常量对跑过的老租户不生效**;`backend/scripts/refresh_coding_prompts.py` 刷未自定义行。**改 coding 系统提示常量后老租户必跑刷新脚本**。(本会话 agent 误报修复刻意放 `_WORKFLOW_PAGE` 代码段=不走 DB,即时生效。)
3. **桌面 coding 走 harness 不直连 pipeline**:`run_coding_pipeline` 事件 → `HarnessManager` → **`CodingProfile.run_turn` 按 elif 链桥接到 EventBus** → `CodingSSEAdapter.translate` → 前端。**新 pipeline 事件类型要在 profile elif 链(+ SSEAdapter)登记,否则静默丢**(run_result 当初就这么丢的,已修)。
4. **图片/原生 GET 鉴权**:浏览器原生 `<img>`/`<a download>`/SSE 取需鉴权后端资源,后端用 `auth_from_header_or_query`(支持 `?token=`)、前端拼 `?token=`,别用 header-only `get_auth_context`。
5. **小程序本地预览=无平台运行时前端壳**:`npm run preview` 没 `window.df`/路由 query(formId/tabId)/真实 `$request` 端点 → 永远 mock;build/预览成功 ≠ 真数据接通,真数据只在 aPaaS 平台运行态(部署后)出。要本地看真数据 = 大活(preview 注入 window.df stub + proxy 扩真实网关 + 透传 xdaptoken)。
6. **上下文压缩的两个 critical(已修 bd8c5ebe)**:① resume 时 `is_resume=True` 跳过 `build_initial_user_message` → 新 requirement 丢失(修:resume 分支补 append);② `_compact_coding` 丢 assistant `tool_calls` → 孤儿 tool_call_id → 网关 400(修:透传 tool_calls + 后置过滤头部孤儿)。**逐 task 评审全绿但漏了这俩——全分支终审(opus)才逮到;教训:循环语义/消息协议合法性要终审 + 集成测试覆盖。**

## §4 调试/恢复法(durable)

- **桌面 coding 改后端验证不必 UI 登录**:读 `~/Library/Application Support/com.ruijing.builder/jwt_secret` 铸 token(`JWT_SECRET_KEY=<secret> ./.venv/bin/python -c "from app.auth import create_access_token; print(create_access_token(1, tenant_id=2, ...))"`)→ 直打 sidecar HTTP(端口看 `ps|grep 'ruijing-sidecar --port'`)抓 SSE / 测 `/raw`。
- **桌面冻结 sidecar**:改后端必 `bash scripts/build-desktop.sh` 重打(updater 签名报错可忽略)→ `pkill -9 -f "睿鲸 Builder"` + `pkill -9 -f ruijing-sidecar` → `open .../bundle/macos/睿鲸 Builder.app`。**每次重启会登出**(token 不跨实例/会话持久),验证要用户重登或走上面铸 token 法。
- **本机 DB 是 SQLite**:dev=`/tmp/fb_demo.db`,桌面=`~/Library/Application Support/com.ruijing.builder/app.db`;`.venv` 是 py3.13;`backend/run.py` reload=False,改后端必重启进程。
- **SDD ledger**:`.git/sdd/progress.md`(#1 的逐 task 记录在此)。访客小程序工作区:`~/Library/Application Support/com.ruijing.builder/workspaces/form-page-visitor-miniapp__1_3c274b2f`(tenant 2,conv 29)。

## §5 推荐下一步顺序

1. ~~合分支~~ **已完成**:feat→dev 零冲突合(merge `90392021`),#1 + #3 全在 dev,1189 passed。
2. **live 验 #1 + #2 + #3**:重打桌面包 → ① 多轮迭代验证 agent 跨轮记忆/不重读(#1);② /coding 跑一轮看 footer token、堆到 ≥80% 弹 banner、点一键换 session 看告警消+清零(#2);③ @ 选上传的 superpowers skill,看 agent 调 use_skill / 跑 run_python(#3)。
3. 按需推 origin(用户拍板;dev 现领先 origin 很多 commit,均本地)。
4. 续做 #4(handoff 结构化),spec→plan→build,以 #1/#2/#3 为模板。

## §6 2026-06-20 续:真机 live 验发现 + 修 + B(思维链可折叠)

dev 顶 `d8891f67`。本日全部本地未推 origin。

**live 验(桌面 v0.2.17 包)逮到并修的 3 个真问题**:
1. **读路径失忆**(`e1ee0932`):#1 跨轮记忆只接了 codegen 路径;读/分析路径 `run_read_query` 每轮 messages 从空起=完全无状态。修=注入 `get_conversation_history` 最近历史。7 测试。
2. **deploy 发布 Unauthorized**(`09f7f3fb`):非用户没权限,是 token 陈旧+上传裸调没自愈(`_ensure_env_token` token 非空不验证过期 + `_build_and_upload_kits` 上传裸 httpx 漏 `call_apaas_with_relogin`)。修=`_upload_one_kit` 撞 token 错重登重试。8 测试。
3. **对话重复 + 英文推理泄漏 = B**(`7e665c89..d8891f67`,6 commit):根因 `agent.py:596` reasoning+content 拼接。修=全栈拆分 reasoning↔content + 折叠「思考过程」卡。**opus 终审逮到 CRITICAL:回放路径 `append_event_to_stream_replay` 没同步改 → 刷新后复现,已修**。后端 1222/前端 81。

**🔑 两条 durable 教训**:
- **coding 流式 UI 特性 = 改两条路径**:live SSE + 回放 `append_event_to_stream_replay`。漏后者→刷新复现。全分支终审才抓得到(逐 task 看不见)。
- **preview 对 coding 不忠实**:大模型配置 + 登录是 desktop/web 两套逻辑,hybrid 搅一起全是杂音。纯 UI/逻辑能用 preview 省包;coding 真实行为(真 LLM)只认 desktop 打包。

**待**:① **B 真 gpt-5.5 端到端只剩 desktop 打包验**(答案出一次/reasoning 收进折叠卡/英文不混入);② 读路径记忆 + deploy 已在 11:12 桌面包,可直接桌面验;③ #4 handoff 结构化上下文包仍未做。
