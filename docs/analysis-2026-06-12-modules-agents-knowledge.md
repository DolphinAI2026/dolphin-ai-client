# ai-builder 深度分析:模块/大文件 · Agent 引擎对比 · 知识/Skills/MCP 管理(2026-06-12)

> 产出方式:10 个并行分析 agent 深读(8 模块 + Claude Code 引擎对比 + 知识管理盘点)+ 高严重度论断对抗核验。
> 核验状态:14 条 high 论断中 5 条通过对抗核验(全部成立),9 条因会话限额未跑核验(但均带 file:line 证据、标注 certain);其中「AI 兜底解析死链」一条已人工补验成立。
> 规模基线:backend/app 111,825 行 Python;frontend/src 87,277 行 Vue/TS。

---

## 一、模块地图与大文件解析

### 1.1 后端模块健康度总表

| 模块 | 核心文件(行数) | 健康度 | 一句话诊断 |
|---|---|---|---|
| MCP 工具层 | mcp_server.py(10592) | 巨石需拆 | 125 个工具/14 个域挤一个文件,活跃维护非遗留 |
| Coding 链 | workspace.py(5677)/pipeline.py(2495)/routes/coding.py(3835) | 两个巨石 | workspace 40% 是内联模板字符串;routes 层养着部署编排被 agent 反向依赖 |
| unified 引擎 | ai_chat/agent.py(1312)/tools.py(1930) | 偏大 | 事实上的最佳 agent 底座,但历史上下文无压缩 |
| Builder 路由 | applications/__init__.py(4228)/docs.py(2787)/section_content.py(2655) | 巨石需拆 | __init__ 里 ~1320 行是 config-chat 死码 + 影子路由 |
| 0-1 生成管线 | generator_v2(2373)/step_executor(2777)/incremental_executor(1466) | 三引擎并存 | 16 个拷贝函数已漂移,修 bug 只落单侧 |
| 基础设施 | apaas_client.py(2929)/auth.py(2748)/llm_client.py(719) | 大杂烩 | 80 方法单类、63 处一次性 httpx(verify=False)、LLM transport 4 套 |

前端:ChatPage.vue(14172,44% 是 CSS)、CodingPage.vue(4933,62% CSS)、AIChatPage.vue(3933)、SpecDesignPanel.vue(2465,被 flag 关死)。

### 1.2 已坐实的高价值问题(按危害排)

**正确性炸弹**
1. `export_apaas_app_design_doc` 凭关键词捏造业务数据(✅对抗核验成立):应用名/菜单命中 'hr/人力/project' 等词且元数据偏泛型时,走 `_render_business_enriched_design_doc` 输出整套硬编码「HR人力成本」设计文档(4角色/7字典/6模型全是假的),下游 generate 会照此建错应用。ai_chat/tools.py:700-701 分流、858-898 关键词门、924-1166 硬编码。**修法:删 ~310 行 enrichment 路径,元数据稀疏时返回 warning。**
2. AI 兜底解析死岛 ~1.9K 行,06-05 的修复落在不可达路径上(✅人工补验):`parse_document` 自 85b5dce4(04-30)起严格模式直接抛 DocNotStandardError;`parse_doc_with_ai` 唯一调用链是零调用方的 `_fallback_ai_parse`(doc_pipeline.py:390,grep 全仓仅注释提及)。但 db2882ae(06-05 下拉↔字典调和)修在 ai_doc_parser.py 内部 = 修在死路上。**必须裁决:要么在上传路径 catch DocNotStandardError 接回兜底,要么删 ai_doc_parser(留 config_assembler 引用的 _sanitize_codes/_fill_icons/_dedup_dicts)+ module_standardizer(312行)整岛,并把 reconcile/downgrade 函数族移植到活的确定性管线或 repair 脚本。**
3. `spec_sections` 路由器从未注册,前端调用必 404(✅核验成立):spec_sections.py 定义 4 路由但 __init__.py:2144-2187 的 include 清单没有它;SpecDesignPanel.vue:1292 在调。一行 include 修活,或连前端 compare 分支一起下线。
4. `get_role_resource_matrix` 返回 100% mock 推断矩阵且在 config 助手白名单内(mcp_server.py:4285,is_mock:True 但 LLM 很可能当真数据陈述)。
5. agents/coding/tools.py:114 读不存在的 `conv.application_id`(模型只有 coding_app_id),env 三级解析第 2 级永远静默失效。
6. 静默丢数据:管线 13 文件 102 处「非法即 continue」,真丢点 ~40 处集中在 forms.py 子表链(429/440/450/684)、models.py(140/160/165/181)、config_diff.py 11 处空 key join(增量更新无声漏改)。warnings 通道范式已有(process_translator),照抄铺完即可。
7. GET /{app_id} 影子路由:__init__.py:742 与 1928 重复注册,1928 版永不可达且缺 06-01 的跨租户兜底修复——谁改它就是改影子。

**架构债**
8. routes/coding.py(✅核验成立):~600 行部署编排(_build_and_upload_kits/_deploy_to_app_impl)住在路由层,agents/coding/tools.py:311-331 反向 import 路由私有函数;另有 ~1390 行 code-server IDE 面本仓零调用(唯一消费者=线上 code-server 睿鲸扩展,删前须与 xhh 对契约);尾部 165 行确定死代码(3 个 pipeline 旧副本 + 裸 LLMClient())。
9. IDE helper 双份漂移(✅核验成立):ensure_cursor_rules 等 4 函数在 pipeline.py:96-263 与 routes/coding.py:89-360 各一份且行为已分叉,两份的模板目录在磁盘都不存在(复制段实为 no-op)。
10. apaas_client.py:80 方法单类、63 处一次性 httpx.AsyncClient(verify=False) 无连接池、错误全是 raise Exception(message) 迫使调用方字符串匹配(401 误判事故结构根源);call_apaas_with_relogin 覆盖 22 处 vs 直连 53 处,incremental_update.py:737 另造一套刷新。低优先:_append_desktop_api_debug_log 无开关写 ~/Desktop 完整 payload。
11. 0-1 三执行器并存:generator_v2(全量)/step_executor(分步)/incremental_executor(增量),16 个近似拷贝函数(5 逐字同/7 已漂移);b14a434d 下拉绑字典修复只落 generator_v2,step 侧大概率仍有同款 bug。operations/ 共享层立了牌坊只搬了 identifiers.py。审批流 payload 构造有 4 套(step_executor 内联/process_payload/process_translator/mcp_server:7742 副本)。
12. section_content 180s 缓存:force 逃生门后端只修 2/10 端点(421/1176),前端只修 3/7 面板;ListDesignerPanel 的刷新按钮(:35)点了仍读 stale。写路径失效 invalidate 全仓仅 2 处调用,MCP 写工具不触发。

**前端**
13. ChatPage.vue 14172 行解剖:template 806 / script 7147 / style 6212(44%!);246 顶层函数/128 ref/106 computed;至少 4 代重设计沉积。strict 检查实测 143 个 unused 符号;messages 数组(L2694)53 处写入、模板零渲染(write-only 遗留层)。
14. 类型门禁被静默放宽:fb322dd3(06-05, xhh)把 tsconfig.app.json strict→false,现在 `npx vue-tsc -b` exit 0。**「~388 预存错只能 build:nocheck」的认知已过时**;恢复 strict:true 实测仅 19 错(30 秒级标注修复)。noUnusedLocals 留到 ChatPage 死码清完再开。
15. unified SSE reducer 双份手工同步:AIChatPage.handleSseEvent(L1907-2029) vs useAiChatSession(L451 自述「忠实复制」),13 个 case 当前完全一致=零成本收口窗口;后端每加事件必须双改。
16. 前端死码清单(全部 grep 求证零引用):config-chat 整链 ~2901 行(ConfigAssistantPanel+config-assistant/+api/configChat.ts;⚠️usePanelResize.ts 是活的须先搬)、SectionNav(562,ChatPage:846 死 import)、OnboardingTour(418)、ShellTopBar(183)、ProcessNodePropsPanel(739)、AppConfigTopTabs(177)、BuilderCommandPalette、structuredDoc.ts 后半 standardDocMdToStructuredDoc ~310 行。
17. 悬置待决策:SPEC 设计三件套 ~4.1K 行被 SPEC_TAB_ENABLED=false 关死仍付维护税(ChatPage:2306 注释「别删」是用户决策,动前必须问);BuilderDevOpsPage(2209)+proposals/git-sync 栈前后端 ~4-5K 行,xhh 的 bbef79e5 删除被 167d71c5 整体 revert,处于悬置。

### 1.3 大文件拆分方案(具体切法)

**mcp_server.py → app/mcp_tools/ 包**(原文件留 façade,17 处外部 import 零改动):
- core.py(~400):FastMCP 实例 + trusted_identity/_resolve_identity + 四条共享桥(_with_client/_call_apaas_platform_tool/_api_call*)
- 按域 13 模块:app_lifecycle(17工具)/apaas_read(11)/process(5+30helper,1.9K)/dict_model(10)/menu_form(9)/form_components(8)/roles_perms(9)/business_events(12,暂停)/self_dev(11)/dev_workspace(14)/browser(11+CDP桥)/config_skills/issue_assistant
- façade 依次 import 全部子模块后跑 drift check;**必须同步改 test_tool_registry.py 的 _extract_mcp_tool_names_from_source(现硬编码读单文件 AST)**。分 3-4 个 PR 按域搬,drift 测试是现成安全网。
- 顺手抽 @apaas_tool 装饰器:37 处身份解析 + 声明式参数校验 + _ok()/_err() 构造(替代 374 处手写信封,error_code 收进常量清单);401 自愈 4 个变体收口(upload_external_zip_to_apaas:3285 手写副本最该先收)。

**workspace.py 5677→~1500**:第一刀把 3414-5677 的 ~2260 行内联脚手架模板落盘成 backend/templates/ 文件树(已有 _scaffold_from_template 机制);第二刀拆 installer/builder/debug_runner(顺修 :2293 硬编码本机路径)/compat。

**routes/coding.py**:部署编排抽 app/coding/deploy_service.py(解除 agents→routes 反向依赖,瘦 ~800 行);IDE 面与 xhh 对齐契约后迁 routes/ide_legacy.py 或砍(连带 vibe_* 命名清零);死尾 165 行立删。

**applications/__init__.py 4228→<500**:删 config-chat 死区(2842-3716)后,沿既有 include 模式拆 crud/lifecycle/apaas_menus/chat_bridge 四个子模块。

**ChatPage.vue 拆分三刀**(先删 143 个 unused 再动刀):①部署/更新进度面板→DeployProgressPanel+useDeployPipeline(~2500-3500 行,边界最清晰)②文档版本 4 个 dialog→DocVersionsDialogs+useDocVersions(~1200-1800)③平台配置 tab 壳→useAppConfigTabs;CSS 随组件走(两巨石一半体量其实是 CSS 问题)。

**apaas_client.py**:不急拆类;先共享 AsyncClient 连接池 + typed errors(APaaSBusinessError(code,message),is_apaas_token_error 改 isinstance)。auth.py 拆三件套(认证/tenants_admin/tenant_members,纯搬移)。

---

## 二、对比 Claude Code 引擎:agent 收敛方案

### 2.1 现状纠偏:不是 4 套循环,是 6 套 tool-loop + 2 类单发流

| # | 循环 | 位置 | 状态 |
|---|---|---|---|
| L1 | unified run_agent | ai_chat/agent.py:858(1312行) | **底座候选**,服务 AIChatPage+配置助手 AppAssistantPanel |
| L2 | BaseAgent+CodingAgent | agents/base.py(698)+agents/coding/agent.py(604) | codegen 用;BaseAgent 一半机器已死 |
| L3 | SpecAgent | builder_spec/agent.py(588) | 0→1 主线;文件内 run/bootstrap_from_doc 两份重复 loop |
| L4 | config-chat | applications/__init__.py:3138-3702(~864行) | **前端已死,整段可删** |
| L5 | read_query | coding/read_query.py:691-905 | READ 意图只读问答 |
| L6 | _grounded_brainstorm | pipeline.py:1513-1652 | 绑应用首轮 brainstorm |

另:spec_chat.py(1014,单发 LLM 从正文抠 JSON patch + mock 兜底)和 pipeline 意图分类单发。BaseAgent 全仓唯一子类=CodingAgent(grep 实证)。

### 2.2 对照 Claude Code 六维度

1. **单一主循环**:Claude Code 一个 tool-use loop 服务所有场景。ai-builder 六套循环在流式/工具分发(串行vs并行)/错误恢复/中断/落库/观测上全部各异。**底座判定:run_agent 成立**——唯一接 observability recorder+真实 token 采集、唯一有 ToolSearch 延迟加载、持久化/abort/错误可见化最完整、git 最活跃。但当底座前必须先从 L2 吸收 4 件:并行工具执行(base.py:616)、nudge/循环检测 hook、循环内上下文压缩 hook、工具自定义事件透传(现在只对 write_artifact 硬编码特判 :1243);且要把与 AIChatSession 表的强耦合抽成 persistence adapter——这是收敛的最大单点工程量。
2. **工具系统**:Claude Code=静态+MCP+ToolSearch 单管线。ai-builder=两套注册表(tool_registry.yaml 真承重 + harness/tool_registry.py 薄皮)+ 四张硬编码本地表 + 两份 ToolSearch 实现。收敛:yaml 升级为唯一事实源(本地工具加 kind:local,agents→profiles 语义);真正的工作量是统一 ToolContext(coding 签名 (args,workspace_path,cb) vs ai_chat (name,args,session,db))。
3. **上下文管理**:没有任何一条链有 token 阈值触发的自动摘要。ContextCompactor(context_compact.py,300行)≈microcompact 但只有 CodingAgent 用;run_agent 的 _build_initial_messages 全量回放历史无窗口(✅核验成立,长会话必撑爆)。优势:run_agent 已采真实 prompt_tokens(:1011),autoCompact 触发条件可以用真数。
4. **子代理**:无等价物。引入场景按收益:0-1 大文档分块解析(盲合并曾出 db2882ae 事故,fan-out+主 agent 调和正合适)、codegen 写后自检(干净上下文跑 build)、批量配置。**应在引擎统一后做,否则是第 7 套循环。**
5. **Skills/系统提示**:领域知识散布(grep '你是' 命中 18 文件);doc_spec_standard.py 是已收口典范且已暴露成 MCP 工具(「知识即工具」先例)。ai_chat 的 deferred-manifest 机制可平移到知识块(manifest 列条目+load_skill 按需注入)。⚠️已有两套 DB prompt 覆盖(prompt_resolver agent_id='whale' + builder agent_prompts),skills loader 须顺手统一,否则变三套。
6. **确认门**:ask_clarifying_question 现存 3 份(builder_spec/tools.py:40、ai_chat/tools.py:544 的 _special:ask_user、pipeline.py:1568 内联)+ brainstorm marker 状态机第 4 种门。收敛为引擎级 ask_user 协议(工具结果带 should_pause→事件+pending 持久化→awaiting_user 收尾→续轮即普通新 turn,采纳 ai_chat 无状态实现);Spec Decision 卡片只是 options 渲染变体。BaseAgent 13 个 hook 只保留 5 个有用的。

### 2.3 收敛路线图

- **Step 0 删 L4 config-chat 死区**(独立可做,净减 ~4200 行):前端 ConfigAssistantPanel 链 + 后端 :2842-3716 + config_chat_sessions.py + models/config_chat.py。前置:usePanelResize.ts 搬家;L4 prompt 里的错误码自愈/verify-after-execute 知识先抢救成 skill 文件;ConfigAssistantSkill 自学习机制决定移植 unified 还是放弃;browser_* 能力回退需产品确认。
- **Step 1 SpecAgent 迁底座**(builder_spec/agent.py 消失,tools.py 留作 spec profile):前置=引擎支持工具声明式自定义事件(spec_patch);收益=消文件内双 loop+Builder 线 token 观测补齐。风险:save_spec_rebased 每 patch 即时落库语义要保住。
- **Step 2 read_query/grounding 化为 preset**(~350 行循环消失):read_query 是最干净的 profile 样本;chat-replay.json 富回放格式是 IDE 侧契约,事件适配器逐字段对照。
- **Step 3 codegen 最后迁**(BaseAgent+CodingAgent+adapter.py 共 ~1500 行消失):风险最高(事件词表最富),flag 切换+事件快照测试;直接红利=codegen 进 recorder(现在 InMemoryTraceWriter 跑完即丢)+token 采集(现在恒 0)。
- **Step 4 ask_user 协议归一 + skills loader。**
- 不等收敛可先做:统一 LLM transport(现 4 套:ai_chat 自带 httpx 栈/builder_spec _open_stream/pipeline 3 条裸 httpx/LLMClient,以 ai_chat 版为基底抽 app/llm_transport.py,observability Phase2 埋点从改 3 处变 0 处);BaseAgent 裁死肉 ~200 行并冻结(禁止新子类)。

---

## 三、知识库/Skills/MCP 要不要抽象统一管理

结论:**不建三合一大平台,不新造机制;两张已有的表 + 一份 yaml 各管一段,补缺口。** MCP 治理已及格(yaml+启动 drift check+CI 双保险是全仓少数做对的治理);真正的债是 ①prompt 散布且最大流量入口没接 DB ②skills 机制建好了没人能运营 ③config-chat 死码贡献重复副本。

现状关键事实:
- 「上线一个工具」最少改 3 处(实现+yaml+白名单快照测试),要进 coding 本地 loop 再 +3~4 处,最坏 6-8 处。
- tool_registry.yaml 的 description/sections 维度是死字段(LLM 看的描述真源=FastMCP docstring,mcp_bridge.py:131),已实际漂移;agents 白名单是真承重。
- `agent_prompts` 表(tenant×agent×phase):builder/whale 已 DB-first+lazy seed,REST CRUD 已挂载(/api/agent-prompts)——**但前端零调用,且 unified 最大入口没接**(SYSTEM_PROMPT_UNIFIED 仍 hardcode,里面「工具速查 55 个」与实际 ~85 不符)。
- `config_assistant_skills` 表:**Skills 管理的完整雏形已存在**——4 个 MCP 读写工具(save/list/get/delete)+ 索引注入(app_context.py:68-89 只注 name+keywords 一行,top20)+ get_config_skill 按需拉全文。缺管理 UI、人工编辑入口、平台级 scope;本地库 0 行,生产大概率也近零=「建好了没人住」。

方案:
- a) 数据模型:MCP 元数据留 yaml 不进 DB(进 DB 必漂移);prompt 模板用 agent_prompts(已有);Skills+领域知识扩展 config_assistant_skills 一次轻量 migration(tenant_id 放开 NULL=平台级、加 kind: skill|knowledge、agent_scope、source: ai_learned|admin)。作用域三级=平台/租户/应用,合并逻辑 app_context._load_skills 已写一半。
- 进 DB 的铁律:与解析器/脚手架代码同步演化的知识(doc_spec_standard/lowcode_standards/模板本体)留代码同 commit 走;纯操作经验/租户个性化进 DB。
- b) 管理界面:平台管理后台新增「Agent 知识库」页,三 tab:①Prompt 模板(**直接吃现成 API,纯前端工作,全场最便宜**)②Skills/知识条目(补 REST CRUD)③工具白名单只读视图。白名单编辑不做 UI(应过 git review)。
- c) 消费:沿用现成三层=必注入(系统提示+文档规范 ~2-3K token)/索引注入(每 100 条知识仅 +2-4K token)/按需拉取(get_config_skill+search_deferred_tools 都已落地)。125 工具全量注入≈25-35K token/轮,core+manifest 已≈8-12K;新增知识一律走索引+按需。
- d) 演进:Phase 0 删 config-chat 死链(消 prompt/skill 注入副本各一);Phase 1(最值,1-2 天)agent_prompts 管理页 + SYSTEM_PROMPT_UNIFIED 接 prompt_resolver;Phase 2 skills 表扩展+REST+管理 tab,从 apaas_backend_templates 挑 2-3 条坑知识试点,**用起来了再扩**;Phase 3(按痛感)coding tool-loop 从 yaml 生成 schema,6-8 处收到 3-4 处。
- 明确不建议:工具元数据进 DB、运行时动态注册 MCP、三表合一、向量检索(这个量级关键词够)、Skills 版本/审批流。

---

## 四、合并行动清单

**快赢(各 ≤半天,零/低风险)**
1. 删 export 工具 HR 捏造路径(~310 行,正确性炸弹)
2. spec_sections 一行 include 修活(或决策下线)+ 删 GET /{app_id} 影子路由
3. 修 conv.application_id 死字段;CodingAgent 补 stream_options.include_usage(token 不再恒 0)
4. 恢复 tsconfig strict:true(仅 19 错);删前端死码 ~5.3K 行(config-chat 链+5 死组件,usePanelResize 先搬)
5. 删 routes/coding.py 死尾 165 行;收口 IDE helper 双份
6. section_content 余下 8 端点补 force + 4 面板补穿透(或直接抽 useSectionContent composable 一并解决)
7. AIChatPage 切 useAiChatSession,收口双 SSE reducer(13 case 一致是最佳窗口)

**裁决项(需大明哥/产品拍板)**
- AI 兜底解析死岛:复活接线 or 删 1.9K 行+移植 reconcile 函数
- SPEC 设计三件套 4.1K 行:恢复/defineAsyncComponent 冷藏/砍
- BuilderDevOpsPage+proposals 栈:与 xhh 对齐 bbef79e5 revert 原因后定去留
- code-server IDE 面 1390 行:与 xhh 对契约
- ConfigAssistantSkill 自学习:移植 unified 还是放弃

**中期(1-3 天/项)**
- config-chat 死区整删(后端 ~1320+前端 ~2900)
- 统一 LLM transport(observability Phase2 前置)
- generator_v2↔step_executor 16 拷贝函数收进 operations/(顺修 step 侧字典绑定缺口)
- 静默丢数据 ~40 真丢点铺 warnings 通道
- agent_prompts 管理页 + unified 接 DB prompt
- 401 自愈收口(wrapper 上移+合并 incremental 副本+routes 禁裸 APaaSClient)
- ChatPage 拆分第 1 刀(部署进度面板)
- mcp_server @apaas_tool 装饰器

**结构性(各一轮专门会话)**
- mcp_server.py 按域拆包(3-4 个 PR)
- workspace.py 模板落盘+拆分
- agent 引擎收敛 Step 0-4(上文路线图)
- 0-1 执行引擎二合一(generator_v2 退化为编排壳复用 execute_* 原语)
- ChatPage 第 2/3 刀 + CSS 随组件走

**未核验提示**:9 条 high 论断(LLM transport 4 套/apaas_client 大杂烩/ChatPage 死码计数/code-server IDE 面/generator-step 漂移/config-chat 行数等)因限额未过对抗核验,动手前按各条 evidence 行号先花 2 分钟复核。
