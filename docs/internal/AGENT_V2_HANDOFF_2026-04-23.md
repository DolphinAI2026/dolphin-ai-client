# 智能开发 Agent V2 —— 会话交接文档（2026-04-23）

本文承接 `AGENT_V2_HANDOFF_2026-04-20.md`，记录 2026-04-23 这一轮的改动与遗留。**新会话必须先读 2026-04-20 那份**，因为架构背景在那里。

## 1. 工作目录

```
/Users/mars/Desktop/apaas-build/apaas-builder-ai/.claude/worktrees/competent-chatterjee-6d4c33
```

- 分支：`claude/competent-chatterjee-6d4c33`
- 未合 main。**只可以改这个 worktree 下的代码**；`DEPLOY.md` 的改动在 main 仓（用户显式授权）。
- 后端跑在主仓 `/Users/mars/Desktop/apaas-build/apaas-builder-ai/backend` 的 venv 下（`--reload`，端口 8000）；前端 vite 在 5173。DB 走 `.env` 里 `39.99.176.43:30018/apaas_builder`。

## 2. 本次解决的根本问题

**现象**：用户反馈"一直在验收中"，前端永远卡在 🧪 验收中… 转圈。

**根因**（直接从 DB 查出来的，不是猜）：
- `conversation_events` / `agent_traces` 表显示 verify 跑完 AC #2 后 LLM 返回了第 4 次 check_ac 的 tool_call（`seq=31 llm_response`），但 `_handle_tool_calls` 还没执行就**进程消失了**。
- 时间点跟上一会话修 Bug #8（`pool_pre_ping`）吻合——uvicorn `--reload` 把进程重启了，`asyncio.create_task(_run_coding_task(...))` 的后台任务被 SIGKILL 掉。
- **整个系统没有 task 恢复机制**：agent 被杀后没有任何 `verification.failed / coding.failed / orchestrator.aborted` SSE 发出，前端永远收不到终态事件。
- 这不是偶发，是结构性：reload / 崩溃 / 部署重启 / 滚动升级都会触发。

## 3. 本次改动（分 5 块）

### 3.1 后端启动扫描兜底（方案 2）

- 新增 `backend/app/startup_recovery.py`：`sweep_dead_coding_sessions()` 在 `main.py` 的 lifespan startup 阶段跑一次
- 找 `coding_sessions.status='running'` 且 conversation 最近 event 超过 10 min 没动静的行
- 原子 UPDATE `status='running' → 'aborted'`（`WHERE status='running'` 保多 worker 并发安全；生产 `--workers 2` 即 2 个 worker 各跑一次扫描，同一行只被一个 worker 抢到）
- 抢到的行补发 `coding.failed` SSE（reason=`process_restart`）→ 前端 store 翻 `phase='failed'`
- threshold=10 min 是因为 LLM 长推理可能静默 20+ 秒，coding→verify 之间曾见 2 min 间隔，留足余量

### 3.2 多进程 / 多 Pod 部署注意事项（main 分支 DEPLOY.md）

`/Users/mars/Desktop/apaas-build/apaas-builder-ai/DEPLOY.md` 的"容器化部署注意事项"章节加第 5 条"多进程 / 多 Pod 部署的陷阱（重要）"：
- 当前兜底：startup sweep + threshold 保障单机多 worker
- 上 K8s 前必须补的 gap：持久化 job queue（Celery/RQ）、SSE sticky session、task heartbeat 表、preStop hook
- 不先解决上面几条，上 K8s 就是每次 Pod 重启都死一批任务

### 3.3 前端：`重新生成`闭环（用户解锁）

- `frontend/src/stores/codingV2.ts`：
  - `coding.failed` 事件的 error 消息带 `errorReason` + `canRetry`（reason=`process_restart` 且 `currentSpecId` 存在时 true）
  - 新增 `prepareRetry()` action：清掉 error 卡 + 所有 verify-active / coding-active + 运行时日志缓存 + `sseLastError`
  - `coding.start` 到来时自动清 stale error / banner
  - `verification.start` 把上一轮仍停在"🧪 验收中…"的 divider 标签改为"⚠️ 验收已中断"
- `frontend/src/components/coding-v2/ChatFlow.vue`：error 卡在 `canRetry=true` 时多一个红底"🔄 重新生成"按钮；透传 `retrying` prop
- `frontend/src/views/coding-v2/CodingPageV2.vue`：`onRetryCoding()` → `prepareRetry` → `startCodingFromSpec(currentSpecId)`；带 `retrying` ref 防重复点击

### 3.4 前端：VerificationProgress 大幅样式重做

原来一张大 `.vp-panel` panel 塞了所有行，用户觉得丑。改成和 CodingProgress 一样的"分块卡"：
- 外层 `.verification-progress` flex 竖排 gap 6px
- 每个工具调用（代码搜索 / 读取文件 / 核验 AC）独立 `.card.tool-card`
- 每条 AC 结果（AC #0 通过 95%）独立 `.card.ac-card`，按 passed/failed/needs_review 染边框色
- `isAborted`（`phase==='failed'` 且没出报告）状态：头部红边 + "验收未完成"标题，不再转圈

**过滤规则**（用户反复迭代后的最终版）：
- `check_ac` / `emit_report` 工具行**永远隐藏**（信息已在 ac_result 卡 / 顶部 AI 总结里，重复）
- `ac_result` 进度卡**只在运行中保留**；终局后隐藏（和底部最终 AC 列表重复）
- 代码搜索 / 读取文件 等**真实步骤永远保留**（审计轨迹）

**终局布局**（**上面是步骤、下面是总结**，用户明确要求的顺序）：
1. 代码搜索 / 读取文件 的历史步骤卡
2. 一张大总结卡（头部"✓ 验收通过 4/4 + 查看 AI 总结"+ AC 详情列表合在同一张卡里，中间薄分割线）
3. 底部"所有验收点通过"绿条

### 3.5 前端：autofix 多轮每轮独立卡（重要结构改动）

用户质疑："verify 失败后 retry 的 coding 步骤如果跳回到最上面的 `coding-active` 里，这种体验很糟。"

**背景**：后端 `drive_coding_with_autofix` 允许 coding→verify→failed→coding 重跑 ≤ 2 次。每轮都 emit `coding.*` / `verification.*` 事件。原来 `codingLog`/`verifyLog` 是单一 ref 数组，autofix 第 2 轮的 coding 事件 append 到同一数组 → 跑到页面顶部的那张 coding-active 里，时间线错乱。

**解法：快照冻结**
- `ChatMessage` 接口加 `frozenCodingLog` / `frozenVerifyLog` / `frozenVerifyReport` 字段
- `coding.start` handler：上一张"活着"的 coding-active 把当前 `codingLog.value` 快照进 `frozenCodingLog`，清空 live log，推一张新 coding-active；轮次 ≥ 2 时 divider 标"🔁 自动修复 · 第 N 轮"
- `verification.start` handler 同理
- `CodingProgress` / `VerificationProgress` 加 `frozenLog` / `frozenReport` props。有 prop → 只读快照模式，不转圈、不显示等待态
- `ChatFlow` 渲染时 `:frozen-log="msg.frozenCodingLog"` 等透传

**效果**：时间线保持 `coding(r1) → verify(r1失败) → coding(r2) → verify(r2通过)` 顺序，每一轮的工具步骤各自在自己那张卡里，回看历史清清楚楚。

### 3.6 后端：tool_call 事件带 args 预览

`backend/app/agents/base.py` 的 `_handle_tool_calls` 原来只发 `{tool: name}`，前端 VerificationProgress 里只能显示"代码搜索"裸工具名，看不出搜了啥。

新增 `_short_args_preview()` helper：
- 常用字段优先挑（`query` / `path` / `file_path` / `glob` / `pattern` / `url` / `command`）
- check_ac 的 `ac_index` 不在优先列里（下一条 ac_result 已经展示 "AC #N"，重复）
- 兜底：压成一行 JSON，跳掉大字段（`content` / `evidence` / `new_string` / `old_string`）
- `_publish("tool_call", ...)` 带上 `input_preview`

CodingAgent 自己的 `agent_tool` 事件有自己的富预览，不受影响。

## 4. 未提交的文件清单

**Worktree（`claude/competent-chatterjee-6d4c33`）**：
```
# 新文件
backend/app/startup_recovery.py
frontend/src/components/coding-v2/CodeBlock.vue       （上一会话遗留）
frontend/src/components/coding-v2/VerificationProgress.vue  （整重写）
frontend/src/components/coding-v2/icons/             （上一会话遗留）
docs/internal/CODING_V2_FILE_UPLOAD_EXTENSION_2026-04-22.md  （上一会话遗留）
docs/internal/AGENT_V2_HANDOFF_2026-04-23.md         （本文）

# 改动
backend/app/agents/base.py            # _short_args_preview + tool_call 带 input_preview
backend/app/main.py                   # 接入 sweep_dead_coding_sessions
backend/app/routes/coding_v2.py       # 上一会话的 llmcfg: 前缀修复 + conversation.user_message 事件
frontend/src/stores/codingV2.ts       # retry 闭环 + 多轮快照 + stale state 清理
frontend/src/components/coding-v2/ChatFlow.vue       # retry 按钮 + frozen props 透传
frontend/src/components/coding-v2/CodingProgress.vue # frozenLog prop
frontend/src/components/coding-v2/InputBar.vue       # 上一会话遗留
frontend/src/components/coding-v2/SpecPreview.vue    # 上一会话遗留
frontend/src/views/coding-v2/CodingPageV2.vue        # onRetryCoding + retrying ref
... (还有其它上一会话遗留的未提交改动)
```

**Main 仓（`main` 分支）**：
```
DEPLOY.md     # 新增第 5 条"多进程 / 多 Pod 部署的陷阱"
```

**都没 commit**。用户偏好 commit message **只允许中文**。

## 5. 本次验证过的数据

- DB 里两个悬挂行 `c_975d75cc4d50`（conv 384）+ `c_986a52a7b5fd`（conv 374）已被 sweep 标 `aborted`，补发了 `coding.failed` 事件（seq=1048 / 4195）。
- `sweep_dead_coding_sessions()` 跑第二次返回 0，幂等。
- 前端刷新后 phase 翻 failed，展示"🔄 重新生成"按钮，点击后走新一轮 coding → verify（autofix 多轮 UI 也验证过，用户确认"上面步骤下面总结"的顺序满意）。

## 6. 已知遗留 / 未实现

### 6.1 仍未解决：agent 无法 resume

- sweep 只是"把死任务标成 aborted"，**不恢复任务**。用户必须点"重新生成"重跑。
- coding 的 `BaseAgent` 已有 `to_snapshot / from_snapshot`，但 `_run_coding_task` 里没在中途写 snapshot，崩了就是彻底丢。
- VerificationAgent 更糟糕，**没有 suspend / snapshot 机制**。
- 上 K8s 之前必须补：持久化 job queue（Celery / RQ / 自建）+ heartbeat 表 + agent snapshot 写点。

### 6.2 上一份 handoff 还没做完的事

- **SCAFFOLD phase 实际执行**：上一份 § 7.5 的大头。需要新增 `backend/app/orchestrator/scaffold.py`，根据 `scene_type` → `project_type` → 调 `WorkspaceManager.create_workspace()`，写 `scaffold.started/done/failed` 事件。目前只在 `coding_v2.py` 的 confirm 分支里把 phase 推到 SCAFFOLD，没 worker 在做事，前端转圈。workaround 是先在有 workspace 的会话上测，但首轮新建会话会卡。
- **VERIFY phase 自动触发** 已经接入了（`_run_coding_task` 里走 `drive_coding_with_autofix`）。这是上一份文档里列的未完成项，实际已经做了。
- **LLM 无 tool_call → `LLM_NO_TOOL_CALL → break → COMPLETED` 但 state.emitted=False**：这条路径应该发 `brainstorm.failed` / `brainstorm.stuck` 通知前端，目前还没做（上一份 § 10 优先级 4 第 1 条）。

### 6.3 AutoFix 多轮的一个小瑕疵

后端 `drive_coding_with_autofix` 在 `on_verify_retry`（VERIFY → GENERATE 转移）时**没发 `orchestrator.phase_changed: generate` SSE**。前端现在靠 `coding.start` 事件来识别新一轮，够用，但从后端语义上讲应该配齐。看心情决定补不补。

### 6.4 前端：`visibleVerifyLog` 过滤 `ac_result` 的时机

终局后 ac_result 卡隐藏掉。但如果 verify 只 emit 到一半就被用户用"重新生成"清掉，中间态的 ac_result 卡不会出问题（因为 `prepareRetry` 整张 verify-active 都清了）。当前逻辑没见漏洞。

## 7. 文件导航速查

```
后端
  backend/app/startup_recovery.py              新：进程启动清理悬挂 session
  backend/app/main.py                          接入点 (lifespan)
  backend/app/agents/base.py                   _short_args_preview + tool_call 事件
  backend/app/orchestrator/driver.py           drive_coding_with_autofix 主循环（没动）
  backend/app/routes/coding_v2.py              _run_coding_task 背景任务

前端
  frontend/src/stores/codingV2.ts              事件分派 + chatMessages 状态
    - coding.start handler       多轮快照逻辑
    - verification.start handler 多轮快照 + divider 改写
    - coding.failed handler      canRetry 标记
    - prepareRetry action        "重新生成"入口调用
  frontend/src/components/coding-v2/
    ChatFlow.vue                消息流渲染，透传 frozen props
    CodingProgress.vue          frozenLog prop + 活跃/冻结双模式
    VerificationProgress.vue    大重写：上面步骤下面总结卡
  frontend/src/views/coding-v2/CodingPageV2.vue  onRetryCoding

文档
  docs/internal/AGENT_V2_HANDOFF_2026-04-20.md  前一份 handoff（架构在这）
  docs/internal/INTELLIGENT_DEV_AGENT_ARCHITECTURE_V1_2026-04-19.md  架构总纲
  DEPLOY.md （main 仓）                          多 Pod 注意事项章节
```

## 8. 用户风格要点（保留上一份）

- **直接、严格、不给面子**。说"你这种展示都不考虑的吗"、"你读书是从后往前读的啊"这种句子时是真的在指出 UX 缺陷，不是开玩笑。
- **希望看根因不看补丁**。这次我顶住"先让我查 DB"再动代码，用户满意；上一份 § 7 那种"打补丁"做法仍是禁区。
- **中文沟通**。Commit message 必须中文。
- **希望系统级架构**不是玩具。sweep 只是兜底，用户清楚知道终局要上 job queue。

## 9. 下一会话建议顺序

**优先级 1**：让用户确认这一轮 UI 改动（多轮独立卡 + 上面步骤下面总结）在多轮 autofix 真实场景里是不是他要的。真实跑一次 verify 会失败的例子（比如故意改坏代码）看 autofix 第 2 轮有没有按预期在新卡里渲染。

**优先级 2**：把本次所有未 commit 的改动 commit 掉，**commit message 用中文**。分两次 commit 比较清晰：
1. "后端启动恢复 + 多 pod 部署注意事项 + tool_call 参数预览"
2. "前端 verify UI 重做 + autofix 多轮独立卡 + 进程重启重试闭环"

**优先级 3**：按上一份 § 10 + 本文 § 6 补 SCAFFOLD phase 的实际执行。这是"新建会话首轮永远卡死"的堵点。

**优先级 4**：开始做 agent snapshot 持久化（为上 K8s 做准备），或者接 Celery/RQ。

---

**最后提醒接手会话**：用户之前就被"268 个单测绿但核心链路不可用"的历史刺痛过。**不要相信单测，真实链路跑一次**。查 DB、看事件流、看用户实际界面，再下判断。
