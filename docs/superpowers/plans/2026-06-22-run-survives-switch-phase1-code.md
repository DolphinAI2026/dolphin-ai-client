# 切会话不丢 run — Phase 1 (Code/harness) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** /coding 的 agent run 脱离 SSE 连接——切会话/刷新/断网后台续跑,切回从 last seq 重连补历史+跟实时。

**Architecture:** 进程级 `RunRegistry`(按 conversation_id 持有在跑 turn 的 `task` + `EventBus` 强引用,根治 GC + 让重连接回同一总线)。harness `start_turn` 已是后台任务 + EventBus(落 harness_items,有 `replay_events(after_seq)`),只需注册化 + 加 `run-status`/`attach` 端点 + 前端切走不 abort/切回重连。

**Tech Stack:** FastAPI + sse-starlette(EventSourceResponse)、asyncio、SQLAlchemy async;前端 Vue3 + fetch SSE(useCodingPipeline)。

## Global Constraints

- 进程内持久:后端重启不保(startup_recovery 已标 aborted 兜底)。一会话同时只 1 个在跑 run。
- 复用现有:harness `EventBus`(app/harness/events.py)、`replay_events`(manager.py:247)、`consumePipelineSse`(useCodingPipeline.ts)。状态机不改,只接线。
- 测试用 `.venv/bin/python -m pytest`;后端 reload=False,改后端验证前重启进程。
- 客户端断开**只 unsubscribe,不取消 task**(现状 manager.py:240-241 已如此,勿回退)。

---

### Task 1: RunRegistry 进程级注册表

**Files:**
- Create: `backend/app/harness/run_registry.py`
- Test: `backend/tests/test_run_registry.py`

**Interfaces:**
- Produces:
  - `class RunHandle` 字段 `task: asyncio.Task`, `event_bus`, `run_id: str | None`, `thread_id: int`
  - `run_registry`(模块级单例)方法:
    - `register(conversation_id: int, handle: RunHandle) -> None`
    - `get(conversation_id: int) -> RunHandle | None`
    - `unregister(conversation_id: int) -> None`
    - `is_running(conversation_id: int) -> bool`(handle 存在且 `not handle.task.done()`)

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_run_registry.py
import asyncio
import pytest
from app.harness.run_registry import run_registry, RunHandle


@pytest.mark.asyncio
async def test_register_get_unregister():
    async def _noop():
        await asyncio.sleep(0.01)
    task = asyncio.create_task(_noop())
    h = RunHandle(task=task, event_bus=object(), run_id="r1", thread_id=7)
    run_registry.register(101, h)
    assert run_registry.is_running(101) is True
    assert run_registry.get(101) is h
    await task
    # task 跑完后 is_running 为 False(即便还没 unregister)
    assert run_registry.is_running(101) is False
    run_registry.unregister(101)
    assert run_registry.get(101) is None


@pytest.mark.asyncio
async def test_register_replaces_and_single_per_conversation():
    async def _noop():
        await asyncio.sleep(0.01)
    t1 = asyncio.create_task(_noop()); t2 = asyncio.create_task(_noop())
    run_registry.register(202, RunHandle(task=t1, event_bus=object(), run_id="a", thread_id=1))
    run_registry.register(202, RunHandle(task=t2, event_bus=object(), run_id="b", thread_id=2))
    assert run_registry.get(202).run_id == "b"  # 后者覆盖,单会话单 run
    await asyncio.gather(t1, t2)
    run_registry.unregister(202)
```

- [ ] **Step 2: 跑测试看失败** — `Run: .venv/bin/python -m pytest tests/test_run_registry.py -v` Expected: FAIL(ModuleNotFoundError run_registry)

- [ ] **Step 3: 实现**

```python
# backend/app/harness/run_registry.py
"""进程级在跑 run 注册表 —— 让 agent run 脱离 SSE 连接(切会话不丢)。

强引用后台 task(否则 asyncio 只弱引用、客户端断开后闭包被 GC → task 被取消)。
按 conversation_id 持有(一会话单 run),重连时据此接回同一条在跑 EventBus。
进程内:后端重启不保(startup_recovery 兜底标 aborted)。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any


@dataclass
class RunHandle:
    task: asyncio.Task
    event_bus: Any
    run_id: str | None
    thread_id: int


class RunRegistry:
    def __init__(self) -> None:
        self._runs: dict[int, RunHandle] = {}

    def register(self, conversation_id: int, handle: RunHandle) -> None:
        self._runs[conversation_id] = handle

    def get(self, conversation_id: int) -> RunHandle | None:
        return self._runs.get(conversation_id)

    def unregister(self, conversation_id: int) -> None:
        self._runs.pop(conversation_id, None)

    def is_running(self, conversation_id: int) -> bool:
        h = self._runs.get(conversation_id)
        return bool(h and not h.task.done())


run_registry = RunRegistry()
```

- [ ] **Step 4: 跑测试看通过** — `Run: .venv/bin/python -m pytest tests/test_run_registry.py -v` Expected: PASS

- [ ] **Step 5: 提交** — `git add backend/app/harness/run_registry.py backend/tests/test_run_registry.py && git commit -m "feat(harness): RunRegistry 进程级在跑 run 注册表"`

---

### Task 2: start_turn 注册 task+bus,完成后摘除

**Files:**
- Modify: `backend/app/harness/manager.py`(start_turn,146-243)
- Test: `backend/tests/test_harness_run_registered.py`

**Interfaces:**
- Consumes: `run_registry`, `RunHandle`(Task 1)
- 行为:start_turn 内 `task = create_task(_run_turn_background())` 后,若 `thread_ctx.conversation_id` 非空 → `run_registry.register(conversation_id, RunHandle(task, event_bus, run_id=str(turn_id), thread_id))`;`_run_turn_background` 的 `finally` 末尾 `run_registry.unregister(conversation_id)`。

- [ ] **Step 1: 写失败测试** —— 断言 start_turn 跑起来后 `run_registry.is_running(conversation_id)` 为 True,turn 完成后变 False。

```python
# backend/tests/test_harness_run_registered.py
# 用内存 StaticPool DB + monkeypatch AsyncSessionLocal(参考 tests/test_agent_observability_*.py 的建库方式);
# 构造一个 profile.run_turn 立即返回的 fake profile(monkeypatch get_profile),
# create_thread(conversation_id=303) → start_turn → 消费完事件流 → 断言:
#   - 流式中途 run_registry.is_running(303) 曾为 True
#   - 流结束 + 摘除后 is_running(303) 为 False
```
（实现时按 test_agent_observability_phase1 的 DB fixture 套路落地具体代码。）

- [ ] **Step 2: 跑测试看失败** — Expected: FAIL(is_running 始终 False)

- [ ] **Step 3: 实现** —— manager.py:

在 `task = asyncio.create_task(_run_turn_background())`(218)后加:
```python
        from app.harness.run_registry import run_registry, RunHandle
        _conv_id = thread_ctx.conversation_id
        if _conv_id is not None:
            run_registry.register(
                _conv_id,
                RunHandle(task=task, event_bus=event_bus, run_id=str(turn_id), thread_id=thread_ctx.thread_id),
            )
```
在 `_run_turn_background` 的 `finally`(207-215)末尾 `await event_bus.send_sentinel()` 之后加:
```python
                if thread_ctx.conversation_id is not None:
                    run_registry.unregister(thread_ctx.conversation_id)
```

- [ ] **Step 4: 跑测试看通过** — Expected: PASS

- [ ] **Step 5: 提交** — `git commit -am "feat(harness): start_turn 注册/摘除在跑 run 到 RunRegistry"`

---

### Task 3: run-status 端点(前端切回据此决定是否重连)

**Files:**
- Modify: `backend/app/routes/harness.py`(新增端点)
- Test: `backend/tests/test_harness_run_status.py`

**Interfaces:**
- Produces: `GET /harness/coding/run-status?conversation_id=N` → `{"running": bool, "last_seq": int, "run_id": str | None}`
  - running = `run_registry.is_running(conversation_id)`;last_seq = handle.event_bus.current_seq(在跑)或该会话最近 thread.last_seq(不在跑)。

- [ ] **Step 1: 写失败测试** —— 无在跑 run → `{running: False}`;注册一个假 handle(bus.current_seq=5)→ `{running: True, last_seq: 5}`。

- [ ] **Step 2: 跑测试看失败**

- [ ] **Step 3: 实现** —— routes/harness.py 加:
```python
@router.get("/coding/run-status")
async def coding_run_status(
    conversation_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    from app.harness.run_registry import run_registry
    h = run_registry.get(conversation_id)
    if h and not h.task.done():
        return {"running": True, "last_seq": getattr(h.event_bus, "current_seq", 0), "run_id": h.run_id}
    return {"running": False, "last_seq": 0, "run_id": None}
```
（`current_seq` 属性已存在于 EventBus,见 manager.py:212 用法。）

- [ ] **Step 4: 跑测试看通过**

- [ ] **Step 5: 提交** — `git commit -am "feat(harness): coding run-status 端点"`

---

### Task 4: attach 端点(补历史 seq>N + 跟实时,断开不杀 task)

**Files:**
- Modify: `backend/app/routes/harness.py`(新增 SSE 端点)+ `backend/app/harness/manager.py`(加 `attach_stream` 辅助)
- Test: `backend/tests/test_harness_run_attach.py`

**Interfaces:**
- Produces: `GET /harness/coding/attach?conversation_id=N&after_seq=S` → EventSourceResponse,事件与 `/coding/pipeline` 同构(经同一 sse adapter,带 `_seq`)。
  - 流程:① 从 DB `replay_events(thread_id, after_seq=S)` 补发 seq>S 历史;② 若 run_registry 有在跑 handle → `event_bus.subscribe()` 跟实时到 sentinel;③ 不在跑 → 补完历史即结束(EventSourceResponse 关闭)。
  - thread_id 来源:在跑取 handle.thread_id;不在跑查该 conversation 最近 thread。

- [ ] **Step 1: 写失败测试** —— 注册一个在跑 handle(bus 已 publish seq1..3);attach(after_seq=1)应先收到 seq2、seq3(历史补发),再收到后续 publish 的 seq4(实时);客户端断开订阅后,handle.task 仍 `not done()`(不被取消)。

- [ ] **Step 2: 跑测试看失败**

- [ ] **Step 3: 实现** —— manager.py 加 `attach_stream(conversation_id, after_seq, tenant_id)` 异步生成器:
```python
    async def attach_stream(self, conversation_id: int, *, after_seq: int, tenant_id: int) -> AsyncIterator[dict]:
        from app.harness.run_registry import run_registry
        handle = run_registry.get(conversation_id)
        # 解析 thread_id
        if handle and not handle.task.done():
            thread_id = handle.thread_id
        else:
            thread_id = await self._latest_thread_id_for_conversation(conversation_id, tenant_id)
            if thread_id is None:
                return
        # 1) 历史补发
        for ev in await self.replay_events(thread_id, after_seq=after_seq, tenant_id=tenant_id):
            yield ev
        # 2) 实时跟随(仅在跑时)
        handle = run_registry.get(conversation_id)
        if not (handle and not handle.task.done()):
            return
        from app.harness.events import _SENTINEL
        from app.harness.profiles import get_profile  # 取 sse adapter
        adapter = get_sse_adapter(...)  # 与 start_turn 同 profile 的 adapter
        q = handle.event_bus.subscribe()
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    if handle.task.done():
                        break
                    yield {"type": "heartbeat"}
                    continue
                if event.get("event_type") == _SENTINEL:
                    break
                # 只发 after_seq 之后没在历史里补过的(seq 单调,replay 已发到 current);
                # 简化:实时段 seq 必 > 历史补发的最大,直接发
                translated = adapter.translate(event)
                if translated:
                    translated["_seq"] = event.get("seq", 0)
                    yield translated
        finally:
            handle.event_bus.unsubscribe(q)  # 只取消订阅,不取消 task
```
routes/harness.py 加端点包成 EventSourceResponse(参考 `_start_coding_turn_sse` 的 sse_generator 包法,ping=15)。
⚠️ adapter 取法与 start_turn 一致(profile.get_sse_adapter_name → get_sse_adapter)。`_latest_thread_id_for_conversation` = 查 HarnessThreadModel where conversation_id==, tenant==, order by id desc limit 1。

- [ ] **Step 4: 跑测试看通过**

- [ ] **Step 5: 提交** — `git commit -am "feat(harness): coding attach 端点(补历史+跟实时,断开不杀 task)"`

---

### Task 5: /coding/pipeline 发送守卫(已有在跑 run 则挡)

**Files:**
- Modify: `backend/app/routes/harness.py`(_start_coding_turn_sse 入口)
- Test: `backend/tests/test_harness_run_status.py`(追加)

**Interfaces:**
- 行为:`/coding/pipeline` 入口若 `conversation_id` 且 `run_registry.is_running(conversation_id)` → 返回 409 `{"detail": "该会话有任务在跑,请等它完成或先停止"}`。

- [ ] **Step 1: 写失败测试** —— 注册在跑 handle → POST /coding/pipeline 同 conversation_id → 409。

- [ ] **Step 2: 跑测试看失败**

- [ ] **Step 3: 实现** —— `_start_coding_turn_sse` 顶部:
```python
    from app.harness.run_registry import run_registry
    if conversation_id is not None and run_registry.is_running(conversation_id):
        raise HTTPException(status_code=409, detail="该会话有任务在跑,请等它完成或先停止")
```

- [ ] **Step 4: 跑测试看通过**

- [ ] **Step 5: 提交** — `git commit -am "feat(harness): coding 发送守卫(单会话单 run)"`

---

### Task 6: 前端 API — run-status + attach URL

**Files:**
- Modify: `frontend/src/api/harness.ts`(或 coding.ts 中 harness 相关处)
- Test: 无(薄封装,随 Task 8 端到端验)

**Interfaces:**
- Produces:
  - `getCodingRunStatus(conversationId: number): Promise<{running:boolean; last_seq:number; run_id:string|null}>`
  - `codingAttachUrl(conversationId: number, afterSeq: number): string`(给 fetch SSE,token 走 header,与 codingPipelineUrl 同款鉴权)

- [ ] **Step 1: 实现**(直接加,无 TDD)
```typescript
getCodingRunStatus(conversationId: number) {
  return request.get(`/harness/coding/run-status?conversation_id=${conversationId}`)
},
codingAttachUrl(conversationId: number, afterSeq: number): string {
  return `${API_PREFIX}/harness/coding/attach?conversation_id=${conversationId}&after_seq=${afterSeq}`
},
```

- [ ] **Step 2: 提交** — `git commit -am "feat(coding-fe): run-status + attach API"`

---

### Task 7: CodingPage 切走不 abort run / 切回重连 + 发送守卫

**Files:**
- Modify: `frontend/src/views/CodingPage.vue`(abortInflightStream:1010、switchConversationFromHeader:1015、loadCodingConversationOnly:1483)、`frontend/src/views/coding/useCodingPipeline.ts`(暴露 attach + detach)

**Interfaces:**
- Consumes: Task 6 API、`consumePipelineSse`(useCodingPipeline 现有)
- 改动要点:
  1. 切会话**不再** `stopStream()`(那会 abort run)。改为 `detachStream()`:`currentAbort?.abort()` 仅断**读取**(run 在后端继续),`isStreaming=false`。语义换名以防误用。
  2. 切回(switchConversationFromHeader/loadCodingConversationOnly)在 `loadConversationHistory` 之后:`const st = await getCodingRunStatus(id); if (st.running) attachRunStream(id, lastSeqFromHistory)`。
  3. `attachRunStream(convId, fromSeq)`:`currentAbort=new AbortController(); fetch(codingAttachUrl(convId,fromSeq),{signal}); await consumePipelineSse(resp)`(复用现有 SSE 消费 → 事件接回状态机)。
  4. 发送守卫:`sendMessage` 捕获 409 → `ElMessage.warning(detail)`,不清输入。
- `lastSeqFromHistory`:从 replay 的 stream_messages 里取最大 `_seq`(没有则 0)。attach 后端会补 seq>fromSeq。

- [ ] **Step 1: useCodingPipeline 暴露 `attachStream(url)`**(包装 fetch+consumePipelineSse)与 `detachStream()`(只 abort 读取);区别于 `stopStream()`(= 真停,Task 后续用于停止键)。

- [ ] **Step 2: CodingPage 切会话两处:`abortInflightStream` 内部由 `stopStream()` 改 `detachStream()`**

- [ ] **Step 3: 切回两处加 run-status 检测 + attachRunStream**

- [ ] **Step 4: sendMessage 加 409 守卫提示**

- [ ] **Step 5: `npm run build:nocheck` 通过(预存 vue-tsc 坏,用 nocheck)** — `Run: cd frontend && npm run build:nocheck` Expected: 成功无报错

- [ ] **Step 6: 提交** — `git commit -am "feat(coding-fe): 切会话不 abort run + 切回 attach 续看 + 发送守卫"`

---

### Task 8: 端到端真机验证

**Files:** 无(验证)

- [ ] **Step 1:** 重启 dev 后端(加载新代码):`pkill -f 'run.py'; cd backend && nohup .venv/bin/python run.py > /tmp/dev.log 2>&1 & disown`
- [ ] **Step 2:** 浏览器 :5173 /coding 开一个会跑较久的 codegen;趁在跑切到另一会话。
- [ ] **Step 3:** 后端日志确认 run **未中断**(turn 继续 publish);`curl /harness/coding/run-status?conversation_id=<id>` 返回 `running:true`。
- [ ] **Step 4:** 切回原会话 → 应自动 attach、补上漏掉的步骤并继续跟实时到 done(playwright 截图/snapshot 证明进度接上)。
- [ ] **Step 5:** 在跑时再发一条 → 409 提示。
- [ ] **Step 6:** 总结验证结果(诚实标注未覆盖项)。

---

## Self-Review

- **Spec coverage**:RunRegistry(T1)、后台 task 强引用+总线注册(T2)、attach 补历史+跟实时(T4)、run-status(T3)、发送守卫(T5)、前端切走不 abort/切回重连(T6/T7)、端到端(T8)。覆盖 spec 阶段1 全部。Builder(阶段2)另起计划。
- **Placeholder**:T2 测试用"按 observability fixture 落地"指引(DB 建库样板已存在,执行时照抄);T4 adapter 取法标注与 start_turn 一致。核心新代码(RunRegistry/attach 生成器/端点)已给全。
- **Type 一致**:RunHandle{task,event_bus,run_id,thread_id} 跨 T1-T4 一致;run-status 返回 {running,last_seq,run_id} 与前端 T6/T7 一致;attach 事件带 `_seq` 与 pipeline 同构。
- **风险**:attach 实时段与历史段 seq 去重——简化为"实时段 seq 必 > 历史最大",若并发 publish 有缝隙,前端按 `_seq` 幂等(同 seq 覆盖)兜底,T8 验证。
