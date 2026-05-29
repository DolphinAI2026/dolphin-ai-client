# 全仓代码体检报告 — 2026-05-29

> 73 个 agent 并行扫 20 万行(后端 11.4 万 / 前端 8.7 万),每条发现逆向验证去误报。
> 原始 68 条 → 确认 58 条(剔除 10 条误报)。本报告是**待办清单**,大部分尚未修复。
> 方法: 5 域并行(apaas韧性/后端逻辑安全/可靠性/前端功能不全/死代码)→ 逐条读真代码验证 → 分级。

## 已修(本 session 3 commit,已 push)
- `a0408b9` app-config 加载提速(steps/status 不阻塞,8.5s→0.4s)
- `80c7693` 配置助手嵌入式右栏
- `2ce65b9` apaas 菜单 401 根治(`is_apaas_token_error` 加 "401"/"Unauthorized" + apaas-menus 端点套 `call_apaas_with_relogin`)

---

## 🔴 P0 — 1 条(安全,需先查暴露面再动)

### SSRF + token 注入风险
- **位置**: `backend/app/routes/auth.py:349-407, 689-762`(`exchange_apaas_token` / `_apaas_platform_login` / `_apaas_backend_login`)
- **问题**: `ExchangeApaasTokenRequest.apaas_base_url` 允许用户传任意 URL,直接发认证请求且 `verify=False` 跳过 SSL;`_extract_apaas_token()` 只校验 `value.count(".")>=1`(极弱),从返回 JSON 深递归搜 token/tenant_id 无来源校验。
- **风险**: SSRF 扫内网 / token 伪造 / 权限提升 / 数据污染。
- **置信度**: medium —— **先查 `exchange_apaas_token` 谁能调、是否对外暴露**,再决定要不要动(改认证流高风险)。
- **建议修法**: `apaas_base_url` 加白名单校验(只允许已配置的 env base_url);生产环境别用 `verify=False`。

---

## 🟠 P1 — 26 条

### A. apaas 401 自愈漏洞(15 处)—— 跟已修的菜单同根

**正确修法(验证过,别盲目套)**:
- **`apaas_tools.py` 的 11 个平台工具**(142/170/239/271/313/368/409/435/456 等)签名是 `(args, env_id, db)`,**套不了** `call_apaas_with_relogin`(它要 `fn(client)`)。
  - MCP 路径(`mcp_server.py:_call_apaas_platform_tool:1138`)**已有自愈**(`_looks_like_apaas_401`+刷token retry)→ 别在工具内重复加,会双重重登。
  - **真漏的是 Agent 路径**: `backend/app/agents/coding/tools.py` 的 `_make_platform_executor`(~193)裸调 `fn_ref`,except 只记日志不自愈。**一处修这个执行器**即覆盖全部 11 工具。
  - 修法: 复用 `is_apaas_token_error` + `_relogin_apaas_env(platform_env_id, db)`。⚠️ **签名是 `(platform_env_id, db)` 传 db session,不是 SessionLocal**(我臆测错过一次,务必先读 `apaas_tools.py:81`)。apaas_tools 失败约定返 `"Error: ..."` 字符串(不抛异常),需判 `result.startswith("Error:") and is_apaas_token_error(result)`。
- **`mcp_server.py` 5 处直接 `@mcp.tool()` 裸调**(没走 `_call_apaas_platform_tool`,真漏):
  - `list_apaas_app_processes`(1473→1489)、`get_apaas_process_detail`(1527→1547)、`deploy_process_to_apaas`(1648→1747 写接口)、`upload_external_zip_to_apaas`(2253→2312)、`_with_client`(1980→1991 包装器,给它加自愈可覆盖 republish 等)。
  - `publish_dev_package` 2318 query_app_dev_kits + 2342-2350 原生 httpx multipart upload(绕过 APaaSClient)。
- **`platform_sync.py:287`** `sync_from_platform_full` 裸调 `client.query_menus`(导入应用断)。
- **`incremental_executor.py:198/307/361`** 裸调 query_dicts/models/menus(生成失败只能手动重试)。

### B. 前端"假功能"(9 处)—— 用户能点/看着可用,点了只 alert 或 disabled
> 这些是**接真功能**不是修 bug,涉产品决策,每个要不要做由用户定。
- `ListDesignerPanel.vue:200/201` 行 [查看]/[编辑] → 只 alert
- `DataModelDetailPanel.vue:66-67` [新增字段]/[批量编辑] disabled;40/108/224 [编辑模型名]/[编辑字段] alert/disabled
- `DictEditorPanel.vue:63` [+添加选项] → alert;选项 [编辑] disabled
- `ProcessDesignerPanel.vue:661/667` [创建/编辑流程] → 只 alert
- `FormDesignerPanel.vue:682` 预览模式 [提交] → alert;字段编辑引导去对话
- `ChatPage.vue:185` 顶部 [保存] → alert("P2 接入")
- `RoleManagePanel.vue:260/572/778` 权限矩阵显示**推断值假数据**,只有 form 权限能存,model/process/app_setting 改了不存(P5)
- `ListDesignerPanel.vue:312` 列表默认显 mock 数据
- `DataSchemaEditor.vue:1370-1378` 新增/编辑数据 → alert 引导去对话

### C. 逻辑 bug(2 处)—— 真能咬人,改动小
- **`skills/orchestrator.py:129-131, 139-141`**: `create_permissions()`/`deploy_app()` 失败时 yield `status:'done'`(应 'error')→ 失败伪装成功,前端以为成了。
- **`generation_steps.py:929-934, 970-975`**: `app.status='completed'` 与 step 状态非原子,commit 失败时 UI 显示不一致(steps 有值但 status 还 running)。

---

## 🟡 P2 — 28 条(摘要,详见原始输出)

### 可靠性 / 吞异常(把失败伪装成功)
- `generation_steps.py:901-902` token 刷新失败 `except: pass` 静默
- `incremental_executor.py:515-528` 重试无熔断/退避,10 模型全失败→30 次重试风暴
- `step_executor.py:1346-1354, 2021` `gather(return_exceptions=True)` 吞 dict 绑定失败,表单缺选项无提示
- `pipeline.py:338-350, 439-444` 项目名提取/场景检测失败静默降级,yield 'done' 掩盖
- `sse.py:140-159` SSE 无 per-message 超时,上游 hang 时心跳还在但无数据→假活
- `generation_steps.py:996-1002` 重复跳过用 'ok' 状态(语义歧义,UI 分不清"创建"vs"跳过")

### 安全小坑
- `auth.py:2128-2143` `list_users` 对 platform_admin(tenant_id=None)返**全平台用户**,无租户隔离
- `auth.py:686,1008-1113` plain_password 异常堆栈可能泄漏
- `auth.py:1825-1868` delete_tenant 硬编码表列表,漏表→孤儿数据;FK 恢复失败静默吞
- `auth.py:2303-2314` invite_tenant_user 无并发唯一性检查(race→500)

### 死代码(可删)
- **`backend/` 根目录 19 个调试脚本**(check_*.py / test_*.py / compare_*.py / debug_*.py 等,非 pytest,从不被 import)
- **`frontend/src/api/incremental.ts`** 整个模块定义但 0 调用
- ⚠️ 注: agent 一度误报 `aiChat.ts`/`proposals.ts` 没用 → 验证证伪,**它们在用,别删**

---

## ⚪ P3 — 3 条(纯清理)
- 根目录 24 张**未跟踪**截图(`chat-*.png`/`v32-*.jpeg` 等,已被 .gitignore,不在仓库,本地清理即可)
- 5 个过期 .md(`PLAN.md`/`PLAN.vibe-preview-runtime.md`/`STATE.md`/`SELF_DEV.md`/`dev-upload.md`,已被 docs/handoff-* 取代)
- `frontend/src/api/workState.ts` 仅 1 处引用(可选优化)

---

## 误报样本(验证环节剔除的,记录避免重复踩)
- `auth.py:669` is_default 内存泄漏 → SQLAlchemy 脏值追踪会持久化,非 bug
- `sse.py:157` heartbeat 资源泄漏 → finally 已正确 cancel+await,标准清理模式
- `aiChat.ts`/`proposals.ts` 死模块 → 实际被频繁调用
- `orchestrator.py:99` form_results 未初始化 AttributeError → 异常路径直接 return 不会走到

---

## 执行建议(工具稳定时按批做,每批路径限定提交+测试)
1. **死代码清理**(P2/P3,零风险): 删 19 调试脚本 + incremental.ts + 过期 md
2. **P1 逻辑 bug 2 个**(改动小价值高): orchestrator status / 状态机原子性
3. **P1 401 自愈 15 处**(机制现成,按上面"正确修法"): 重点改 `_make_platform_executor` 一处覆盖 11 工具 + mcp 5 处 + sync/incremental。每改一处先读真签名再动(本机工具曾返损坏输出误导)。
4. **前端假功能 9 个**: 逐个产品决策,用户排期
5. **P0 SSRF**: 先查暴露面再定

完整原始输出(每条含 location+detail+验证依据): workflow run `wf_f21121e4-d45` 的 task output。
