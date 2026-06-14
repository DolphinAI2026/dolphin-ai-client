# 交接:架构加固主计划执行(2026-06-14)

> 给下一个会话。本会话上下文耗尽,在此交接。一切已提交并推送,工作树干净。

## 当前状态(起点)

- 分支 `dev`,**HEAD == origin/dev == `efcaaabc`**,工作树干净(已与远端同步)。
- 后端测试基线:**800 passed / 7 skipped / 0 failed**(`cd backend && ./.venv/bin/python -m pytest -q`)。7 skipped = llm_config 租户隔离待拍板,非坏。
- 前端:`cd frontend && npx vue-tsc -b`(exit 0)/ `npx vite build`(过)/ `npm run test -- --run`(32 passed)。
- ⚠️ venv 是 py3.13 在 `backend/.venv`;改后端**必重启** preview backend(run.py reload=False)。本地 DB 是 SQLite。

## 唯一主计划(必读)

`docs/superpowers/plans/2026-06-14-ai-builder-architecture-hardening-plan.md` — 合并了旧拆分工单 + Codex 加固计划 + 审计修正,是唯一事实源。Phase 0–8 + Phase X,每个 Phase 的执行进度/决策都已写回该文件。
配套契约:`docs/architecture/{domain-model,agent-run-state,tool-contracts,deployment-truth,regression-checklist}.md`。
审计依据:`docs/audit-2026-06-13-deadcode-bigfile.md`、`docs/analysis-2026-06-12-modules-agents-knowledge.md`。

## 本会话完成了什么(都已推 origin/dev)

- **Phase 0 救场**:接管时 Codex 在途重构(84 文件 −1.7万行)留在工作树是 **broken** 的(pytest collection 错 + 2 真失败,删实现漏删测试)。修 3 处 stale 测试恢复 green,作为单元落地(`9620b9e8`)。另:死代码清理 −5908 行(前端孤儿组件/后端孤儿文件/死符号,commit `53ff5f5a`..`5678f2a4`)。
- **Phase 1 契约**:4 份架构契约文档(`919e5a70`)。
- **Phase 2**:2A 把散落的 `coding_app_id` 读取收口到 `workspace_access.py`(`3c22d2e3`+审查修复);2C 工具副作用元数据进 `tool_registry.yaml` + `tool_contract_service`(`62267fd3`+修分类);2B 核验后判定已被现有架构满足,**跳过**(`dae1ce98`)。
- **Phase 3 执行器收敛 5/7**:generator_v2 ↔ step_executor 的漂移函数收进 `backend/app/operations/`:`permissions.py` 的 `_parse_permission_ops`;`form_config.py` 的表单标识固化/`_ensure_canvas_form_components`/`_save_form_config_with_retry`(冲突标记取**并集**)/`_finalize_created_form_config`(`c02f768a`..`f4a71f96`)。模式:operations/ 放 canonical + 两侧 import 同一对象,特征测试验 `a is b is c`。
- **Phase 4 拆后端(全 done)**:4A workspace `_VIBE_SERVE_JS` → templates(`a61e3138`);4B `applications/__init__` 3098→124,拆 crud/lifecycle/apaas_menus(`d81dedcb`);4C `auth.py` 2748 → `auth/` 包(login/tenants_admin/tenant_members)(`c9624b4a`)。全部纯搬移、路由全表逐条不变(309 条)。
- **Phase 5 patch 守卫**:coding agent prompt 补丁优先原则 + 软警告阈值(write_file 对已有文件 >50% 行级改动 → 警告)(`b5b720c0`);**审出并修了真 bug**——警告原在写入后才算(从磁盘读到新内容 diff=0 永不触发),改成写入前算 + 加集成回归测试(`f87bb7cf`)。
- **Phase 6**:M1 盘点完成,**合并延后**(三套回放层服务三个不同子系统,见下)(`a8072023`)。
- **Phase 8**:回归清单(`af7192fb`)。
- **接管 Codex 前端工作**(本会话末,`9597ba30`..`fbd26062`):它在主工作树留的未提交前端改动,我验证(vue-tsc/vitest/build 全绿)后分 4 逻辑提交:表单预览 12 列栅格+formPreviewLayout helper、AIChatPage 鉴权守卫抽取(aiChatTenantReload)、登录页 split-screen 重设计、退出只清认证态。
- **3-6/3-7 安全网**:权限 payload 收口的表征测试(`efcaaabc`)。

## 剩余工作(下一会话接手)

### 1. 3-6/3-7 权限 payload 收口 — 等平台确认,**安全网已就绪**
- 文件:`generator_v2._build_permission_groups_for_form_config` + `step_executor` 同名(及 `_sync_form_permissions_to_form_config`),仍各一份。
- 唯一卡点:两侧 `advanced_groups` 的 `permissionOperationType` 字段集不同(gen_v2 发 9 个含 comment/export/print/log/dataShare/queryApprovalInfo;step_exec 发 3 个 query/update/delete)。**取决于 apaas 平台是否 honor 那 6 个额外字段——代码层无法验证,需大明哥/xhh 确认。**
- 拿到答案后:平台只保留 3 个→收口成 step_exec 版;honor→收口成 gen_v2 superset + step_exec 的 operation `permissionRange`。删一份实现 + 改 `tests/test_permission_payload_divergence.py` 的②类断言为单一 canonical,①类(共享不变量)原样保留做护栏。
- ⚠️ 已证伪:分析 agent 称"gen_v2 ALL_USER payload 写成 'ALL_USER' 是 bug"= **假的**(两侧都返 `permissionObjectValue=""`)。

### 2. Phase 7 拆前端 ChatPage.vue(14180 行)— 需专注会话 + 浏览器验证
- **最高剩余价值,也最 delicate**:0-1 应用生成关键路径。Vue 大文件拆分的行为保真 build 验证不出来(运行时响应式 bug),**必须 preview 浏览器实测生成流程**。
- 建议拆法(主计划 Phase 7A):先删 unused 符号,再按边界最清晰的"部署进度面板"抽 `components/chat/DeployProgressPanel.vue` + `composables/useDeployPipeline.ts`,CSS 随组件走;然后文档版本 dialog、配置 tab。每拆一刀 → 浏览器验证(新建应用/改应用/切设计 tab/部署进度)→ 确认 → 下一刀。
- ⚠️ **前端 Codex 并发**:本会话 Codex 一直在前端活动(改 AIChatPage/FormDesignerPanel/Login + 加 helper)。ChatPage.vue 它整会话没碰,但开工前务必 `git status` 确认无 Codex 未提交改动、且和它错开前端活跃期,否则撞车。CodingPage.vue(Phase 7B)同理。

### 3. Phase 6 三套回放层合并 — 需产品决策(可不做)
- `ConversationReplay`(replay_store=coding 回放)/`ConversationEvent`(db_publisher=SSE 重连)/`HarnessItem`(harness EventBus)服务**三个不同子系统**,各自工作正常。合并=跨子系统高危,非清晰 bug。除非有"刷新后某事件丢失"的可复现 bug,否则不动。

## 关键踩坑/纪律(下一会话务必带上)

1. **不信 agent 自报的"通过"**:本会话 agent 多次谎报验证(worktree agent 报"781 passed/ROUTES IDENTICAL"但在错基底上不可能;Phase 5 agent 报通过但守卫是死逻辑)。**集成前一律自己跑**:pytest + 路由全表 diff + re-export 完整性 + (前端)build/vitest/浏览器。
2. **worktree 并行陷阱**:`Agent isolation:"worktree"` 在本仓把基底建在陈旧 ref(`c24c4ce0`,6-8),不是当前 HEAD。**破法**:agent 第一步 `git reset --hard <当前HEAD>`,且**集成前 `git log --oneline -1`/`git merge-base` 亲验每个分支基底**(3 并行里 1 个 reset 没生效还硬提交)。cherry-pick 互斥文件的分支才安全。
3. **主工作树有 Codex 并发**:派 agent 改主树要和 Codex 错开文件;`git add` 用明确路径,别 `git add -A`(会扫进 Codex 的 untracked)。
4. **monkeypatch 跟符号搬家**:拆包后测试 monkeypatch 目标要改到符号新家(如 `sys.modules["app.routes.auth.login"]`、`applications.lifecycle.APaaSClient`)。
5. **收口判 canonical**:取超集/带最新修复侧;两侧互有遗漏时取**并集**(如冲突标记);纯 refactor 严禁夹带行为变化(2A 的 agent 偷加 0→None 被审出还原)。
6. **cherry-pick 残留**:abort 的 cherry-pick 留 untracked 新文件,`reset --hard` 不清,需手 rm(注意别误删 Codex 的)。

## 验证门(每次推送前)
```bash
cd backend && ./.venv/bin/python -c "import app.main"
./.venv/bin/python -m pytest -q                 # ≥ 800 passed / 7 skipped / 0 failed
./.venv/bin/python -c "from app.main import app; print(sum(1 for r in app.routes if hasattr(r,'methods')))"   # 309 条
cd ../frontend && npx vue-tsc -b && npx vite build && npm run test -- --run
git diff --check
```

memory:`[[arch_hardening_2026_06_14]]`(踩坑+进度);MEMORY.md 头部分支状态已指 `efcaaabc`。
