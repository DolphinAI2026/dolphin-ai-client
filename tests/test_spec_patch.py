"""SpecPatch 单元测试 —— 路径解析、apply set/add/remove、版本号 bump、错误处理。"""
import os
import sys

os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.agents.iteration import (  # noqa: E402
    IterationLevel,
    PatchApplyError,
    PatchOp,
    SpecPatch,
    apply_patch,
    validate_path,
)


# ══════════════════════════════════════════════════════════════
# 辅助 envelope
# ══════════════════════════════════════════════════════════════

def _envelope() -> dict:
    return {
        "schema_version": "1.0",
        "scene_type": "web_component_dual",
        "spec_id": "spec_v1",
        "provenance": {"version": 1, "confidence": 0.9, "created_by": "agent"},
        "identity": {
            "code_name": "rating-star",
            "display_name": "评分",
            "description_cn": "x",
            "widget_code": "FORM_CUSTOM_RATING_STAR",
        },
        "intent": {
            "original_requirement": "做评分",
            "core_purpose": "1-5 星",
            "acceptance_criteria": ["可点击"],
        },
        "spec": {
            "data": {"bof_type": "BOF_NUMBER", "default_value": 0},
            "config_properties": [
                {"key": "primaryColor", "default": "#409EFF"},
                {"key": "maxStars", "default": 5},
            ],
            "scenes_required": ["edit", "read"],
        },
    }


def _patch(ops: list[dict], level: IterationLevel = IterationLevel.TRIVIAL) -> SpecPatch:
    return SpecPatch(
        base_spec_id="spec_v1",
        operations=[PatchOp.from_dict(o) for o in ops],
        rationale="test",
        user_instruction="改一下",
        iteration_level=level,
    )


# ══════════════════════════════════════════════════════════════
# validate_path
# ══════════════════════════════════════════════════════════════

def test_validate_path_simple_ok():
    assert validate_path("identity.display_name")
    assert validate_path("spec.config_properties[0].default")
    assert validate_path("a")
    assert validate_path("a[0]")
    assert validate_path("a[0][1].b")


def test_validate_path_invalid():
    assert not validate_path("")
    assert not validate_path("0.a")  # 数字开头
    assert not validate_path("a..b")
    assert not validate_path("a[b]")
    assert not validate_path("a[0][")
    assert not validate_path(".a")


# ══════════════════════════════════════════════════════════════
# apply set
# ══════════════════════════════════════════════════════════════

def test_apply_set_scalar_field():
    env = _envelope()
    patch = _patch([{"op": "set", "path": "identity.display_name", "value": "五星评分"}])
    out = apply_patch(env, patch)
    # 原 envelope 未被 mutate
    assert env["identity"]["display_name"] == "评分"
    # 新 envelope 应用成功
    assert out["identity"]["display_name"] == "五星评分"


def test_apply_set_nested_array_element():
    env = _envelope()
    patch = _patch([{
        "op": "set",
        "path": "spec.config_properties[0].default",
        "value": "#FF0000",
    }])
    out = apply_patch(env, patch)
    assert out["spec"]["config_properties"][0]["default"] == "#FF0000"


def test_apply_set_replaces_whole_dict():
    env = _envelope()
    new_cp = {"key": "primaryColor", "default": "#333"}
    patch = _patch([{
        "op": "set",
        "path": "spec.config_properties[0]",
        "value": new_cp,
    }])
    out = apply_patch(env, patch)
    assert out["spec"]["config_properties"][0] == new_cp


def test_apply_set_missing_path_raises():
    env = _envelope()
    patch = _patch([{"op": "set", "path": "identity.nonexistent_parent.x", "value": 1}])
    try:
        apply_patch(env, patch)
    except PatchApplyError:
        return
    raise AssertionError("expected PatchApplyError")


# ══════════════════════════════════════════════════════════════
# apply add
# ══════════════════════════════════════════════════════════════

def test_apply_add_append_to_array():
    env = _envelope()
    new_cp = {"key": "allowHalf", "default": False}
    patch = _patch([{
        "op": "add",
        "path": "spec.config_properties",
        "value": new_cp,
    }])
    out = apply_patch(env, patch)
    assert len(out["spec"]["config_properties"]) == 3
    assert out["spec"]["config_properties"][-1] == new_cp


def test_apply_add_new_dict_key():
    env = _envelope()
    patch = _patch([{
        "op": "add",
        "path": "spec.extra_field",
        "value": "hello",
    }])
    out = apply_patch(env, patch)
    assert out["spec"]["extra_field"] == "hello"


def test_apply_add_to_existing_key_rejected():
    env = _envelope()
    patch = _patch([{
        "op": "add",
        "path": "identity.display_name",
        "value": "dup",
    }])
    try:
        apply_patch(env, patch)
    except PatchApplyError:
        return
    raise AssertionError("expected PatchApplyError")


def test_apply_add_at_array_index_inserts():
    env = _envelope()
    new_cp = {"key": "newFirst", "default": "x"}
    patch = _patch([{
        "op": "add",
        "path": "spec.config_properties[0]",
        "value": new_cp,
    }])
    out = apply_patch(env, patch)
    assert out["spec"]["config_properties"][0] == new_cp
    assert out["spec"]["config_properties"][1]["key"] == "primaryColor"  # 原第 0 个后移
    assert len(out["spec"]["config_properties"]) == 3


# ══════════════════════════════════════════════════════════════
# apply remove
# ══════════════════════════════════════════════════════════════

def test_apply_remove_array_element():
    env = _envelope()
    patch = _patch([{"op": "remove", "path": "spec.config_properties[0]"}])
    out = apply_patch(env, patch)
    assert len(out["spec"]["config_properties"]) == 1
    assert out["spec"]["config_properties"][0]["key"] == "maxStars"


def test_apply_remove_dict_key():
    env = _envelope()
    patch = _patch([{"op": "remove", "path": "identity.description_cn"}])
    out = apply_patch(env, patch)
    assert "description_cn" not in out["identity"]


def test_apply_remove_missing_raises():
    env = _envelope()
    patch = _patch([{"op": "remove", "path": "identity.no_such_key"}])
    try:
        apply_patch(env, patch)
    except PatchApplyError:
        return
    raise AssertionError("expected PatchApplyError")


# ══════════════════════════════════════════════════════════════
# 多 op 顺序 + 错误传播
# ══════════════════════════════════════════════════════════════

def test_apply_multi_ops_in_order():
    env = _envelope()
    patch = _patch([
        {"op": "set", "path": "identity.display_name", "value": "新名"},
        {"op": "add", "path": "spec.config_properties", "value": {"key": "a", "default": 1}},
        {"op": "remove", "path": "spec.config_properties[0]"},  # 移除原第 0 条
    ])
    out = apply_patch(env, patch)
    assert out["identity"]["display_name"] == "新名"
    # 原先 [primaryColor, maxStars] + add → [primaryColor, maxStars, a]
    # 然后 remove [0] → [maxStars, a]
    keys = [cp["key"] for cp in out["spec"]["config_properties"]]
    assert keys == ["maxStars", "a"]


def test_apply_fails_on_any_op_leaves_base_intact():
    """任一 op 失败时，apply_patch 返回前 base 完全不变（deepcopy 保护）"""
    env = _envelope()
    before = _envelope()  # 对照
    patch = _patch([
        {"op": "set", "path": "identity.display_name", "value": "新"},
        {"op": "remove", "path": "no.such.path"},  # 会 fail
    ])
    try:
        apply_patch(env, patch)
    except PatchApplyError:
        pass
    assert env == before


# ══════════════════════════════════════════════════════════════
# provenance / version bump
# ══════════════════════════════════════════════════════════════

def test_apply_bumps_version_and_parent_version():
    env = _envelope()
    env["provenance"]["version"] = 3
    patch = _patch([{"op": "set", "path": "identity.display_name", "value": "v2"}])
    out = apply_patch(env, patch)
    assert out["provenance"]["version"] == 4
    assert out["provenance"]["parent_version"] == 3
    assert out["provenance"]["created_by"] == "mixed"
    # spec_id 被清空，让 service 层重新生成
    assert out["spec_id"] == ""


def test_apply_skip_bump_version():
    env = _envelope()
    patch = _patch([{"op": "set", "path": "identity.display_name", "value": "v2"}])
    out = apply_patch(env, patch, bump_version=False)
    assert out["provenance"]["version"] == 1  # 未 bump
    assert out.get("spec_id") == "spec_v1"    # 未清空


# ══════════════════════════════════════════════════════════════
# iteration_level 门槛
# ══════════════════════════════════════════════════════════════

def test_apply_rejects_major_level():
    env = _envelope()
    patch = _patch(
        [{"op": "set", "path": "identity.display_name", "value": "v2"}],
        level=IterationLevel.MAJOR,
    )
    try:
        apply_patch(env, patch)
    except PatchApplyError as e:
        assert "major" in str(e).lower() or "cross_scene" in str(e).lower()
        return
    raise AssertionError("expected PatchApplyError")


def test_apply_rejects_cross_scene_level():
    env = _envelope()
    patch = _patch(
        [{"op": "set", "path": "identity.display_name", "value": "v2"}],
        level=IterationLevel.CROSS_SCENE,
    )
    try:
        apply_patch(env, patch)
    except PatchApplyError:
        return
    raise AssertionError("expected PatchApplyError")


def test_apply_accepts_minor_level():
    env = _envelope()
    patch = _patch(
        [{"op": "set", "path": "identity.display_name", "value": "v2"}],
        level=IterationLevel.MINOR,
    )
    out = apply_patch(env, patch)
    assert out["identity"]["display_name"] == "v2"


# ══════════════════════════════════════════════════════════════
# 序列化 roundtrip
# ══════════════════════════════════════════════════════════════

def test_spec_patch_dict_roundtrip():
    p = _patch([
        {"op": "set", "path": "x.y", "value": 1},
        {"op": "add", "path": "arr", "value": "a"},
        {"op": "remove", "path": "z"},
    ])
    out = SpecPatch.from_dict(p.to_dict())
    assert out.base_spec_id == p.base_spec_id
    assert out.iteration_level == p.iteration_level
    assert len(out.operations) == 3
    assert out.operations[0].value == 1
    assert out.operations[2].op == "remove"


def test_patchop_unknown_op_rejected():
    try:
        PatchOp.from_dict({"op": "replace", "path": "x"})
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_patchop_remove_to_dict_omits_value():
    op = PatchOp(op="remove", path="x")
    d = op.to_dict()
    assert "value" not in d


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
