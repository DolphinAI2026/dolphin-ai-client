# 设计 v2:Builder=配置 / Coding=开发 双支柱定位

> 日期 2026-06-01(v2 重定位,替代本文件 v1)· 状态:执行中 · 范围:仅主仓 `backend/` + `frontend/`(`mcp-server/` 副本不碰,后续删)

## 1. 定位(锁死,对齐产品两支柱「智能配置 + 智能开发」)

之前几版纠结的根:想让一个面同时干"配置"和"写代码"。本 v2 把刀切在产品本来的骨缝上:

- **AI Builder = 纯搭建 / 配置**:低代码应用配置(模型/表单/流程/权限)。工具 = **配置 MCP + 共享读 MCP**。**不做 codegen**。用户在 Builder 想写自定义代码 → **引导去 AI Coding**。
- **AI Coding = 纯开发**:自定义代码(自开发页面/组件/后端接口)。工具 = **开发 MCP(apaas_tools)+ codegen pipeline + IDE + 共享读 MCP**。**意图路由**:读/问 → 用读 MCP 直接答;建代码 → 走 codegen。
- **共享**:常规读 MCP(list 应用/模型/表单/字典)两边复用,一套维护。

**心智**:配置去 Builder,写代码去 Coding。Builder 不堆 codegen 工具(prompt 不臃肿)。

## 2. 这版要解决的核心问题
- **Coding 总写 SPEC**:Coding 现在是 codegen 流水线(detect_scene→SPEC→codegen),对"读一下有哪些应用"也硬走 codegen。→ 加**意图路由**(读 vs 建)。
- **Builder 工具/职责臃肿**:把塞进 config-chat 的自开发 codegen 摘掉 + 加引导。
- (已在 v1 完成)session 为主数据模型、删除语义、孤儿迁移、侧栏只列会话。

## 3. 范围

**已完成并提交(v1,继续有效 —— Coding 是开发主场,正需要这些)**
- B1 会话↔workspace 1:1 + 删除语义(`6e4e966`)
- B2 孤儿 workspace 迁移(幂等,`e2e4756`)
- B3 去掉强制 brainstorm 确认门(`d583dff`)
- F1 侧栏只列会话(`eab81d8`)

**本版任务**
- **N1(核心):Coding 意图路由** —— 输入先判意图:读/问 → 用共享读 MCP 工具直接答(出工具 chip + 文字),**不建 workspace、不 codegen**;建代码 → 现有 codegen 流程。修"总写 SPEC"的根。
- **N2:Builder 去自开发 codegen + 引导** —— 从 config-chat 工具白名单/SOP 摘掉自开发(create_dev_workspace/publish 等);Builder 检测到"要写代码"→ 回一个「去 AI Coding 开发」的引导(带 handoff)。
- **N3:共享读 MCP 复用** —— 确认/收敛 list 应用/模型/表单/字典 等读工具,Builder 与 Coding 共用一套(多为现状,核对一致性)。
- **F2(降级为 polish):工具卡** —— Coding 保留对话,卡片现已 work(prose 是旧数据);可选:把结构化历史也存 DB(现仅存 workspace 磁盘 chat-replay.json,workspace 没了就只剩 prose)。
- **F3:Builder→Coding handoff/引导** —— 修 handoff 字段不一致(`{app_id,app_name}` vs `{projectId,sceneCategory}`)+ 带应用上下文 + 「← 回 Builder」链。

**不做**:`mcp-server/` 副本(后删)· 引擎层(scenes/workspace/build/publish)。

## 4. 关键链路(目标态)
```
读/问:  Builder 或 Coding 输入 → 意图=读 → 调共享读 MCP(list_my_applications / list_apaas_app_models …)→ inline 工具 chip + 文字答。无 codegen。
配置:   Builder 输入 → config-chat agent 改低代码配置(模型/表单/流程/权限)。无 codegen。想写代码 → 引导去 Coding。
开发:   Coding 输入 → 意图=建代码 → detect_scene → codegen pipeline → workspace + 代码 → 工具卡 → 开 IDE 改。
```

## 5. 测试
- N1:在 Coding 问"读一下有哪些应用"→ 走读工具答(不出 SPEC);说"建个图书首页组件"→ 走 codegen。
- N2:Builder 让它写代码 → 回引导去 Coding(不再自己 codegen);config-chat 白名单不含自开发工具(`pytest test_tool_registry`)。
- F3:Builder 一键进 Coding,带应用上下文 + 能回跳。

## 6. 风险
- N1 改的是复杂的 `run_coding_pipeline` 入口(加意图门);需保证"建代码"原流程不回归。
- 意图判定误分类(把"建代码"误判成"读")→ 给保守兜底(拿不准时走原 codegen 流程,或反问)。
