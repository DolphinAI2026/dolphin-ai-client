# 交接 — 2026-05-29 性能/401/全仓体检/UI 清理 session

> 分支 `local/ui-redesign-2026-05-20`，HEAD `9fc668d`，**全部已 push、`0 0` 同步、工作区干净**。
> 接上个 session 的 `b44cfb4`。本 session 12 个 commit(`a0408b9`..`9fc668d`)。
> ⚠️ **共享分支**：可能有并行 vibe/ai-coding session 交织 → 提交务必**路径限定** `git commit -- <path>`，别裸 commit。

---

## 一、本 session 干了什么（12 commit，全 push）

```
9fc668d chore  删 designer 区两个死按钮（页面设置 sub-tab + 表单 header 保存）
74fdd10 feat   暂隐藏「设计」(spec) tab — 进应用直接走「功能」+ 配置助手对话
f4a1618 chore  删顶栏「保存」空壳按钮
f9be44b fix    堵 exchange-apaas-token 未授权 SSRF — apaas_base_url 白名单（P0）
5583ec4 fix    修顶栏面包屑窄屏压成竖排撑高 — 长应用名截断
feefb48 fix    后端可靠性批（失败掩盖/吞异常/重试风暴，7 agent + 人工 review）
3f3fb82 fix    401 自愈补全 6 处裸调
de81a3a chore  清理死代码（删 19 个 backend 调试脚本）
06d8f56 docs   全仓代码体检报告（58 真问题清单）
2ce65b9 fix    根治 apaas 菜单反复 401（is_apaas_token_error 认 httpx 401 + 端点套 relogin）
80c7693 feat   配置助手改嵌入式右栏（对齐设计 tab 布局）
a0408b9 perf   app-config 加载提速（steps/status 不阻塞，占位 8.5s→0.4s）
```

### 性能（用户最初诉求「app-config 加载慢」）
- **真凶**：`onMounted` 里 `await loadDeployStatus()` → `GET /applications/{id}/steps/status` 后端按 apaas 远程重建进度耗 **8s**，排在 `restoreActiveViewForApp`（翻 platform 消占位）**前面** → 数据 270ms 就齐了却白等 8s。修：restoreActiveViewForApp 提前 + loadDeployStatus 改 `void` 后台跑。**preview 实测占位 8.5s→0.4s**。
- 顺带：退休 `primeAppPollingBaseline` 重复 948kB GET（改 `seedAppPollingBaseline` 复用已取 app）；加载期不调 `refreshCurrentAppRemoteMeta`（include_remote=true 全量远程 ~3s）；新增 `GET /applications?include_config=false`（省每行 config_preview，1.5MB→7KB）。

### apaas 401 反复发生 → 根治
- **根因**：`is_apaas_token_error` 的 `APAAS_TOKEN_MARKERS` 只认中文标记，**漏认 httpx 抛的 `Client error '401'`**（纯英文）→ 自愈核心 `call_apaas_with_relogin` 对 401 不重登。各调用点历史上各自手拼 `or "401" in msg`，唯独真相源漏了。
- 修：`error_messages.py` markers 加 `"401"`/`"Unauthorized"` 收口 + 菜单端点套 `call_apaas_with_relogin`（`2ce65b9`）；再补 6 处裸调自愈（`3f3fb82`）：`agents/coding/tools.py:_make_platform_executor`（一处覆盖 11 个 Agent 工具）+ mcp_server 5 处（list_processes/process_detail/deploy_process/_with_client/upload_zip）。
- ⚠️ `_relogin_apaas_env(platform_env_id, db)` 签名传 **db 不是 SessionLocal**（我臆测错过一次，务必先读 `apaas_tools.py:81`）。MCP 路径 `_call_apaas_platform_tool:1138` 早有 `_looks_like_apaas_401` 自愈，别重复加。

### 全仓体检（73 agent 扫 20 万行）
- 报告：[docs/audit-2026-05-29-codebase-health.md](audit-2026-05-29-codebase-health.md)，**58 真问题**（P0×1/P1×26/P2×28/P3×3，剔 10 误报）。
- 已修：401 自愈 6 处、后端可靠性批、死代码 19 脚本、SSRF。

### 后端可靠性批（`feefb48`，7 agent 分片 + 我逐个 review）
- orchestrator 失败 `yield done`→`error`（不再伪装成功）；generation_steps `except:pass`→warning + `'ok'`→`'completed'`；pipeline LLM/场景失败加日志；step_executor dict 绑定失败汇总日志；incremental 固定 1s→指数退避+jitter；auth delete_tenant FK 恢复加 error 日志 + invite_tenant_user 并发 IntegrityError 幂等重查。

### SSRF（`f9be44b`，P0）
- `/api/auth/exchange-apaas-token` **无鉴权**（SSO 换 token 设计须允许未登录）+ 用户传任意 `apaas_base_url` 发请求 = 未授权 SSRF。
- 修：新增 `_is_allowed_apaas_base_url`（origin 白名单，防 host 子串绕过）+ 端点校验。
- ⚠️ **真相**：该端点依赖的 `app.services.apaas_token_validator` **模块不存在** → 当前一调即 500（死端点），前端从不调，SSO 换 token 是未落地半成品。白名单是潜伏 SSRF 前置加固。
- **未动**（留专项）：`verify=False`（全仓 80 处/11 文件全局约定，疑 apaas 自签证书，要确认证书→配 CA→统一改，单点改会断连）。

### UI 清理（用户逐个反馈）
- **顶栏面包屑窄屏 bug**（`5583ec4`）：长应用名把 nowrap 容器压成竖排、142px 撑乱顶栏跟按钮重叠。纯 CSS：crumbs `flex-wrap:nowrap`+应用名 ellipsis 截断。preview 实测 142px→20px。
- **删顶栏「保存」按钮**（`f4a1618`）：纯 P2 占位（onTopCtaSave 只弹提示）。其它 CTA（开发/生产/发布/历史/更多/→自开发）都真功能。
- **暂隐藏「设计」(spec) tab**（`74fdd10`，可逆）：用户嫌 SPEC 文档平铺冗余，进应用直接走「功能」+对话。⚠️**命名陷阱**：视觉「设计」=`topTab 'spec'`（SpecDesignPanel）；「功能」=`'design'`（直改 apaas）。隐藏法=`AppConfigTopTabs` 的 `hideSpec` prop（默认 true）+ ChatPage `SPEC_TAB_ENABLED=false`+`normalizeTopTab()`（spec→design）覆盖 4 入口。**恢复=两处开关设 true，SpecDesignPanel 本体没删（low-code 核心线铁律不动）**。
- **删 designer 区死按钮**（`9fc668d`）：「页面设置」sub-tab（纯占位）+ 表单 header「保存」（永久 disabled）。保留预览体「提交申请」（合理预览模拟）。

---

## 二、还没做的（体检剩余 + 用户提过的）

### 前端假功能（涉产品决策，逐个要用户拍板，别盲目接）
体检 P1，用户能点但点了只 alert/disabled：
- `ListDesignerPanel` 行内 [查看]/[编辑] → alert
- `DataModelDetailPanel` [新增字段]/[编辑字段]/[编辑模型名] → disabled/alert
- `DictEditorPanel` [+添加选项]/[编辑] → alert
- `ProcessDesignerPanel` [创建/编辑流程] → alert（且体检标 mock 4 节点 demo）
- `RoleManagePanel` 权限矩阵显**推断值假数据**，只 form 权限能存（model/process/app_setting 改了 P5 不存）
- `DataSchemaEditor` [AI推荐索引]/[同步表结构] disabled（P4）；新增/编辑数据 alert
- `SpecDesignPanel` [历史] disabled（P2）—— 注：spec tab 现已隐藏

### 高风险可靠性（agent 给了建议未改）
- `sse.py` 无 per-message 超时（上游 hang 时心跳还在但无数据=假活）—— 加超时高风险断流，需专项
- `generation_steps` app.status 与 step 状态非原子（commit 失败 UI 不一致）—— 需改事务边界

### 两排融合（用户提过，选了暂不做）
- designer 区 `mdsh-subnav`（ChatPage）+ `fbp-canvas-head`（FormDesignerPanel）信息割裂重复，可融成一行省高度。跨两组件布局重构。

### SSRF 收尾
- `apaas_token_validator` 模块缺失：决定补（恢复 SSO 换 token）还是删端点
- `verify=False` 全局专项（80 处）

---

## 三、⚠️ 测试/类型基线债（**本 session 前就存在，非我引入，多次 stash 对比确认**）
不影响运行（页面 preview 全正常），但 CI 红：
- **后端 pytest 11 个预存失败**：`test_tool_registry`（yaml 跟 mcp_server 漂移，`01caa5c` vibe 删除尾巴）/ `test_step_executor_model_merge`（mock `query_models` 缺 `with_fields` 参数，过时）/ `test_auth_switch_tenant`+`test_platform_admin_tenant_context`（JWT audience 校验配置）/ `test_spec_section_o1`（`SpecSection` 没在 `models/__init__` re-export）
- **前端 vue-tsc：ChatPage 166 个 TS 错**（全仓预存类型债）。我的改动全部 stash 对比确认**零新增**。
- 这是个独立的「还技术债」任务，跟改生产代码不冲突。

---

## 四、环境/验证须知
- **本地全栈跑着**：前端 5173 / 后端 8000（preview 管理，backend `run.py` 是 `reload=False`，**改后端必须重启才生效**）/ admin-spa 5174 / code-server 8080。
- **preview 登录态**：admin / 产品租户（df-apaas，env 49）。app_id=22 = inn-idm「集成数据管理系统」（132 模型，apaas_app_id=847803124843282432，已部署），是验证标杆。
- 后端测试：`cd backend && ./venv/bin/python -m pytest tests/xxx -q`（venv python 是 3.13；系统 python3 是 3.9 跑不了）。全量跑加 `--ignore=tests/test_spec_section_o1.py`（那个 collection error 会中断）。
- **⚠️ 本机工具间歇性返损坏输出**（Read/Bash/截图随机返空/重复/虚构假代码/NOT FOUND 实则存在）——本 session 因虚构 CSS 误改一次、臆测 `_relogin` 签名差点提交错（及时撤回）。**精密手术前先验工具可靠性，关键改动先读真代码核签名**。

## 五、记忆已存（`~/.claude/.../memory/`）
- `codebase_audit_2026_05_29.md` — 体检 58 问题 + 各批进度（最全）
- `apaas_401_root_cause_2026_05_29.md` — 401 根因 + 防复发
- `app_config_perf_2026_05_29.md` — 加载慢修复
- `user_profile.md` — 称呼「大明哥」+ 中文优先

🤖 Generated with [Claude Code](https://claude.com/claude-code)
