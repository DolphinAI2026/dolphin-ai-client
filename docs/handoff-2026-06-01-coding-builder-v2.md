# Handoff 2026-06-01 — AI Coding/Builder v2 双支柱重定位

> 一句话:Builder=纯配置(不 codegen,想写代码引导去 Coding)· Coding=纯开发(意图路由:读→读MCP答 / 建→codegen)· 常规读 MCP 两边复用。映射产品「智能配置 + 智能开发」。

## 定位(v2,已锁)
- **AI Builder** = 智能配置:对话搭表单/数据模型/流程/权限,**不再写自开发代码**。用户要写代码 → 引导去 AI Coding。
- **AI Coding** = 智能开发:首轮先**意图路由**——
  - READ(读/问:"有哪些应用""看下这个表结构")→ 走只读 MCP 工具直接回答,**不写 SPEC、不建 workspace**。
  - BUILD(建/改:"做个图书首页双端组件")→ 走原 codegen 管线(detect_scene→inline SPEC→生成)。
- 常规**只读 MCP 工具两边复用**(list_apaas_apps 等)。
- spec: `docs/superpowers/specs/2026-06-01-ai-coding-overhaul-design.md` (v2)
- plan: `docs/superpowers/plans/2026-06-01-ai-coding-overhaul.md`

## 已完成 + 提交(dev 分支,倒序)
| commit | 内容 |
|---|---|
| 20df9f9 | READ 路径**持久化会话历史** + 回看渲染为正常消息(不进思考卡) |
| 6a7c4fc | N1 读路径补完:读工具走 `_call_apaas_platform_tool` token 自愈(**修 401**)+ 前端工具卡/清占位 |
| fe78708 | **N2** Builder 去自开发 codegen(tool_registry 白名单摘 15 工具,82→67)+ 引导文案 |
| 1f7f156 | **N1** 意图路由:`read_query.py`(classify_coding_intent + run_read_query)+ pipeline 首轮意图门 |
| d678bb7 | spec v2 重定位文档 |
| eab81d8 | **F1** 侧栏只列会话,消灭 conv:/ws: 双轨 |
| d583dff | **B3** 去首轮 brainstorm 强制确认门,proposal 转 inline SPEC 直接 codegen |
| e2e4756 | **B2** 孤儿 workspace 迁移脚本(幂等,main.py lifespan 启动跑) |
| 6e4e966 | **B1** delete_coding_conversation 删除语义(会话+workspace 1:1)+ 测试 |
| 19d98d5 | 会话删除按钮 + 恢复 Coding 模型选择器 + 自开发页移除冗余 3 按钮 |
| bb7475f | 登录时给租户 env 灌账号密码(token 自愈可用)+ 修"token 为空"误导文案 |

## 已 live 验证(preview 实测)
- **N1 读意图**:问"读一下现在有哪些应用"→ 返回 26 应用 markdown 表格(RUNNING 11/SHUTDOWN 15),**不再写 SPEC**。意图分类 read/build 准。
- **读工具 401 自愈**:首调触发 MANAGE 重登 → 200。
- **读路径持久化**:会话存 user+assistant 两条;刷新/回看历史完整显示为表格消息(非折叠思考卡)。
- **× 删除**:删会话连带清 workspace 目录(用户实测删了 5 个测试会话,行为正确)。
- B4(结构化工具事件 SSE)、F2(前端工具卡渲染)其实代码早已存在,本轮接通即生效。

## 剩余(下次开干)
- ✅ **F3 已完成(6dce9a5)**:消费端补读 app_id(URL)+ app_name(payload,之前被丢)+ 会话表头「← 回 Builder 配置「{app}」」回跳链(两种布局都显示)。live 验证往返通。注:真因不是「字段完全不一致」——app_id 一直在 URL query 里,只有 app_name 被丢 + 缺回跳 UI。
- ✅ **N3 已核对**:8 个核心读工具两边一致 + 都走 apaas_client 共享层。3 个 latent 缺口:① 命名分叉 list_apaas_apps vs list_apaas_apps_in_env;② Coding 读路径是子集(缺 roles/processes/business-events/permissions,apaas_tools.py 未定义);③ 三套目录非单一真相。
- ✅ **F2 已完成(a71024b)**:实时工具卡(Step2/3)早已工作;本次补 Step4——直达 `/coding?conversation_id=N`(URL 无 workspace_id)的 codegen 会话,onMounted 先查 workspace → 有则 openWorkspaceById 恢复 stream_messages 富工具卡(与侧栏一致),无则降级纯文本。注:富 replay 走 workspace chat-replay.json(非 DB);parseAssistantHistory 保留为无结构化数据的兜底。build 验证过;live 视觉待用户重登(token 过期)。
- **mcp-server/**(~27 万行,占仓库 40% 的副本)后续整体删——见 ai_coding_prd_direction。
- 后台任务 chip(已甩):7 个陈旧失败测试 / 同步 config-chat 端点缺引导 / (可选)N3 三缺口。

## 全模块测试结果(2026-06-02)
跑了完整全模块测试,**本轮 11 commit 零回归**。
- 后端 pytest:**427 passed** / 6 failed(全陈旧,父提交上同样失败,已铁证)/ 1 collection 错(陈旧 SpecSection);本轮新增 60 测试全绿。
- 集成(真打 apaas-trial):意图分类 11/11、读工具→26 应用(401 自愈)、读路径持久化存 user+assistant。
- 前端:`vite build` ✓;我改的 3 文件 0 TS 错(`vue-tsc` 严格检查 dev 上早已 400+ 陈旧错,非本轮)。
- Live:READ 表格 / 回看历史 / 侧栏只列会话 / × 删除 / 模型选择器 全 ✓;**BUILD→codegen 完整跑通**(detect_scene=web_component_dual → 32 产物 + 双端 build 成功);**Builder config-chat-stream 正确引导去 AI Coding 不吐代码**。
- 两个发现(已甩后台任务):① 7 个陈旧失败测试(JWT aud / create_access_token 签名 / query_models / SpecSection);② **同步 `/config-chat`(applications/__init__.py:2573)缺引导块**(会吐代码),UI 走 stream 不受影响,但端点活着——需补引导或删死端点。

## 2026-06-02 UX 反馈轮 + UI 统一立项
用户 live 试用后的快速反馈,已修:
- **da7c254** 产物面板不再空弹(自动显示去 isStreaming,仅有产物才弹)+ Coding 首条占位改中性「正在理解你的需求」(READ 不再误显「识别开发场景」)。
- **51e3cf8** Builder `list_my_applications` 改查 **apaas 平台全量(26)**,与 Coding 一致(之前 Builder 查本地库 2 个、Coding 查 apaas 26,用户问「为啥不一样」)。解析租户默认 env→查 apaas,无 env 降级本地。
- **fd2e89e** 还原:**模型名 dolphin.ai 是预期名,勿改**(我一度误当陈旧名改掉,已撤销 dc18d85 + DB 改回)。
- **9358edd** 🎯 **UI/UX 统一立项 spec**:`docs/superpowers/specs/2026-06-02-coding-builder-ui-unification.md` —— Coding 会话区复用 Builder `AgentConversation`,统一工具卡/表格列/间距颜色/布局空态。**待独立 session 带可视化迭代执行**(本轮卡登出态盲改故立项;composer 已共用 UnifiedChatComposer 不动)。
- ⚠️ 教训:UI/UX 视觉活必须能登录看 live 再改;盲改复杂会话区 = 高风险。

## 环境 / key context(踩坑速查)
- **dev 分支共享**(与 xhh 协作),commit 前先 `git pull --rebase`。
- 本地 `backend/.env`(**gitignored,勿提交**):`APAAS_BASE_URL=https://apaas-trial.definesys.cn/backend`、`CODE_SERVER_BASE_URL=http://127.0.0.1:8080`、`DATABASE_URL=sqlite+aiosqlite:////tmp/fb_demo.db`、`APAAS_ENCRYPTION_KEY`、`JWT_SECRET_KEY=demo-secret-local`、`LLM_API_KEY=demo`。线上无 APAAS_BASE_URL(故本地需手配)。
- workspace 根:`~/.apaas-builder-ai/workspaces`(仓库路径含空格,故落 home)。
- **登录**:用真 aPaaS 平台管理员账号(产品租户 tid=57, user_id=1)。配 APAAS_BASE_URL 后本地 seed admin 不再可用。
- preview servers(本机调试,**重启走 preview_stop+preview_start 别 nohup**):backend(8000)/frontend(5173)/admin-spa(5174)/code-server(8080)。`lsof -ti :8000 -sTCP:LISTEN` 释放(必带 -sTCP:LISTEN,否则杀浏览器连接)。
- **两套 coding 后端**:老 `run_coding_pipeline`(harness/coding/pipeline,UI 在用,**N1 改的是这套**)+ `coding/v2`(未接 UI)。改前认准。
- tsconfig.app.json `noUnusedLocals:true` → build 跑 `vue-tsc -b` → **死代码会断 build**(删按钮要连带删 import/handler)。
- 消息持久化:stream_messages 落 workspace `chat-replay.json`(非 DB);`messages` 表只有 id/conversation_id/role/content/created_at。
