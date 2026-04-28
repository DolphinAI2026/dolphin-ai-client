"""真实 pause/resume 链路集成测试（脚本化 LLM，但走完整真实工具调用）。

**背景**：之前的单测用 `_call_llm` 直接被 override 的 ScriptedAgent，绕过了 tool
执行细节，从不走 should_pause → BaseAgent.run() 退出 → suspend_session → resume 这条
真实链路。导致在真实 HTTP 环境里整个反问交互是不可用的（死锁 + 空 snapshot）。

本测试**专门**覆盖这条路径：
- 用 `ScriptedLLMClient` 伪造 OpenAI chat_completion response（返回真实 tool_call）
- Agent 的 `_call_llm` 用默认实现 —— 真的调 ctx.llm_client.chat_completion(..., tools=...)
- 真实的 `_handle_tool_calls` 执行真实工具体（detect_scene 改 state；ask_user
  设置 should_pause=True 触发 pause）
- drive_brainstorm 拿到 PAUSED 结果 → suspend_session 存 snapshot
- resume_session(user_answer) 注入 tool_result → drive_brainstorm 再跑 → is_resume=True
- 断言：scene_detect 只跑 1 次；ask_user 调用次数等于 turn 数；最终 emit_spec 成功

成功 = 反问→resume 链路真实跑通。
"""
import asyncio
import json
import os
import secrets
import sys
from typing import Any

os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.agents.brainstorm import BrainstormAgent  # noqa: E402
from app.agents.publisher import InMemoryEventPublisher  # noqa: E402
from app.agents.trace_writer import InMemoryTraceWriter  # noqa: E402
from app.agents.types import AgentContext, AgentStatus  # noqa: E402
from app.database import Base  # noqa: E402
import app.models  # noqa: F401,E402
from app.models import Conversation, User  # noqa: E402
from app.orchestrator import driver  # noqa: E402
from app.services import brainstorm_session_service as bs_svc  # noqa: E402
from app.services import spec_service  # noqa: E402


# ══════════════════════════════════════════════════════════════
# ScriptedLLMClient —— 伪装成 LLMClient，返回预设 OpenAI-format 响应
# ══════════════════════════════════════════════════════════════

class ScriptedLLMClient:
    """按调用次序返回预设 chat_completion 响应。

    每个 response 必须是完整 OpenAI chat.completions.create 返回结构：
        {"choices": [{"message": {"content": "", "tool_calls": [...]}}]}
    """

    def __init__(self, responses: list[dict[str, Any]]):
        self._responses = list(responses)
        self.call_count = 0
        self.model = "scripted-fake"
        self.calls_seen: list[dict] = []

    def _next(self) -> dict[str, Any]:
        if self.call_count >= len(self._responses):
            raise RuntimeError(
                f"ScriptedLLM ran out of responses (called {self.call_count + 1} times, "
                f"only {len(self._responses)} defined)"
            )
        resp = self._responses[self.call_count]
        self.call_count += 1
        return resp

    async def chat_completion(self, *, messages, model=None, max_tokens=8192,
                              timeout=120.0, temperature=0.3, tools=None,
                              tool_choice=None, **kw) -> dict[str, Any]:
        self.calls_seen.append({
            "messages_count": len(messages),
            "tools_count": len(tools) if tools else 0,
            "last_role": messages[-1].get("role") if messages else None,
        })
        return self._next()

    async def chat_completion_stream(self, **kw):
        # BrainstormAgent 用非流式；防御性实现
        raise NotImplementedError("scripted llm stream not used")


def _tc(tool_id: str, name: str, args: dict) -> dict:
    return {
        "id": tool_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
    }


def _resp(tool_calls: list[dict] | None = None, content: str = "") -> dict:
    return {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": content,
                "tool_calls": tool_calls or [],
            },
            "finish_reason": "tool_calls" if tool_calls else "stop",
        }],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
    }


# ══════════════════════════════════════════════════════════════
# DB fixture
# ══════════════════════════════════════════════════════════════

def _run(coro_factory):
    async def w():
        return await coro_factory()
    asyncio.run(w())


async def _make_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    session = sm()
    u = User(username=f"pr_{secrets.token_hex(3)}", hashed_password="x")
    session.add(u)
    await session.flush()
    conv = Conversation(
        user_id=u.id, tenant_id=1, title="t", agent_type="coding", status="active",
    )
    session.add(conv)
    await session.flush()
    return session, conv, u, engine


async def _close(session, engine):
    try:
        await session.close()
    finally:
        await engine.dispose()


def _make_ctx(llm_client, *, session_id: str, conv_id: int, user_id: int,
              requirement: str = "做个评分组件") -> AgentContext:
    return AgentContext(
        session_id=session_id,
        conversation_id=conv_id,
        user_id=user_id,
        tenant_id=1,
        model="scripted-fake",
        input={"requirement": requirement},
        publisher=InMemoryEventPublisher(),
        trace_writer=InMemoryTraceWriter(),
        llm_client=llm_client,
    )


# ══════════════════════════════════════════════════════════════
# 测试 1：第一次 run 在 ask_user 后真的 pause + snapshot 真的保存
# ══════════════════════════════════════════════════════════════

def test_run_pauses_at_ask_user_and_snapshot_persists():
    """首轮：detect_scene → ask_user(should_pause) → run() 退出返回 PAUSED
    driver 调 suspend_session → DB snapshot 非空，含完整 messages"""
    async def run():
        db, conv, user, engine = await _make_db()
        try:
            # 创建 brainstorm session
            bs_row = await bs_svc.create_session(
                db, conversation_id=conv.id, user_id=user.id, tenant_id=1,
                model_used="scripted-fake",
            )

            # 脚本：LLM 先调 detect_scene，再调 ask_user（触发 pause）
            llm = ScriptedLLMClient([
                _resp([_tc("t1", "detect_scene", {
                    "scene_type": "web_component_dual",
                    "confidence": 0.95,
                    "reason": "用户说评分组件",
                })]),
                _resp([_tc("t2", "ask_user", {
                    "question": "值形态是什么？",
                    "options": [
                        {"value": "scalar", "label": "单值"},
                        {"value": "range", "label": "范围"},
                    ],
                    "priority": 1,
                    "p1_key": "form_value_shape",
                })]),
            ])

            ctx = _make_ctx(llm, session_id=bs_row.id, conv_id=conv.id, user_id=user.id)
            agent = BrainstormAgent(ctx)

            result = await driver.drive_brainstorm(
                db, agent=agent, session_id=bs_row.id,
            )

            # driver 拿到 PAUSED（不是 emitted/degraded）
            assert result.status == "paused", (
                f"expected paused, got {result.status}. "
                f"agent.status={agent.status}, stop_reason={agent._stop_reason}"
            )
            # LLM 被调用了 2 次（detect_scene + ask_user）
            assert llm.call_count == 2, f"LLM call_count={llm.call_count}"

            # state 里场景已识别
            from app.spec.schema import SceneType
            assert agent.state.scene_type == SceneType.WEB_COMPONENT_DUAL
            assert agent.state.scene_confidence == 0.95
            assert len(agent.state.p1_questions) > 0

            # 关键：DB snapshot 已保存 + 内容完整
            fresh = await bs_svc.get_session(db, bs_row.id)
            assert fresh.status == bs_svc.BsStatus.SUSPENDED, (
                f"session should be suspended, got {fresh.status}"
            )
            snap = fresh.agent_snapshot
            assert snap is not None, "snapshot should be non-None after pause"
            assert snap["messages"], "snapshot.messages should contain history"
            # messages 至少包含: system / user / assistant(detect_scene) /
            # tool(detect_scene result) / assistant(ask_user)
            assert len(snap["messages"]) >= 5

            # 最后一条 assistant message 带 ask_user 的 tool_call
            last_asst = next(
                (m for m in reversed(snap["messages"]) if m.get("role") == "assistant"),
                None,
            )
            assert last_asst is not None
            tcs = last_asst.get("tool_calls") or []
            assert len(tcs) >= 1
            assert tcs[-1]["function"]["name"] == "ask_user"
        finally:
            await _close(db, engine)

    _run(run)


# ══════════════════════════════════════════════════════════════
# 测试 2：resume_session 注入用户答案为 tool_result，再次 run 不重跑 detect_scene
# ══════════════════════════════════════════════════════════════

def test_resume_injects_tool_result_and_continues_without_rerunning_scene_detect():
    """
    1. 首轮 pause（detect_scene + ask_user）
    2. resume_session(user_answer="scalar") → messages 末尾注入 role=tool 消息
    3. 新 agent from_snapshot + run() → is_resume=True，不重跑 detect_scene
    4. 第二次 LLM 被调用看到的 messages 里有"scalar"答案 → 继续问下一个或 emit
    """
    async def run():
        db, conv, user, engine = await _make_db()
        try:
            bs_row = await bs_svc.create_session(
                db, conversation_id=conv.id, user_id=user.id, tenant_id=1,
                model_used="scripted-fake",
            )

            # —— 第一次 run: detect_scene + ask_user → pause —— #
            llm1 = ScriptedLLMClient([
                _resp([_tc("s1", "detect_scene", {
                    "scene_type": "web_component_dual", "confidence": 0.9,
                    "reason": "x",
                })]),
                _resp([_tc("a1", "ask_user", {
                    "question": "值形态?", "priority": 1,
                    "p1_key": "form_value_shape",
                })]),
            ])
            ctx1 = _make_ctx(llm1, session_id=bs_row.id, conv_id=conv.id, user_id=user.id)
            agent1 = BrainstormAgent(ctx1)
            r1 = await driver.drive_brainstorm(db, agent=agent1, session_id=bs_row.id)
            assert r1.status == "paused"
            assert llm1.call_count == 2

            # —— resume + 注入用户答案 —— #
            llm2 = ScriptedLLMClient([
                # 第 3 次 LLM 调用（resume 后第一次）：再问一个 P1
                _resp([_tc("a2", "ask_user", {
                    "question": "BOF 类型?", "priority": 1,
                    "p1_key": "bof_type",
                })]),
            ])
            ctx2 = _make_ctx(llm2, session_id=bs_row.id, conv_id=conv.id, user_id=user.id)
            _, agent2 = await bs_svc.resume_session(
                db, session_id=bs_row.id, ctx=ctx2, user_answer="scalar",
            )

            # 关键：_messages 被恢复 + 注入的 tool_result 在末尾
            assert len(agent2._messages) >= 6, (
                f"resumed messages should be >=6, got {len(agent2._messages)}"
            )
            last = agent2._messages[-1]
            assert last.get("role") == "tool", f"last msg role={last.get('role')}"
            assert "scalar" in (last.get("content") or ""), (
                f"tool content should contain 'scalar', got {last.get('content')}"
            )
            assert last.get("tool_call_id") == "a1", (
                f"should match first ask_user's tool_call_id, got {last.get('tool_call_id')}"
            )
            # resume 后 p1 状态应来自 snapshot（尚未回答）
            assert agent2.state.scene_type is not None, (
                "scene should be preserved from snapshot"
            )

            # —— 第二次 run：从中断处继续 —— #
            r2 = await driver.drive_brainstorm(db, agent=agent2, session_id=bs_row.id)
            assert r2.status == "paused", f"expected paused again, got {r2.status}"
            # 关键：LLM 只被调 1 次（不是 3 次从头！）
            assert llm2.call_count == 1, (
                f"llm2 should be called once (resume 后 只问 BOF)，got {llm2.call_count}"
            )
            # LLM 看到的 messages 里有"scalar"（通过 tool_result 注入）
            assert llm2.calls_seen[0]["last_role"] == "tool"

            # 事件层面：不应该出现第二次 scene_detected
            all_events = ctx1.publisher.events + ctx2.publisher.events
            scene_events = [e for e in all_events if e["type"] == "brainstorm.scene_detected"]
            assert len(scene_events) == 1, (
                f"scene_detected should fire once across resume, got {len(scene_events)}"
            )
        finally:
            await _close(db, engine)

    _run(run)


# ══════════════════════════════════════════════════════════════
# 测试 3：多轮 pause/resume 最后 emit_spec
# ══════════════════════════════════════════════════════════════

def test_full_multi_round_pause_resume_to_emit():
    """完整链路：
    run 1: detect_scene → ask_user → pause
    resume: user answer "scalar" → run 2: ask_user("bof_type") → pause
    resume: user answer "BOF_NUMBER" → run 3: ask_user("scenes") → pause
    resume: user answer "edit,read" → run 4: emit_spec → done

    断言：全程 scene_detect 只 1 次；最终 Spec 被保存；phase = confirm。
    """
    async def run():
        db, conv, user, engine = await _make_db()
        try:
            from app.orchestrator import start_brainstorm, get_phase
            from app.orchestrator.phases import Phase

            bs_row = await start_brainstorm(
                db, conversation_id=conv.id, user_id=user.id, tenant_id=1, model="m",
            )
            await db.commit()
            session_id = bs_row.id

            # —— Round 1 —— #
            llm1 = ScriptedLLMClient([
                _resp([_tc("s1", "detect_scene", {
                    "scene_type": "web_component_dual", "confidence": 0.95, "reason": "r",
                })]),
                _resp([_tc("a1", "ask_user", {
                    "question": "值形态?", "priority": 1, "p1_key": "form_value_shape",
                })]),
            ])
            ctx1 = _make_ctx(llm1, session_id=session_id, conv_id=conv.id, user_id=user.id)
            agent1 = BrainstormAgent(ctx1)
            r1 = await driver.drive_brainstorm(db, agent=agent1, session_id=session_id)
            assert r1.status == "paused"
            await db.commit()

            # —— Round 2: resume with answer —— #
            llm2 = ScriptedLLMClient([
                _resp([_tc("a2", "ask_user", {
                    "question": "BOF?", "priority": 1, "p1_key": "bof_type",
                })]),
            ])
            ctx2 = _make_ctx(llm2, session_id=session_id, conv_id=conv.id, user_id=user.id)
            _, agent2 = await bs_svc.resume_session(
                db, session_id=session_id, ctx=ctx2, user_answer="scalar",
            )
            # resume_session 应该自动把 form_value_shape 标 answered
            q_form = next(q for q in agent2.state.p1_questions if q.key == "form_value_shape")
            assert q_form.answered, "form_value_shape should be marked answered after resume"
            assert q_form.answer == "scalar"
            r2 = await driver.drive_brainstorm(db, agent=agent2, session_id=session_id)
            assert r2.status == "paused"
            assert llm2.call_count == 1
            await db.commit()

            # —— Round 3 —— #
            llm3 = ScriptedLLMClient([
                _resp([_tc("a3", "ask_user", {
                    "question": "scenes?", "priority": 1, "p1_key": "scenes_required",
                })]),
            ])
            ctx3 = _make_ctx(llm3, session_id=session_id, conv_id=conv.id, user_id=user.id)
            _, agent3 = await bs_svc.resume_session(
                db, session_id=session_id, ctx=ctx3, user_answer="BOF_NUMBER",
            )
            q_bof = next(q for q in agent3.state.p1_questions if q.key == "bof_type")
            assert q_bof.answered and q_bof.answer == "BOF_NUMBER"
            r3 = await driver.drive_brainstorm(db, agent=agent3, session_id=session_id)
            assert r3.status == "paused"
            await db.commit()

            # —— Round 4: answer + emit_spec —— #
            emit_args = {
                "scene_type": "web_component_dual",
                "identity": {
                    "code_name": "rating-star",
                    "display_name": "评分",
                    "description_cn": "星级评分",
                    "widget_code": "FORM_CUSTOM_RATING_STAR",
                },
                "intent": {
                    "original_requirement": "做个评分组件",
                    "core_purpose": "1-5 星打分",
                    "acceptance_criteria": ["用户可点击 1-5 星打分"],
                },
                "spec": {
                    "data": {
                        "bof_type": "BOF_NUMBER",
                        "component_model_field": ["NUM"],
                        "form_value_shape": "scalar",
                        "default_value": 0,
                        "storage_note": "1-5 整数",
                    },
                    "config_properties": [],
                    "scenes_required": ["edit", "read"],
                    "scenes_optional": [],
                },
                "open_questions": [],
            }
            llm4 = ScriptedLLMClient([
                _resp([_tc("e1", "emit_spec", emit_args)]),
            ])
            ctx4 = _make_ctx(llm4, session_id=session_id, conv_id=conv.id, user_id=user.id)
            _, agent4 = await bs_svc.resume_session(
                db, session_id=session_id, ctx=ctx4, user_answer="edit, read",
            )
            # resume 自动 mark 所有 P1 answered（依赖上一轮 ask_user 带的 p1_key）
            assert agent4.state.p1_coverage() == 1.0, (
                f"expected p1_coverage=1.0 after all 3 resumes, got "
                f"{agent4.state.p1_coverage()}; p1={[(q.key, q.answered) for q in agent4.state.p1_questions]}"
            )

            r4 = await driver.drive_brainstorm(db, agent=agent4, session_id=session_id)
            assert r4.status == "emitted", f"expected emitted, got {r4.status}"
            assert r4.spec_id is not None
            assert r4.spec_envelope is not None
            # DB 主键 / envelope.spec_id / spec_emitted 事件 spec_id 必须三方一致，
            # 否则前端按事件 spec_id GET /api/coding/v2/specs/{id} 会 404。
            assert r4.spec_id == r4.spec_envelope["spec_id"], (
                f"driver.spec_id={r4.spec_id} != envelope.spec_id={r4.spec_envelope['spec_id']}"
            )
            spec_emitted_events = [
                e for e in ctx4.publisher.events if e["type"] == "brainstorm.spec_emitted"
            ]
            assert len(spec_emitted_events) == 1
            assert spec_emitted_events[0]["data"]["spec_id"] == r4.spec_id
            await db.commit()

            # 关键断言：scene_detected 只被触发一次
            all_events = (
                ctx1.publisher.events + ctx2.publisher.events
                + ctx3.publisher.events + ctx4.publisher.events
            )
            scene_events = [
                e for e in all_events if e["type"] == "brainstorm.scene_detected"
            ]
            assert len(scene_events) == 1, (
                f"scene_detected fired {len(scene_events)} times; should be exactly 1"
            )

            # phase 推进
            assert await get_phase(db, conv.id) == Phase.CONFIRM

            # Spec 落盘
            spec_row = await spec_service.get_spec(db, r4.spec_id)
            assert spec_row is not None
            assert spec_row.code_name == "rating-star"
            assert spec_row.widget_code == "FORM_CUSTOM_RATING_STAR"
        finally:
            await _close(db, engine)

    _run(run)


# ══════════════════════════════════════════════════════════════
# 测试 4：run() 的 is_resume 分支不会覆盖 _messages
# ══════════════════════════════════════════════════════════════

def test_run_resume_does_not_rebuild_initial_messages():
    """直接测 base.run() 的分支：预先填 _messages（模拟 from_snapshot），
    然后 run() 不应该把它清空重建。"""
    async def run():
        db, conv, user, engine = await _make_db()
        try:
            llm = ScriptedLLMClient([
                _resp([], content="done"),   # 无 tool_call → 立即退出
            ])
            ctx = _make_ctx(llm, session_id="s1", conv_id=conv.id, user_id=user.id)
            agent = BrainstormAgent(ctx)
            # 模拟 from_snapshot：预填充 _messages + _turn
            preset = [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "u"},
                {"role": "assistant", "content": "", "tool_calls": [
                    {"id": "x", "type": "function",
                     "function": {"name": "detect_scene", "arguments": "{}"}},
                ]},
                {"role": "tool", "tool_call_id": "x", "content": "ok"},
            ]
            agent._messages = list(preset)
            agent._turn = 2

            result = await agent.run()
            assert result.status == AgentStatus.COMPLETED
            # 前 4 条消息完全保持原状（不被 build_initial_user_message 覆盖）
            for i, orig in enumerate(preset):
                assert agent._messages[i] == orig, (
                    f"msg[{i}] changed: was {orig} now {agent._messages[i]}"
                )
            # turn 至少是 2（保留）+ 可能 +1
            assert agent._turn >= 2
            # LLM 被调 1 次（直接从 preset 末尾的 tool 消息继续）
            assert llm.call_count == 1
        finally:
            await _close(db, engine)

    _run(run)


# ══════════════════════════════════════════════════════════════
# 测试 5：fresh run 依旧重建 initial messages（兼容性）
# ══════════════════════════════════════════════════════════════

def test_run_fresh_still_builds_initial_messages():
    """非 resume 场景（_messages 是空 list），run() 正常构造 system + user"""
    async def run():
        db, conv, user, engine = await _make_db()
        try:
            llm = ScriptedLLMClient([
                _resp([], content="quick done"),
            ])
            ctx = _make_ctx(llm, session_id="s2", conv_id=conv.id, user_id=user.id,
                            requirement="做个组件吧")
            agent = BrainstormAgent(ctx)
            assert agent._messages == []  # fresh
            result = await agent.run()
            assert result.status == AgentStatus.COMPLETED
            # 构造了 initial messages
            assert len(agent._messages) >= 3  # system + user + assistant
            assert agent._messages[0]["role"] == "system"
            assert agent._messages[1]["role"] == "user"
            assert "做个组件吧" in agent._messages[1]["content"]
        finally:
            await _close(db, engine)

    _run(run)


if __name__ == "__main__":
    import inspect, traceback as _tb
    current = sys.modules[__name__]
    tests = [
        (n, f) for n, f in inspect.getmembers(current, inspect.isfunction)
        if n.startswith("test_")
    ]
    passed = failed = 0
    for name, func in tests:
        try:
            func()
            print(f"✓ {name}")
            passed += 1
        except Exception as e:
            print(f"✗ {name}: {type(e).__name__}: {e}")
            _tb.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
