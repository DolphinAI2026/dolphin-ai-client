# Handoff · 2026-05-24 session — 5 P0 + token 全链路省 + silent-fail bug 实测捞出

> 上接 [handoff-2026-05-22-session-end.md](handoff-2026-05-22-session-end.md)。
> HEAD `1602daa` (push origin `local/ui-redesign-2026-05-20` 待用户确认)。
> 本 session 8 commits / 3 files / +250 / -97 (主线 backend prompt/schema + 2 frontend UI).

## TL;DR

下次 session 接手 4 句话：

1. **5 P0 + 1 P1 + 1 P0 bug 全落地** — `7a6758d` ~ `1602daa` 8 commits. 含 RailSidebar `<a href>` / tab path 还原 / deploy token 自愈 / artifact_id 强制 schema 链路 (validate+submit+generate) / Phase 1 删 submit_design_doc 治 final summary / 二开 silent-fail bug 修.
2. **chrome-devtools 浏览器实测全 P0** — 创建应用 `app_id=13` (图书借阅管理系统, apaas_app_id=`846351551214649344`), Phase 1 + 2 一气呵成跑通, **0 个 submit_design_doc 调用**, Phase 2 末 final summary 完整出现.
3. **二开实测意外捞出真 P0 bug** — `create_apaas_app_roles` / `create_apaas_app_dict` 漏 `appId` 字段, apaas 平台返 200 ok 但 silent 不创建 → agent false-positive 报成功. 修法对齐 `step_executor.py:236` 正确范例.
4. **token 浪费 100% 收尾** — Phase 1+2 全程 md 生成 1 次 (write_artifact 唯一), validate/submit/generate 强制 artifact_id 引用. agent 没选择空间, pydantic schema 拒老 md_content 调用.

---

## 关键架构 + 决策

### Token 浪费修法链路 (3 commits)

之前痛点: agent 创建应用走 write_artifact (5000 字 md) → validate_builder_doc (再 5000 字) → submit_design_doc (再 5000 字) → generate_app_from_doc (再 5000 字). 4 次 LLM 输出 = ~20000 token + 90-180s.

| Commit | 修法 | 工具 | schema 状态 |
|---|---|---|---|
| `6ba63aa` | 强制 schema 删 md_content | validate_builder_doc | `(artifact_id: int)` required |
| `6ba63aa` | 强制 schema 删 md_content | submit_design_doc | `(artifact_id: int, file_name, ...)` artifact_id required |
| `2c6afdc` | 强制 schema 删 md_content | generate_app_from_doc | `(artifact_id: int, app_name, env_id, ...)` artifact_id required |
| `10e4b16` | Phase 1 prompt 删 submit_design_doc 调用 | (agent.py) | ai-chat agent 不再调 submit |

实测 (chrome-devtools): session 26 DB trace 只 1 个 `write_artifact` tool call. agent 跳过 validate_builder_doc (因为 write_artifact 内部 silent validate 已含 score) 直接 STOP. Phase 2 也只调 generate_app_from_doc (artifact_id=N) 不重传 md.

**Token 真实节省**: Phase 1+2 一次创建应用从 ~20000 → ~5000 token (write_artifact 那一次), 时间从 ~3-5 分钟 → ~1.5 分钟.

### Token 自愈 C 方案 A+B (`5ca0f86`)

P0 #4 修法 deploy_application 撞 apaas token 过期 hard fail 问题:

- **A (backend/.../generate.py)**: env.token 为空时自动 `APaaSClient.login()` 拿 token 写回 db. 不再 hard fail "去 admin 重连".
- **B (mcp_server.py)**: 移植 `b33d18e` 的 `_api_call` / `_api_call_sse_collect` token retry 参数 + retry logic. 用同进程 `_refresh_apaas_env_token` (commit 6cb7ce0 同模式) 替换 internal HTTP refresh.
- `deploy_application` 调用时传 `token_retry_app_id=app_id`, SSE 撞 apaas token 过期 → 整段 stream 重跑.

实测 deploy 25.0s + publish 18.7s 跑通, token 没过期所以自愈 path 没触发 — 但代码路径走过证明 wrapper 不破坏正常流.

### 二开 silent-fail bug 捞出 (`ea001bc` + `1602daa`)

二次开发实测点 quick action "加一个角色叫'运维管理员'" → config-chat agent 跑 5 轮内调 `create_apaas_app_roles(ops_admin, 运维管理员)` 报 ok=true → list 显示 total=2 没新增. agent 给方案分析卡片说 "已创建但平台还没刷新可能要保存应用".

**Root cause**: `mcp_server.create_apaas_app_roles` 拼 payload 时**每项 role 漏 appId 字段**. apaas 平台:
- 收到 payload schema 合法 → 返 200 ok (无 error)
- 但没 appId → 不知道挂哪个应用 → silent ignore / 可能写到全局表
- 工具看 ok=true 误判成功 (false-positive)

**对比 step_executor.py:236-240** (generator_v2 真成功路径, 含 appId):
```python
await client.create_roles(app_id, [{
    "appId": app_id,        # ← 必填!
    "roleCode": platform_code,
    "roleName": r["name"],
}])
```

**修后验证** (直调 MCP):
1. 修前: ok=true, list total=2 (false positive)
2. 修后同名 "运维管理员" → 平台返 "角色名称重复" (证明之前漏 appId 真写到别处了)
3. 修后换名 "运维专员A" → list total=3 真显示 ✓

**同模式预防修** `create_apaas_app_dict` 也漏 appId (1602daa).

**Audit 结论**: mcp_server 二开工具里只有 `create_apaas_app_roles` + `create_apaas_app_dict` 是 "自拼 payload 直传" 模式漏 appId. 其它 `client.method(app_id, ...)` 调用 client 内部正确含 appId.

---

## 本 session 完整 commit 列表 (8)

按时间顺序:

| # | Commit | 主题 |
|---|---|---|
| 1 | `7a6758d` | feat(frontend): RailSidebar nav 改 `<a href>` — Cmd+click 真开新 chrome tab |
| 2 | `2dbf68b` | feat(tabs): Phase 4 #1 — 刷新 tab 还原到最后浏览位置 |
| 3 | `5ca0f86` | fix(deploy): 移植 token 自愈到 deploy_application 链路 (C 方案 A+B) |
| 4 | `6ba63aa` | feat(ai-chat): token 浪费修法 1 — 强制 artifact_id schema 删 md_content |
| 5 | `10e4b16` | fix(ai-chat): P0 #3 — Phase 1 删 submit_design_doc 调用治 final summary |
| 6 | `2c6afdc` | feat(ai-chat): P1 generate_app_from_doc 加 artifact_id 强制 schema |
| 7 | `ea001bc` | **fix(mcp): create_apaas_app_roles 漏 appId — silent fail (二开实测)** |
| 8 | `1602daa` | fix(mcp): create_apaas_app_dict 同样漏 appId — 跟 roles 一起修 |

---

## 实测产物

| 路径 | 产物 | 备注 |
|---|---|---|
| AIChatPage `/ai-chat/26` | session 26 完整 trace (Phase 1+2 一气呵成) | DB 验通: 0 个 submit, Phase 1+2 末都有 final summary |
| Apps `/apps` → ChatPage `/chat?app_id=13` | **app_id=13 图书借阅管理系统** `library-borrow` | 已部署上线, apaas_app_id=`846351551214649344`, 版本 1.0.0 |
| apaas 平台 | 角色 `ops_admin_a` 运维专员A | 二开 fix 后实测验证产物, 用户决策**应用不要删** |

---

## 留尾任务 (下次 session)

### P0
(本 session 全清完 — 没有当前 P0 留尾)

### P1
- **update_app_from_doc 也加 artifact_id 强制 schema**: 当前还接收 `md_content`, agent 改应用配置时仍重传 5000 字. 跟 generate_app_from_doc 一致修法 (artifact_id required). 30-40min.
- **config-chat agent prompt 优化**: 当前 list_apaas_app_roles 反复调多次没 final summary (text), 只输出 JSON action card. 加"verify 失败时给中文 summary" 规则. 30min.
- **call_logs 持久化机制 review**: 当前 `_call_log_buffer` 只在 generation_steps.py 内 flush, 其它路径 (config-chat / 直调 MCP) 不 flush → 二开/调试 trace 不可查. 加全局定时 flush 或每次调用都 flush. 1-2h.

### P2
- **"AI 给的方案分析 — 仅展示 不调真工具" 文案残留**: `0158780` 删 ChangePlan stub 按钮时漏改文案. frontend 改 1 行. 10min.
- **同 silent-fail 风险审计扩展**: 看 mcp-server-v2 repo 是否同样有 create_apaas_app_roles/dict 漏 appId bug. (本 repo 已修, prod dolphin 走 v2 不受影响, 但 v2 同样可能 bug.) 30min.
- **53 处 .vue 硬编码 hex 改 token**: 跟前 session 留尾, dark mode 已兜底 CSS 覆盖, 但源头改更彻底. 2-3h.

### P3
- 老目录清理 (`dist/` 4/12 老 vite 产物 / `output/` 临时 / `marketplace_store/` 空 / `docker/` 几乎空 / `examples/` 历史样例). 15-30min.

---

## 关键文件

### Backend
- [backend/app/mcp_server.py:130-260](../backend/app/mcp_server.py) — `_api_call` / `_api_call_sse_collect` token retry wrapper (`5ca0f86`)
- [backend/app/mcp_server.py:406-468](../backend/app/mcp_server.py) — `generate_app_from_doc(artifact_id: int)` 强制 schema (`2c6afdc`)
- [backend/app/mcp_server.py:819-862](../backend/app/mcp_server.py) — `validate_builder_doc(artifact_id: int)` 强制 schema (`6ba63aa`)
- [backend/app/mcp_server.py:901-945](../backend/app/mcp_server.py) — `submit_design_doc(artifact_id: int, ...)` 强制 schema (`6ba63aa`)
- [backend/app/mcp_server.py:2748-2810](../backend/app/mcp_server.py) — `create_apaas_app_roles` payload 加 appId (`ea001bc`)
- [backend/app/mcp_server.py:2875-2900](../backend/app/mcp_server.py) — `create_apaas_app_dict` payload 加 appId (`1602daa`)
- [backend/app/routes/applications/generate.py:81-115](../backend/app/routes/applications/generate.py) — env.token 空时自动 login (`5ca0f86` A 部分)
- [backend/app/ai_chat/agent.py:125-167](../backend/app/ai_chat/agent.py) — Phase 1 删 submit + Token 节省铁律段 (`10e4b16` + `2c6afdc`)
- [backend/app/ai_chat/tools.py:1241-1244](../backend/app/ai_chat/tools.py) — `_persist_spec_artifact` intercept 去掉 generate_app_from_doc (`2c6afdc`)

### Frontend
- [frontend/src/components/v2/RailSidebar.vue](../frontend/src/components/v2/RailSidebar.vue) — nav `<button>` → `<a href>` + resolveHref + onMenuClick (`7a6758d`)
- [frontend/src/stores/tabs.ts](../frontend/src/stores/tabs.ts) — syncFromRoute 加强 (子路径 prefix match + app_id 隔离 + 命中更新 tab.path) (`2dbf68b`)

### Docs
- [docs/handoff-2026-05-22-session-end.md](handoff-2026-05-22-session-end.md) — 上次 session handoff
- [docs/handoff-2026-05-24-session-end.md](handoff-2026-05-24-session-end.md) — **本文档**

---

## ⚠️ 提示下次接手

1. **app_id=13 图书借阅管理系统不要删** — 用户明确决策保留, apaas_app_id=`846351551214649344` 上线版本 1.0.0. 含本 session 实测加的 `ops_admin_a 运维专员A` 角色 (二开 fix 后验证产物).
2. **token 浪费链路 100% 收** — validate / submit / generate 三个工具全强制 artifact_id. `update_app_from_doc` 是下次 P1 (一致性补完).
3. **silent fail bug 类型**: apaas 平台批量创建接口对漏 appId 不报错, 自查模式是 grep `mcp_server.py` 里 `lambda c: c.create_xxx(app_id, payload)` 形式 + 看 payload 是否每项含 appId. step_executor.py 是真成功范例.
4. **chrome-devtools mcp 实测全 P0 + 二开** — 浏览器端到端跑通的好处是能在 agent 报告 ok=true 时直查平台真实状态, 抓 false-positive. 下次实测建议保持此习惯.
5. **mcp-server-v2 repo 待 audit** — 本 repo 修了 silent fail bug, v2 (prod dolphin 走的 k8s 服务) 可能同样有. 下次 session 看一下.
6. **session 26 + app 13 trace 完整** — DB 里有完整 messages + tool_calls 历史可查, 复现 / debug 都方便.

详 commits: `git log 62f7f57..HEAD --oneline` 看本 session 8 commits 全貌.
