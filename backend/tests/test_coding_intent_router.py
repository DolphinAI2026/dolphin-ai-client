"""N1: AI Coding 意图路由测试

验收条件：
1. classify_coding_intent
   a. "读一下有哪些应用" → READ
   b. "建个图书首页双端组件" → BUILD（走 LLM）
   c. LLM 失败 → BUILD（兜底）
   d. 模糊/不确定 → BUILD（保守）

2. READ 路径 (run_read_query)
   - 不调用 _create_workspace_now（无 workspace 创建）
   - 不调用 detect_scene / codegen
   - emit 了 tool + content + done 事件
   - done 事件 workspace_id=None

3. BUILD 路径回归
   - classify_coding_intent("建个图书首页双端组件") → BUILD
   - pipeline.run_coding_pipeline 入口处 classify 返 BUILD 时，走原有 codegen（不进 run_read_query）

4. run_coding_pipeline + is_iteration=True（已有 ws_id） → 跳过意图分类直接走 codegen
"""
from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.coding.read_query import classify_coding_intent, run_read_query


# ───────────────────────────────────────────────────────────────────────────
# 1. classify_coding_intent
# ───────────────────────────────────────────────────────────────────────────

class TestClassifyCodingIntent:
    """意图分类单测（mock LLM，不走真实网络）"""

    @pytest.mark.asyncio
    async def test_read_intent_via_llm(self):
        """LLM 返回 READ → 分类为 READ"""
        mock_resp = {
            "choices": [{"message": {"content": "READ"}}]
        }
        # load_coding_llm_config 是在函数内 local import，patch 其源模块路径
        with patch("app.agents.coding.llm_config.load_coding_llm_config",
                   new=AsyncMock(return_value=("http://api", "key", "model"))), \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_resp_obj = MagicMock()
            mock_resp_obj.json.return_value = mock_resp
            mock_resp_obj.raise_for_status = MagicMock()
            mock_ctx.post = AsyncMock(return_value=mock_resp_obj)
            mock_client_cls.return_value = mock_ctx

            result = await classify_coding_intent(1, "model", "读一下有哪些应用")

        assert result == "READ"

    @pytest.mark.asyncio
    async def test_build_intent_keyword_shortcut(self):
        """消息含「建」等 BUILD 关键词 → 直接 BUILD，不走 LLM"""
        # 不 mock 任何 LLM — 如果走 LLM 会报 connection error
        result = await classify_coding_intent(1, "model", "建个图书首页双端组件")
        assert result == "BUILD"

    @pytest.mark.asyncio
    async def test_build_intent_via_llm(self):
        """LLM 返回 BUILD → 分类为 BUILD"""
        mock_resp = {
            "choices": [{"message": {"content": "BUILD"}}]
        }
        with patch("app.agents.coding.llm_config.load_coding_llm_config",
                   new=AsyncMock(return_value=("http://api", "key", "model"))), \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_resp_obj = MagicMock()
            mock_resp_obj.json.return_value = mock_resp
            mock_resp_obj.raise_for_status = MagicMock()
            mock_ctx.post = AsyncMock(return_value=mock_resp_obj)
            mock_client_cls.return_value = mock_ctx

            # 无 BUILD 关键词的消息
            result = await classify_coding_intent(1, "model", "帮我查一下字典")

        assert result == "BUILD"

    @pytest.mark.asyncio
    async def test_llm_failure_fallback_to_build(self):
        """LLM 抛异常 → 兜底 BUILD，不崩"""
        with patch("app.agents.coding.llm_config.load_coding_llm_config",
                   new=AsyncMock(side_effect=RuntimeError("no llm"))):
            result = await classify_coding_intent(1, "model", "列出所有模型字段")

        assert result == "BUILD"

    @pytest.mark.asyncio
    async def test_ambiguous_falls_back_to_build(self):
        """LLM 返回奇怪内容 → 兜底 BUILD"""
        mock_resp = {
            "choices": [{"message": {"content": "MAYBE_READ?"}}]
        }
        with patch("app.agents.coding.llm_config.load_coding_llm_config",
                   new=AsyncMock(return_value=("http://api", "key", "model"))), \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_resp_obj = MagicMock()
            mock_resp_obj.json.return_value = mock_resp
            mock_resp_obj.raise_for_status = MagicMock()
            mock_ctx.post = AsyncMock(return_value=mock_resp_obj)
            mock_client_cls.return_value = mock_ctx

            result = await classify_coding_intent(1, "model", "查看一下应用情况")

        assert result == "BUILD"  # MAYBE_READ? 不是 READ → BUILD


# ───────────────────────────────────────────────────────────────────────────
# 2. run_read_query — 不建 workspace、emit tool + content + done
# ───────────────────────────────────────────────────────────────────────────

class _FakePlatformEnv:
    id = 42
    is_default = True
    tenant_id = 1


class _FakeParams:
    tenant_id = 1
    selected_model = None
    message = "列一下有哪些应用"


def _make_mock_db(env: _FakePlatformEnv | None = _FakePlatformEnv()):
    """构造一个假 AsyncSession，模拟 platform_env 查询结果。"""
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = env
    db.execute = AsyncMock(return_value=mock_result)
    return db


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _make_llm_resp(content: str = "", tool_calls: list | None = None) -> dict:
    msg: dict = {"content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {"choices": [{"message": msg}]}


def _fake_stream_llm(turns):
    """按轮消费的 _stream_llm 假实现: 每次调用取一个 turn, 填 sink 并流式 yield content。"""
    it = iter(turns)

    async def fake(base_url, api_key, payload, sink):
        t = next(it, {})
        sink.setdefault("content", "")
        sink.setdefault("tool_calls", [])
        c = t.get("content") or ""
        if c:
            sink["content"] += c
            yield c
        sink["tool_calls"].extend(t.get("tool_calls") or [])

    return fake


class TestRunReadQuery:
    """run_read_query 功能测试（mock LLM + apaas 工具）"""

    @pytest.mark.asyncio
    async def test_emits_tool_content_done_on_tool_call(self):
        """LLM 先调工具 → 工具 chip → 再给文字 → done(workspace=None)"""
        tool_call = {
            "id": "tc1",
            "function": {"name": "list_apaas_apps", "arguments": "{}"},
        }
        # 第一轮：LLM 返回 tool_call；第二轮：LLM 返回 content(流式 _stream_llm 直接替换)
        mock_tool_result = json.dumps({"ok": True, "apps": [{"app_name": "图书借阅"}]})

        with patch("app.agents.coding.llm_config.load_coding_llm_config",
                   new=AsyncMock(return_value=("http://api", "key", "model"))), \
             patch("app.coding.read_query._stream_llm",
                   new=_fake_stream_llm([
                       {"tool_calls": [tool_call]},
                       {"content": "共有 3 个应用：图书借阅、采购管理、客户管理"},
                   ])), \
             patch.dict(
                 "app.coding.read_query._READ_ONLY_EXECUTORS",
                 {"list_apaas_apps": AsyncMock(return_value=mock_tool_result)},
             ):
            db = _make_mock_db()
            events = []
            async for ev in run_read_query(_FakeParams(), db):
                events.append(ev)

        types = [e["type"] for e in events]
        assert "tool" in types, "应 emit tool chip"
        assert "content" in types, "应 emit content"
        assert "done" in types, "应 emit done"

        done_ev = next(e for e in events if e["type"] == "done")
        assert done_ev["workspace_id"] is None

    @pytest.mark.asyncio
    async def test_no_platform_env_emits_graceful_message(self):
        """没有 platform_env → emit 提示消息 + done，不崩"""
        db = _make_mock_db(env=None)
        with patch("app.agents.coding.llm_config.load_coding_llm_config",
                   new=AsyncMock(return_value=("http://api", "key", "model"))):
            events = []
            async for ev in run_read_query(_FakeParams(), db):
                events.append(ev)

        types = [e["type"] for e in events]
        assert "content" in types
        assert "done" in types
        done_ev = next(e for e in events if e["type"] == "done")
        assert done_ev["workspace_id"] is None

    @pytest.mark.asyncio
    async def test_non_readonly_tool_not_executed(self):
        """LLM 试图调非只读工具 → 报 error result，不执行"""
        tool_call = {
            "id": "tc_bad",
            "function": {"name": "write_artifact", "arguments": '{"content": "bad"}'},
        }
        with patch("app.agents.coding.llm_config.load_coding_llm_config",
                   new=AsyncMock(return_value=("http://api", "key", "model"))), \
             patch("app.coding.read_query._stream_llm",
                   new=_fake_stream_llm([
                       {"tool_calls": [tool_call]},
                       {"content": "好的，已处理"},
                   ])):
            db = _make_mock_db()
            events = []
            async for ev in run_read_query(_FakeParams(), db):
                events.append(ev)

        # 非只读工具不 emit "tool" running/done chip
        tool_running = [e for e in events if e.get("type") == "tool" and e.get("name") == "write_artifact"]
        assert not tool_running, "非只读工具不应被执行或 emit tool chip"

    @pytest.mark.asyncio
    async def test_does_not_call_create_workspace(self):
        """READ 路径不调 _create_workspace_now 或任何 workspace 创建逻辑"""
        # WorkspaceManager.create_workspace 是非 closure 的，可以 patch
        with patch("app.agents.coding.llm_config.load_coding_llm_config",
                   new=AsyncMock(return_value=("http://api", "key", "model"))), \
             patch("app.coding.read_query._stream_llm",
                   new=_fake_stream_llm([{"content": "查询完成"}])), \
             patch("app.coding.workspace.WorkspaceManager.create_workspace",
                   side_effect=AssertionError("不应调 create_workspace")) as mock_ws:
            db = _make_mock_db()
            events = []
            async for ev in run_read_query(_FakeParams(), db):
                events.append(ev)

            # run_read_query 正常完成说明 create_workspace 没被调
            mock_ws.assert_not_called()

    @pytest.mark.asyncio
    async def test_workspace_read_exposes_app_status_and_search_tools(self, tmp_path):
        """有工作区时，READ 路径仍应暴露应用状态工具和 search_tools。"""
        (tmp_path / ".workspace.json").write_text(
            json.dumps({"id": "1_ws", "project_id": 5}, ensure_ascii=False),
            encoding="utf-8",
        )

        class _WorkspaceParams(_FakeParams):
            workspace_id = "1_ws"
            conversation_id = None
            app_id = None
            message = "应用重新发布了吗？"

        payloads: list[dict] = []

        async def _capture_payload(base_url, api_key, payload, sink):
            payloads.append(payload)
            sink.setdefault("content", "")
            sink.setdefault("tool_calls", [])
            sink["content"] += "先查应用状态。"
            yield "先查应用状态。"

        with patch("app.agents.coding.llm_config.load_coding_llm_config",
                   new=AsyncMock(return_value=("http://api", "key", "model"))), \
             patch("app.coding.workspace.WorkspaceManager.get_workspace_path",
                   return_value=tmp_path), \
             patch("app.coding.read_query._stream_llm", new=_capture_payload):
            db = _make_mock_db()
            events = []
            async for ev in run_read_query(_WorkspaceParams(), db):
                events.append(ev)

        assert payloads, "应发起 LLM 调用"
        tool_names = {
            tool.get("function", {}).get("name")
            for tool in payloads[0].get("tools", [])
        }
        assert "get_current_workspace_app_status" in tool_names
        assert "search_tools" in tool_names

    @pytest.mark.asyncio
    async def test_search_tools_only_returns_readonly_tools(self):
        """READ 路径 search_tools 只能发现只读工具，不能激活 republish 等写工具。"""
        tool_call = {
            "id": "tc_search",
            "function": {
                "name": "search_tools",
                "arguments": json.dumps({"query": "发布 重新发布"}, ensure_ascii=False),
            },
        }
        with patch("app.agents.coding.llm_config.load_coding_llm_config",
                   new=AsyncMock(return_value=("http://api", "key", "model"))), \
             patch("app.coding.read_query._stream_llm",
                   new=_fake_stream_llm([
                       {"tool_calls": [tool_call]},
                       {"content": "可以先看当前应用发布状态。"},
                   ])):
            db = _make_mock_db()
            events = []
            async for ev in run_read_query(_FakeParams(), db):
                events.append(ev)

        search_done = next(
            e for e in events
            if e.get("type") == "tool"
            and e.get("name") == "search_tools"
            and e.get("status") == "done"
        )
        result = json.loads(search_done["result"])
        assert "get_current_workspace_app_status" in result["activated"]
        assert "republish_apaas_app" not in result["activated"]
        assert "deploy_dev_workspace_to_app" not in result["activated"]

    @pytest.mark.asyncio
    async def test_current_workspace_app_status_resolves_bound_app_publish_state(self, tmp_path):
        """状态工具从工作区 project_id 反查 Application，并返回本地发布状态。"""
        (tmp_path / ".workspace.json").write_text(
            json.dumps({"id": "1_ws", "project_id": 5}, ensure_ascii=False),
            encoding="utf-8",
        )

        class _WorkspaceParams(_FakeParams):
            workspace_id = "1_ws"
            conversation_id = None
            app_id = None
            message = "应用重新发布了吗？"

        app = MagicMock()
        app.id = 5
        app.app_name = "企业级研发项目管理PMS"
        app.app_code = "rd-pms"
        app.status = "completed"
        app.apaas_app_id = "852927940168515584"
        app.platform_env_id = 63
        app.created_at = datetime(2026, 6, 12, 9, 0, 0)
        app.updated_at = datetime(2026, 6, 12, 10, 0, 0)

        deploy = MagicMock()
        deploy.id = 9
        deploy.version_label = "v3"
        deploy.completed_at = datetime(2026, 6, 12, 10, 30, 0)
        deploy.user_id = 1
        deploy.deploy_type = "publish"

        tool_call = {
            "id": "tc_status",
            "function": {
                "name": "get_current_workspace_app_status",
                "arguments": "{}",
            },
        }
        with patch("app.agents.coding.llm_config.load_coding_llm_config",
                   new=AsyncMock(return_value=("http://api", "key", "model"))), \
             patch("app.coding.workspace.WorkspaceManager.get_workspace_path",
                   return_value=tmp_path), \
             patch("app.coding.read_query._stream_llm",
                   new=_fake_stream_llm([
                       {"tool_calls": [tool_call]},
                       {"content": "应用已有成功发布记录。"},
                   ])):
            db = _make_mock_db()
            db.execute = AsyncMock(side_effect=[
                _scalar_result(_FakePlatformEnv()),
                _scalar_result(app),
                _scalar_result(deploy),
            ])
            events = []
            async for ev in run_read_query(_WorkspaceParams(), db):
                events.append(ev)

        status_done = next(
            e for e in events
            if e.get("type") == "tool"
            and e.get("name") == "get_current_workspace_app_status"
            and e.get("status") == "done"
        )
        result = json.loads(status_done["result"])
        assert result["ok"] is True
        assert result["app"]["local_app_id"] == 5
        assert result["app"]["apaas_app_id"] == "852927940168515584"
        assert result["publish_status"]["status"] == "published"
        assert result["publish_status"]["latest_deploy"]["version"] == "v3"


# ───────────────────────────────────────────────────────────────────────────
# 3. BUILD 路径 keyword 快速路径
# ───────────────────────────────────────────────────────────────────────────

class TestBuildKeywords:
    @pytest.mark.parametrize("msg", [
        "建个图书首页双端组件",
        "做一个数据查询页面",
        "写一个后端接口",
        "创建一个新应用",
        "开发一个采购管理系统",
    ])
    @pytest.mark.asyncio
    async def test_build_keyword_always_build(self, msg):
        """含 BUILD 关键词的消息，不 mock LLM 也能快速返回 BUILD"""
        result = await classify_coding_intent(None, "model", msg)
        assert result == "BUILD", f"期待 BUILD，得到 {result!r}（消息：{msg!r}）"


# ───────────────────────────────────────────────────────────────────────────
# 4. is_iteration=True 时 pipeline 跳过意图分类（集成钩子测试）
# ───────────────────────────────────────────────────────────────────────────

class TestPipelineIntegration:
    """验证 pipeline.py 中意图门的接入点是否正确。"""

    @pytest.mark.asyncio
    async def test_iteration_skips_intent_classification(self):
        """is_iteration=True 时，classify_coding_intent 不被调用。"""
        # 验证方式：patch classify_coding_intent，然后走 pipeline，确认它没被调
        # pipeline 内 is_iteration = ws_id is not None，传一个假 ws_id 就能触发
        from app.coding import pipeline as pl
        from app.coding.pipeline import PipelineParams

        fake_params = PipelineParams(
            message="列一下应用",
            user_id=1,
            tenant_id=1,
            workspace_id="ws-exists-123",  # is_iteration=True
        )

        with patch.object(pl, "classify_coding_intent", new=AsyncMock()) as mock_classify, \
             patch.object(pl, "run_read_query", new=AsyncMock()) as mock_read, \
             patch.object(pl, "_detect_scene_llm_call",
                         new=AsyncMock(side_effect=Exception("测试提前终止"))), \
             patch("app.coding.pipeline.resolve_effective_coding_model",
                   new=AsyncMock(return_value=("model", 1))), \
             patch("app.agents.coding.llm_config.load_coding_llm_config",
                   new=AsyncMock(return_value=("http://fake/v1", "k", "gpt-x"))):
            db = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            db.execute = AsyncMock(return_value=mock_result)
            db.get = AsyncMock(return_value=None)

            events = []
            try:
                async for ev in pl.run_coding_pipeline(fake_params, db):
                    events.append(ev)
                    if len(events) > 30:  # 安全阀
                        break
            except Exception:
                pass  # 测试只关心 classify 没被调

            # is_iteration=True → classify 不调
            mock_classify.assert_not_called()
            mock_read.assert_not_called()

    @pytest.mark.asyncio
    async def test_first_turn_read_intent_goes_to_read_query(self):
        """首轮且 classify=READ → run_read_query 被调，_detect_scene_llm_call 不被调。"""
        from app.coding import pipeline as pl
        from app.coding.pipeline import PipelineParams

        fake_params = PipelineParams(
            message="列一下有哪些应用",
            user_id=1,
            tenant_id=1,
            workspace_id=None,  # is_iteration=False
        )

        read_events = [
            {"type": "content", "content": "共 3 个应用"},
            {"type": "done", "workspace_id": None, "conversation_id": None},
        ]

        async def _fake_read_query(params, db):
            for ev in read_events:
                yield ev

        with patch.object(pl, "classify_coding_intent",
                         new=AsyncMock(return_value="READ")) as mock_classify, \
             patch.object(pl, "run_read_query", new=_fake_read_query) as mock_read, \
             patch.object(pl, "_detect_scene_llm_call",
                         new=AsyncMock(side_effect=AssertionError("不应调 detect_scene"))) as mock_detect, \
             patch("app.coding.pipeline.resolve_effective_coding_model",
                   new=AsyncMock(return_value=("model", 1))), \
             patch("app.agents.coding.llm_config.load_coding_llm_config",
                   new=AsyncMock(return_value=("http://fake/v1", "k", "gpt-x"))):
            db = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            db.execute = AsyncMock(return_value=mock_result)
            db.get = AsyncMock(return_value=None)
            db.add = MagicMock()

            events = []
            async for ev in pl.run_coding_pipeline(fake_params, db):
                events.append(ev)

        mock_classify.assert_awaited_once()
        # detect_scene 不被调（如果调了会 raise AssertionError，测试会失败）
        mock_detect.assert_not_called()

        types = [e["type"] for e in events]
        assert "content" in types
        assert "done" in types

    @pytest.mark.asyncio
    async def test_first_turn_build_intent_calls_detect_scene(self):
        """首轮且 classify=BUILD → pipeline 继续走，不进 run_read_query，emit detect_scene 事件。"""
        from app.coding import pipeline as pl
        from app.coding.pipeline import PipelineParams
        from app.coding.scenes import SceneType

        fake_params = PipelineParams(
            message="建个图书首页双端组件",
            user_id=1,
            tenant_id=1,
            workspace_id=None,
        )

        # mock Conversation 创建成功
        mock_conv = MagicMock()
        mock_conv.id = 99
        mock_conv.selected_llm_config_id = None
        mock_conv.workspace_id = None

        with patch.object(pl, "classify_coding_intent",
                         new=AsyncMock(return_value="BUILD")) as mock_classify, \
             patch.object(pl, "run_read_query") as mock_read, \
             patch.object(pl, "_detect_scene_llm_call",
                         new=AsyncMock(return_value=SceneType.WEB_COMPONENT_DUAL)) as mock_detect, \
             patch("app.coding.pipeline.resolve_effective_coding_model",
                   new=AsyncMock(return_value=("model", 1))), \
             patch("app.agents.coding.llm_config.load_coding_llm_config",
                   new=AsyncMock(return_value=("http://fake/v1", "k", "gpt-x"))):
            db = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            db.execute = AsyncMock(return_value=mock_result)
            db.get = AsyncMock(return_value=None)
            db.commit = AsyncMock()
            db.refresh = AsyncMock(side_effect=lambda conv: setattr(conv, 'id', 99) or None)
            db.add = MagicMock()

            events = []
            try:
                async for ev in pl.run_coding_pipeline(fake_params, db):
                    events.append(ev)
                    # 等到 detect_scene:done 或 scene_detected — 此时 LLM 调用已发生
                    if ev.get("type") == "scene_detected":
                        break
                    if ev.get("step") == "detect_scene" and ev.get("status") == "done":
                        break
                    if len(events) > 30:  # 安全阀
                        break
            except Exception:
                pass  # pipeline 后续可能因缺 mock 而失败，我们只关心前面的断言

        # classify 被调了
        mock_classify.assert_awaited_once()
        # run_read_query 没被调（classify=BUILD）
        mock_read.assert_not_called()
        # detect_scene 被调了（走进了原 codegen 流程）
        mock_detect.assert_awaited()
