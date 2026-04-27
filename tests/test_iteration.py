"""迭代分级 + SpecPatch 集成测试。

覆盖：
- classify_iteration：无 LLM 走启发式、LLM 返回 JSON 解析、trivial 带 patch、
  LLM 错误时 fallback、低 confidence 降级、cross_scene 识别
- iteration_service.apply_patch_as_new_spec：
  trivial patch → 新 spec v2；未知 base → 错；非法 patch 路径 → PatchApplyError
"""
import asyncio
import json
import os
import secrets
import sys

os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.agents.iteration import (  # noqa: E402
    IterationLevel,
    PatchApplyError,
    PatchOp,
    SpecPatch,
    classify_heuristic,
    classify_iteration,
)
from app.database import Base  # noqa: E402
import app.models  # noqa: F401,E402
from app.models import Conversation, User  # noqa: E402
from app.services import brainstorm_session_service as bs_svc  # noqa: E402
from app.services import iteration_service, spec_service  # noqa: E402


# ══════════════════════════════════════════════════════════════
# 辅助
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
    u = User(username=f"it_{secrets.token_hex(3)}", hashed_password="x")
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


def _component_envelope() -> dict:
    return {
        "schema_version": "1.0",
        "scene_type": "web_component_dual",
        "spec_id": "unused",
        "provenance": {
            "brainstorm_session_id": "bs_x",
            "created_at": "2026-04-20T00:00:00+00:00",
            "created_by": "agent",
            "model": "m",
            "version": 1,
            "confidence": 0.9,
            "open_questions": [],
        },
        "identity": {
            "code_name": "rating-star",
            "display_name": "评分",
            "description_cn": "星级评分",
            "widget_code": "FORM_CUSTOM_RATING_STAR",
        },
        "intent": {
            "original_requirement": "做评分",
            "core_purpose": "1-5 星",
            "acceptance_criteria": ["可点击 1-5 星"],
        },
        "spec": {
            "data": {
                "bof_type": "BOF_NUMBER", "component_model_field": ["NUM"],
                "form_value_shape": "scalar", "default_value": 0, "storage_note": "x",
            },
            "config_properties": [
                {
                    "key": "primaryColor", "type": "string", "label": "主色",
                    "default": "#409EFF", "required": False,
                    "ui_editor": "form-custom-color-editor", "is_custom_editor": False,
                },
            ],
            "scenes_required": ["edit", "read"],
            "scenes_optional": [],
        },
    }


# ══════════════════════════════════════════════════════════════
# classify_heuristic（无 LLM）
# ══════════════════════════════════════════════════════════════

def test_heuristic_trivial_hint_downgrades_to_minor():
    """启发式识别到"改成 X"→ minor（因为没法自动产 patch）"""
    env = _component_envelope()
    r = classify_heuristic("把主色改成红色", env)
    assert r.level == IterationLevel.MINOR
    assert r.patch is None


def test_heuristic_minor_fuzzy_words():
    env = _component_envelope()
    r = classify_heuristic("弄漂亮一点", env)
    assert r.level == IterationLevel.MINOR


def test_heuristic_major_new_feature():
    env = _component_envelope()
    r = classify_heuristic("加一个备注字段", env)
    assert r.level == IterationLevel.MAJOR


def test_heuristic_cross_scene_component_to_page():
    env = _component_envelope()
    r = classify_heuristic("把它改成页面", env)
    assert r.level == IterationLevel.CROSS_SCENE


def test_heuristic_cross_scene_page_to_component():
    env = _component_envelope()
    env["scene_type"] = "web_page"
    r = classify_heuristic("改成组件", env)
    assert r.level == IterationLevel.CROSS_SCENE


def test_heuristic_fallback_to_major():
    env = _component_envelope()
    r = classify_heuristic("阿巴阿巴", env)  # 无法识别
    assert r.level == IterationLevel.MAJOR


# ══════════════════════════════════════════════════════════════
# classify_iteration with LLM (mock)
# ══════════════════════════════════════════════════════════════

class _FakeLLM:
    """最小可用的 LLMClient 替身"""
    def __init__(self, response: str):
        self._response = response
        self.model = "fake-model"
        self.calls: list[dict] = []

    async def chat_completion(self, *, messages, model, max_tokens=8192, temperature=0.3, **kw):
        self.calls.append({"messages": messages, "model": model})
        return {
            "choices": [{"message": {"content": self._response}}],
        }


def test_llm_classify_trivial_with_patch():
    env = _component_envelope()
    llm_response = json.dumps({
        "level": "trivial",
        "rationale": "改默认主色，明确小修改",
        "confidence": 0.92,
        "patch": {
            "operations": [
                {"op": "set", "path": "spec.config_properties[0].default", "value": "#FF0000"},
            ],
            "rationale": "改主色为红色",
        },
    })
    llm = _FakeLLM(llm_response)

    r = asyncio.run(classify_iteration(
        user_message="主色改成红色",
        spec_envelope=env,
        llm_client=llm,
    ))
    assert r.level == IterationLevel.TRIVIAL
    assert r.patch is not None
    assert len(r.patch.operations) == 1
    assert r.patch.operations[0].value == "#FF0000"
    assert r.confidence == 0.92
    assert r.patch.iteration_level == IterationLevel.TRIVIAL
    # 调用记录
    assert len(llm.calls) == 1


def test_llm_classify_minor_without_patch():
    env = _component_envelope()
    llm_response = json.dumps({
        "level": "minor",
        "rationale": "用户说『弄漂亮』，太模糊，需要反问细节",
        "confidence": 0.8,
        "patch": None,
    })
    r = asyncio.run(classify_iteration(
        user_message="弄漂亮点",
        spec_envelope=env,
        llm_client=_FakeLLM(llm_response),
    ))
    assert r.level == IterationLevel.MINOR
    assert r.patch is None


def test_llm_classify_major():
    env = _component_envelope()
    llm_response = json.dumps({
        "level": "major",
        "rationale": "新增字段影响 Spec 结构",
        "confidence": 0.85,
    })
    r = asyncio.run(classify_iteration(
        user_message="加一个备注字段",
        spec_envelope=env,
        llm_client=_FakeLLM(llm_response),
    ))
    assert r.level == IterationLevel.MAJOR


def test_llm_classify_cross_scene():
    env = _component_envelope()
    llm_response = json.dumps({
        "level": "cross_scene",
        "rationale": "scene 从 component 变成 page",
        "confidence": 0.9,
    })
    r = asyncio.run(classify_iteration(
        user_message="改成管理页面",
        spec_envelope=env,
        llm_client=_FakeLLM(llm_response),
    ))
    assert r.level == IterationLevel.CROSS_SCENE


def test_llm_classify_extracts_json_from_code_block():
    env = _component_envelope()
    raw = '```json\n{"level": "minor", "rationale": "r", "confidence": 0.7}\n```'
    r = asyncio.run(classify_iteration(
        user_message="优化一下",
        spec_envelope=env,
        llm_client=_FakeLLM(raw),
    ))
    assert r.level == IterationLevel.MINOR


def test_llm_classify_trivial_low_confidence_downgrades():
    """LLM 说 trivial 但 confidence=0.3 → 自动降到 minor"""
    env = _component_envelope()
    llm_response = json.dumps({
        "level": "trivial",
        "rationale": "可能是简单改动",
        "confidence": 0.3,
        "patch": {
            "operations": [
                {"op": "set", "path": "spec.config_properties[0].default", "value": "#F00"},
            ],
        },
    })
    r = asyncio.run(classify_iteration(
        user_message="x", spec_envelope=env, llm_client=_FakeLLM(llm_response),
    ))
    assert r.level == IterationLevel.MINOR
    assert r.patch is None


def test_llm_classify_trivial_without_patch_downgrades():
    """LLM 说 trivial 但没给 patch → 降到 minor（因为无可执行计划）"""
    env = _component_envelope()
    llm_response = json.dumps({
        "level": "trivial",
        "rationale": "小改",
        "confidence": 0.9,
        "patch": None,
    })
    r = asyncio.run(classify_iteration(
        user_message="x", spec_envelope=env, llm_client=_FakeLLM(llm_response),
    ))
    assert r.level == IterationLevel.MINOR


def test_llm_classify_invalid_level_falls_back_major():
    env = _component_envelope()
    llm_response = json.dumps({
        "level": "invalid_enum",
        "rationale": "?",
        "confidence": 0.5,
    })
    r = asyncio.run(classify_iteration(
        user_message="x", spec_envelope=env, llm_client=_FakeLLM(llm_response),
    ))
    assert r.level == IterationLevel.MAJOR


def test_llm_classify_no_json_fallback_heuristic():
    env = _component_envelope()
    llm = _FakeLLM("抱歉我只会说人话，没有 JSON 给你")
    r = asyncio.run(classify_iteration(
        user_message="改成红色", spec_envelope=env, llm_client=llm,
    ))
    # 启发式对"改成红色"返回 minor（因为它是 TRIVIAL_HINT 但启发式无法产 patch）
    assert r.level == IterationLevel.MINOR
    assert "启发式" in r.rationale


def test_llm_classify_exception_fallback_heuristic():
    class _ErrLLM:
        model = "e"
        async def chat_completion(self, **kw):
            raise RuntimeError("LLM down")

    env = _component_envelope()
    r = asyncio.run(classify_iteration(
        user_message="加一个备注", spec_envelope=env, llm_client=_ErrLLM(),
    ))
    assert r.level == IterationLevel.MAJOR  # 启发式识别到"加一个"→ major
    assert "启发式" in r.rationale


def test_classify_without_llm_client_uses_heuristic():
    env = _component_envelope()
    r = asyncio.run(classify_iteration(
        user_message="加一个字段", spec_envelope=env, llm_client=None,
    ))
    assert r.level == IterationLevel.MAJOR  # 启发式


# ══════════════════════════════════════════════════════════════
# iteration_service.apply_patch_as_new_spec
# ══════════════════════════════════════════════════════════════

async def _seed_base_spec(db, conv, user):
    bs_row = await bs_svc.create_session(
        db, conversation_id=conv.id, user_id=user.id, tenant_id=1, model_used="m",
    )
    envelope = _component_envelope()
    envelope["provenance"]["brainstorm_session_id"] = bs_row.id
    spec_row = await spec_service.save_spec(
        db, brainstorm_session_id=bs_row.id, envelope=envelope,
    )
    await db.commit()
    return bs_row, spec_row


def test_apply_patch_creates_new_version():
    async def run():
        db, conv, user, engine = await _make_db()
        try:
            _bs, base = await _seed_base_spec(db, conv, user)

            patch = SpecPatch(
                base_spec_id=base.id,
                operations=[PatchOp(
                    op="set",
                    path="spec.config_properties[0].default",
                    value="#FF0000",
                )],
                rationale="改主色",
                user_instruction="主色改成红色",
                iteration_level=IterationLevel.TRIVIAL,
            )
            new_row = await iteration_service.apply_patch_as_new_spec(
                db, base_spec_id=base.id, patch=patch,
            )
            await db.commit()

            # 新版本号 +1
            assert new_row.version == 2
            assert new_row.parent_version == 1
            # 不同 spec_id
            assert new_row.id != base.id
            # 同 code_name / 同 session
            assert new_row.code_name == base.code_name
            assert new_row.brainstorm_session_id == base.brainstorm_session_id
            # 内容已变更
            new_cp = new_row.content["spec"]["config_properties"][0]
            assert new_cp["default"] == "#FF0000"
            # provenance.created_by = mixed
            assert new_row.content["provenance"]["created_by"] == "mixed"
        finally:
            await _close(db, engine)
    _run(run)


def test_apply_patch_base_not_found_raises():
    async def run():
        db, conv, user, engine = await _make_db()
        try:
            patch = SpecPatch(
                base_spec_id="ghost",
                operations=[PatchOp(op="set", path="x", value=1)],
                iteration_level=IterationLevel.TRIVIAL,
            )
            try:
                await iteration_service.apply_patch_as_new_spec(
                    db, base_spec_id="ghost", patch=patch,
                )
            except ValueError:
                return
            raise AssertionError("expected ValueError")
        finally:
            await _close(db, engine)
    _run(run)


def test_apply_patch_bad_path_raises():
    async def run():
        db, conv, user, engine = await _make_db()
        try:
            _bs, base = await _seed_base_spec(db, conv, user)
            patch = SpecPatch(
                base_spec_id=base.id,
                operations=[PatchOp(op="set", path="not.exist.path", value=1)],
                iteration_level=IterationLevel.TRIVIAL,
            )
            try:
                await iteration_service.apply_patch_as_new_spec(
                    db, base_spec_id=base.id, patch=patch,
                )
            except PatchApplyError:
                return
            raise AssertionError("expected PatchApplyError")
        finally:
            await _close(db, engine)
    _run(run)


def test_apply_patch_rejects_major_level():
    async def run():
        db, conv, user, engine = await _make_db()
        try:
            _bs, base = await _seed_base_spec(db, conv, user)
            patch = SpecPatch(
                base_spec_id=base.id,
                operations=[PatchOp(op="set", path="identity.display_name", value="new")],
                iteration_level=IterationLevel.MAJOR,  # 不允许
            )
            try:
                await iteration_service.apply_patch_as_new_spec(
                    db, base_spec_id=base.id, patch=patch,
                )
            except PatchApplyError:
                return
            raise AssertionError("expected PatchApplyError")
        finally:
            await _close(db, engine)
    _run(run)


def test_apply_patch_result_passes_business_validation():
    """patch 完的 envelope 必须通过 validators —— 例：不能设置非法 widget_code"""
    async def run():
        db, conv, user, engine = await _make_db()
        try:
            _bs, base = await _seed_base_spec(db, conv, user)
            # widget_code 改成非法（小写），save_spec 会拒绝
            patch = SpecPatch(
                base_spec_id=base.id,
                operations=[PatchOp(op="set", path="identity.widget_code", value="form_custom_lowercase")],
                iteration_level=IterationLevel.TRIVIAL,
            )
            try:
                await iteration_service.apply_patch_as_new_spec(
                    db, base_spec_id=base.id, patch=patch,
                )
            except Exception as e:
                # 应该是 Pydantic schema invalid 或 SpecValidationError
                assert "invalid" in str(e).lower() or "VALIDATION" in str(e).upper() or "widget_code" in str(e).lower()
                return
            raise AssertionError("expected validation error")
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
