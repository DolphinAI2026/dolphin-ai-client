# 切会话不丢 run（builder + code）— 设计

2026-06-22。目标:在跑的 agent run 脱离 SSE 连接生命周期——**切会话 / 刷新页面 / 断网重连**都不丢,切回会话能接回实时进度。范围 = /coding(Code)+ /ai-chat(Builder),**进程内持久**(后端重启不保,startup_recovery 已兜底标 aborted)。

## 现状(根因)

两条路线架构不同:

- **Code(/coding)** 走新 harness:`HarnessManager.start_turn`([manager.py:218](../../backend/app/harness/manager.py)) 已用 `asyncio.create_task(_run_turn_background())` 后台跑 + `EventBus`(内存订阅 list + 落 `harness_items` + `replay_events(after_seq)`)。**骨架接近**,但缺口:① EventBus 每次 `start_turn` 新建 → 重连接不回在跑那条总线;② 后台 `task` 仅被 `_event_stream` 闭包引用 → 客户端断开后 `_event_stream` 被 GC,task 失去强引用可能被取消;③ 无"重连=补历史+跟实时"端点(现在 replay 是静态、实时是内联);④ 前端切会话主动 abort(`abortInflightStream` → `stopStream` → `currentAbort.abort()`,CodingPage)。
- **Builder(/ai-chat)** 走 `run_agent`([agent.py:768](../../backend/app/ai_chat/agent.py)):run **内联在 SSE 生成器**(`async for ev in run_agent(...): yield`),客户端断 → 生成器取消 → run 当场停。事件经 `DbEventPublisher`([db_publisher.py](../../backend/app/agents/db_publisher.py),进程单例 + 按会话 seq + 落 `conversation_events`)广播+落库——`conversation_events` 表注释已写明"支持断线重连补发,保留 7 天"。

可参考的成熟范式:**serve-logs**(`_append_serve_log`/`iter_serve_logs`/serve-logs SSE 路由 + 前端 `buildServeLogsUrl(lastSeenSeq)`)= 环形缓冲 + 按 seq 补发 + 实时跟随 + 断开不影响生产。

## 架构

1. **RunRegistry(进程级运行注册表)** — `dict[conversation_id, RunHandle]`,`RunHandle = {task, bus, run_id, status}`。**强引用 task**(根治 GC 隐患);SSE 客户端断开**只取消订阅、不取消 task**;run 完成/失败/abort 才摘除。一个会话同时只允许一个在跑 run。
2. **事件总线按会话/线程注册表持有**(不再每次 start_turn 新建)→ 重连能接回**同一条在跑的总线**拿实时事件。Code 复用 harness EventBus(落 harness_items);Builder 复用 DbEventPublisher(落 conversation_events)。两者都已"内存广播 + 落库带 seq"。
3. **统一"重连"端点 = 补历史 + 跟实时**(对齐 serve-logs):`attach?after_seq=N` → 先从库回放 `seq>N`,再订阅在跑总线跟随实时,直到 run 结束/空闲;断开只 unsubscribe。
4. **状态查询端点**:`run-status` → `{running, last_seq, run_id}`,前端切回据此决定是否重连。

## 数据流

- **开跑**:发消息 → 建 run 后台任务 + 注册 RunRegistry → 前端 attach(after_seq=0)。
- **切走**:前端只关 attach 读取(**不再 abort run**)→ task 后台继续 → 事件继续进总线 + 落库。
- **切回**:前端 GET run-status → 在跑则 attach(after_seq=本地最后 seq)→ 补漏 + 接回实时,喂进现有 SSE 状态机(useCodingPipeline / aiChat reducer,**状态机不改**)。

## 生命周期 / 收尾

- **一会话单 run**:发新消息时若已有在跑 run → **守卫(决策①)**:提示"有任务在跑,请等它完成或先停止"挡住,不自动停旧的(避免并发竞态/误丢)。
- **abort/停止键照常**:显式停 = 取消 task + 标 aborted + 摘除注册表。
- **清理**:run 完成即摘除;`startup_recovery`(超 10 分钟悬挂标 aborted)兜底后端重启场景。

## 前端(两页同款,状态机不改,只接线两处 + 新增 attach 函数)

- CodingPage:`abortInflightStream` 切会话**改为只关读取、不 abort run**;`switchConversationFromHeader` / `loadCodingConversationOnly` 加"查状态 → 在跑则 attach 续看"。
- AIChatPage:`loadSession` 同款。
- 共用思路:新增 `attachRunStream(convId, fromSeq)`,内部复用现有 SSE 消费(`consumePipelineSse` / `handleSseEvent`)。

## 分阶段

- **阶段 1 — Code(/coding)**:harness 已有后台任务+总线+replay,改造最小。RunRegistry(强引用 task)+ 总线注册表持有 + attach/run-status 端点 + 前端切走不 abort/切回 attach。**先做通+真机验**。
- **阶段 2 — Builder(/ai-chat)**:run_agent 内联 → 先拆成后台任务发到 DbEventPublisher 总线,再接 attach/run-status + AIChatPage 重连。

## 测试

- 后端:RunRegistry(注册/摘除/单会话单 run/强引用不被 GC);attach(补历史 + 跟实时 + 断开不杀 task);run-status;abort 仍生效;发新消息守卫。
- 端到端:开跑 → 切走 → run 后台继续 → 切回 attach 看到完整进度(真机)。

## 非目标(YAGNI)

- 后端重启/部署续跑(全持久)——本轮不做。
- 同会话并发多 run——不做(守卫挡住)。
- 跨进程/多实例(Redis 同步)——单实例够用,不做。
