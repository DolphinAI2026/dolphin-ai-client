# 深度审计:大文件 + 死代码(2026-06-13,当前工作树)

> 方法:7 区并行侦察 agent(后端 4 + 前端 2 + ai_chat/mcp 1)+ 35 条候选对抗式可达性核验(反向证明"真不可达")+ 主循环机械复核争议项。
> ⚠️ 审计对象是**未提交的工作树**:Codex 正在执行 `docs/plans/2026-06-13-bigfile-split-codex-plan.md`,mcp_server 已拆 mcp_tools 包、新增 deploy_service/workspace_access、前端 SSE reducer 已收口。

---

## 0. 当前重构进度(已核实,均干净无接线 bug)

| 项 | 状态 |
|---|---|
| mcp_server.py 10025→**814 façade** + `app/mcp_tools/` 16 子模块(9898 行) | ✅ 工具数 114=114 零丢失(AST 核过);façade 无残留工具实现;apaas_direct_tools 聚合链(→feature_builder/form_tools/runtime_tools)完整 |
| `app/coding/deploy_service.py` 抽出 | ✅ routes/coding.py 旧副本全删,agents/coding/tools.py 已改 import 它(解除反向依赖) |
| `app/coding/workspace_access.py` 抽出 | ✅ harness.py 经 re-export 取用,非第二份实现,无漂移 |
| 前端 `useAiChatSession` SSE reducer 收口 | ✅ AIChatPage 用 `createAiChatSseReducer`,无残留重复 reducer |
| **AI 兜底解析死岛**(06-12 列的 ~1.9K 行)| ✅ 已被 `262ae2cd` 删除:ai_doc_parser.py + module_standardizer.py 物理不存在,reconcile 函数族已迁 `config_postprocess.py` 接进活管线 |
| **export HR 业务数据捏造路径**(06-12 正确性炸弹)| ✅ `_render_business_enriched_design_doc` 全仓零命中,已删 |

剩余拆分尾巴(非死,待收口):**IDE-helper 族双份漂移**——`pipeline.py` 与 `routes/coding.py` 各一份 `ensure_vibe_workspace_file/ensure_cursor_rules/ide_color_theme/IDE_EXCLUDED_GLOBS`,已轻微不一致(cursor_rules 一份带 hash 缓存一份没有、glob 一个 list 一个 tuple)。两份都活(各经独立 live 链),建议抽共享模块。

---

## 1. 死代码清单(经对抗核验确认 = `confirmed_dead`)

### 1A. 后端孤儿文件(整文件可删,零外部引用)

| 文件 | 行 | 证据 | 删除注意 |
|---|---|---|---|
| `app/coding/verifier.py` | 166 | 全仓零 import/动态加载,仅 def 自身 | 无 |
| `app/services/runtime_seed.py` | 186 | 唯一外部命中是 runtime_v2.py docstring 文字,非调用 | 连带 ↓ |
| `app/models/runtime_v2.py`(PipelineRun/DeploymentHistory) | 55 | 仅被死 seeder import + create_all 建表 | 删模型不删已存在的表(留 migration 处理) |
| `app/models/agent_config.py`(AgentConfig/AgentSkill/AgentMcpBinding/AgentKnowledgeBinding) | 89 | 零 select/零实例化/零 relationship/零 FK 引用 | 同上 |
| `app/models/industry.py`(IndustryPack/IndustryPackInstall) | 74 | 唯一引用是 models/__init__ 的 re-export(noqa) | 同上 |

### 1B. 后端死符号(文件内,删符号留文件)

| 位置 | 行 | 证据 |
|---|---|---|
| `coding/workspace.py` `_scaffold_layout`/`_scaffold_plugin`/`_scaffold_form_list` | ~603 | create_workspace 脚手架分派必走前置分支,这 3 个 PROJECT_TYPE 永不可达 |
| `coding/workspace.py` `start_auto_debug` + `_ensure_debug_form` | 316 | 旧 auto-debug 流,全仓零调用 |
| `coding/workspace.py` `build_if_needed` + `list_user_workspaces` | 81 | 零调用 |
| `coding/form_component_editor.py` `_infer_component_model_field` + `_extract_component_model_field` | 66 | 零调用对 |
| `step_executor.py` `_update_existing_form` | 51 | 零调用(execute_create_form 不走它) |
| `apaas_client.py` `create_datasource` + `list_datasource_tables` + `list_datasource_table_fields` | 97 | datasource 功能未接线,零调用 |
| `field_types.py` `build_prompt_field_types_table` | 13 | 零调用 |
| `models/agent_models.py` BrainstormSession(50)/Spec(39)/CodingSession(42)/AgentTrace(45)/AgentErrorEvent(35) | 211 | 零读写;唯一残留引用源 `tests/test_spec_service.py` 已坏(import 不存在的 brainstorm/spec_service 模块) |

> ⚠️ `agent_models.py` 删除连带删坏测试 `tests/test_spec_service.py`(import 三个已不存在的生产模块,无法 collect)。注意区分:同文件里 **AgentRun/AgentStep(observability)、AgentPrompt、ConfigAssistantSkill、ConversationReplay 都是活的**,别误删。

### 1C. 后端孤儿路由(router 从未 include_router,端点 404)

| 文件 | 死端点 | 行 | 删除注意 |
|---|---|---|---|
| `routes/applications/spec_sections.py` | 整 router 4 端点 | 191 | **前端 SpecDesignPanel.vue:1292 在调→404**;但 SpecDesignPanel 是 flag 关死冷藏组件,删此 router 需与前端 SPEC 线一并决策 |
| `routes/incremental_update.py` | 9 端点(撤挂后 main.py:35 残留死 import) | ~700 | **partial**:模块本身被 spec_apply.py:797 + change_plans.py:210 import(复用其函数),删端点保留被复用函数;前端 `api/incremental.ts` 整条随之死(见 2B) |
| `routes/quick_db.py` | 2 端点(/test-connection /build-spec)+ wizard | 120 | **partial**:`_list_mysql_tables`/`_query_mysql_schemas`/`table_classifier` 被已挂载的 db_connections.py 复用,务必保留 |
| `routes/spec.py` | 3 端点(upgrade-from-legacy@77 / confirm-all / generate-config) | 120 | **high 非 certain**:router 本身活(SpecCanvas 用其他端点),仅这 3 个无消费者;upgrade-from-legacy 像一次性迁移端点,删前确认无运维脚本调 |

### 1D. 前端孤儿组件/模块(整文件可删,零引用)

| 文件 | 行 | 证据 |
|---|---|---|
| `components/MembersPanel.vue` | 835 | 零 import/标签/全局注册 |
| `components/GlobalNavRail.vue` | 620 | v2 遗留导航,零引用 |
| `components/UpdateSteps.vue` | 365 | incremental 配套 UI,随后端死 |
| `components/SideBySideDiff.vue` | 362 | **仅自递归引用(:55),无外部入口=死**(补跑 agent 误判"保留",已机械纠正) |
| `components/AppSidebar.vue` | 328 | 旧 sidebar,零引用 |
| `components/TemplateManager.vue` | 291 | 零引用 |
| `components/UsageBar.vue` | 70 | 零引用 |
| `components/DriftBanner.vue` | 68 | 零引用 |
| `components/BaseChip.vue` | 32 | 零引用 |
| `api/incremental.ts` | ~155 | ChatPage:823 仅 import 从不调用(`.incrementalApi.`=0);后端路由已死 |
| `data/builderMock.ts` | 99 | demo 数据,零引用 |
| `api/requirements.ts` | ~99 | `requirementsApi` 零引用 |
| `api/helpAssistant.ts` | 95 | `helpAssistantApi` 零引用 |
| `api/applicationMembers.ts` | 35 | `applicationMembersApi` 零引用(后端端点也未挂) |
| `stores/mcp.ts` | ? | `useMcpStore` 零引用 |

连带清理:ChatPage.vue 的 `import { incrementalApi ... }`(:823)+ `.incremental-modal*` CSS(~35 行)。

---

## 2. 对抗核验抓出的误报(标过候选但其实是活代码,**勿删**)

| 候选 | 真相 |
|---|---|
| `generator_v2.py` 6 个 `duplicate_drifted` 函数(_build_permission_groups_for_form_config / _parse_permission_ops / _sync_form_permissions_to_form_config / _finalize_created_form_config / _ensure_canvas_form_components / _save_form_config_with_retry) | **活,但与 step_executor 同名异体漂移**。两条 0-1 生成路径(generate.py 一把梭 vs generation_steps.py 分步)各持一份拷贝。不是死代码,是"改一侧漏改另一侧"的 bug 温床——`_parse_permission_ops`/`_build_permission_groups_for_form_config` 是真 bug 级漂移(权限修复只落了 step_executor 侧)。**应收进 operations/ 单一实现,不是删。** |
| `pipeline.py` IDE-helper 族 | 活(经 build_ide_url→run_coding_pipeline 两条 live 链)。是漂移重复,见 §0 尾巴 |
| `models/collaboration.py` `ProposalReview` | 活:`tests/test_collaboration_models.py` 真实例化+select+断言 |
| `apaas_client.py` `_append_desktop_api_debug_log` | 活:无条件每次 create_form_config 触发(无 branch/flag 门控)。低优先:它无开关写 ~/Desktop 完整 payload,建议加 env 门控 |
| ChatPage `messages` 数组 | **活,62 处引用**——纠正 06-12 的"write-only 零渲染"论断 |
| `config_diff.py` FormComponentChange 族 | 活:产出不被 executor 执行,但经 to_dict 序列化给前端变更预览渲染(有意设计) |

---

## 3. 大文件裁决(>1000 行)

### must_split
- **`coding/workspace.py`(5677)**:单 WorkspaceManager 类 101 方法占 ~5300 行。先删 §1B 的 7 个死方法(~1000 行)再按族切(脚手架 scaffolds.py / 构建 / 生命周期)。**全仓最该拆。**
- **`views/ChatPage.vue`(14180)**:4+ 独立业务板块挤一文件,44% 是 CSS。先删 §1D 死码 + incremental 残留,再按 `docs/plans/2026-06-13-bigfile-split-codex-plan.md` Wave 5B 三刀拆。

### should_split(有现成落点)
- **`step_executor.py`(2593)**、**`generator_v2.py`(2180)**:继续 operations/ 收口(已抽走逐字相同的 9+ 函数,剩 §2 的 6 个漂移函数待调和)。收口后 generator_v2 自然降到 ~1500。
- **`coding/pipeline.py`(2492)**:抽 IDE-helper 族(顺带解决 §0 漂移)+ brainstorm 状态机族;run_coding_pipeline 单函数 ~700 行。
- **`routes/applications/__init__.py`(3098)**、**`docs.py`(2787)**、**`section_content.py`(2689)**、**`auth.py`(2748)**:沿既有 include 模式拆子模块(见 Codex 工单 Wave 3/4)。
- **`apaas_client.py`(2929)**:78 方法单类。06-12 建议先做连接池 + typed errors 再议拆类(行为改动,另立项)。
- **`coding/form_component_editor.py`(2072)**、`components/v3/FormDesignerPanel.vue`(1776)、`RoleManagePanel.vue`(1248)、`components/v2/AppAssistantPanel.vue`(1018):可按子关注点切,不阻塞。

### already_being_split
- **`routes/coding.py`(3131←3665)**:deploy_service/workspace_access 已抽出,剩 workspace CRUD + IDE legacy(见下)。

### cohesive_ok(不拆,体量来自职责种类多非堆积)
`incremental_executor.py`(1466)、`config_diff.py`(1431)、`process_translator.py`(1278)、`routes/chat.py`(1440)、`routes/generation_steps.py`(1523)、`ai_chat/tools.py`(1647,工具分发表必须聚一起)、`ai_chat/agent.py`(1169,单类)、`mcp_tools/process_tools.py`(1009);前端 `AIChatPage.vue`(3972,已收口)、`Apps.vue`(2129)、`PlatformEnvs.vue`(1524)、`ProcessDesignerPanel.vue`(1650)、`DataSchemaEditor.vue`(1385)、`ListDesignerPanel.vue`(1181)、`RailSidebar.vue`(1058)、`WorkspaceCatalogPage.vue`(1185)、`PlatformTenants.vue`(1016)。

### 冷藏(用户决策"别删",非死码)
`components/v3/SpecDesignPanel.vue`(2481)+ SPEC 三件套:`SPEC_TAB_ENABLED=false` 关死,defineAsyncComponent 冷藏,改 flag 即解冻。

---

## 4. 高风险待裁决项(删除需对外契约,不在快赢内)

| 项 | 行 | 为何不能直接删 |
|---|---|---|
| `routes/coding.py` IDE legacy 6 端点(/workspace/{ws_id}/ide/*) | ~520 | 本仓前端零调用,但唯一消费者是**线上 code-server 睿鲸扩展**,删前须与 xhh 对契约 |
| `routes/browser.py` 整 router | 405 | 挂着但全仓零消费者(POC 遗留),可能为 agent computer-use 预留,需产品确认 |
| `spec_sections.py` router | 191 | 删它前端 SpecDesignPanel 调用点(冷藏中)要同步处理 |

---

## 5. 建议执行顺序(快赢 → 结构性)

**快赢(零/低风险,可立即删,合计 ~6000 行)**
1. 前端孤儿:9 组件(~2971)+ 4 api(~384)+ stores/mcp + builderMock(99)+ ChatPage incremental 残留(~70)。`vue-tsc -b` + `vite build` 验。
2. 后端孤儿文件:verifier.py + runtime_seed.py + runtime_v2.py + agent_config.py + industry.py(~570),连带 models/__init__ re-export 行。
3. 后端死符号:workspace.py 7 方法(~1000)+ form_component_editor 66 + step_executor 51 + apaas_client datasource 97 + field_types 13 + agent_models 211(连带删坏测试 test_spec_service.py)。
4. 孤儿路由(保留被复用 helper):spec.py 3 端点、incremental_update 9 端点 + main.py:35 死 import、quick_db 2 端点。
   - 每步:`./.venv/bin/python -c "import app.main"` + `pytest -q`(基线 738 collected;先记环境性预存败,只要求不新增)。

**中期(结构治理)**
5. operations/ 收口 generator_v2↔step_executor 6 个漂移函数(顺修权限 payload 漂移 bug)。
6. IDE-helper 族抽共享模块(消 pipeline↔routes/coding 漂移)。
7. apaas_client 连接池 + typed errors。

**结构性(各一轮)**
8. workspace.py 模板落盘 + 拆分(Codex 工单 Wave 1A)。
9. ChatPage 三刀(Wave 5B)。
10. applications/__init__、auth 拆子模块(Wave 3/4)。

**待裁决**:IDE legacy(对 xhh 契约)、browser router(产品)、SPEC 线整体去留。

---

## 附:与 06-12 分析的差异

- ✅ 已修复:AI 兜底解析死岛、export HR 捏造、config-chat 死区、影子路由、routes/coding 死尾、tsconfig strict、ChatPage messages 非 write-only。
- 🔄 纠正:06-12 说"5 逐字同/7 漂移"→ 现实是逐字同的已抽进 operations/,剩 6 个同名异体漂移待收口;"LLM transport 4 套"→ 实为 2 层(llm_transport 底层 + LLMClient 高层)都活已收口,无死分支。
- 🆕 本轮新增发现:前端孤儿组件集群(SideBySideDiff 等)、stores/mcp.ts、api/requirements.ts、3 个孤儿路由的 partial 形态、坏测试 test_spec_service.py。
