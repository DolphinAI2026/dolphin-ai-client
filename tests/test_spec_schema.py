"""Spec 1.0 单元测试 — schema + 预置 registry + validators。

覆盖：
- Pydantic 强类型字段校验（正则 / 必填 / 值域）
- discriminated union 正反序列化
- ui_editor / ui_section registry 查询
- validators 业务规则（hard errors vs soft warnings）
"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from contextlib import contextmanager  # noqa: E402

from pydantic import TypeAdapter, ValidationError  # noqa: E402


# 轻量级 pytest.raises 替代（避免强依赖 pytest）
class _RaisesCtx:
    def __init__(self, exc_type):
        self.exc_type = exc_type
        self.value: Exception | None = None


@contextmanager
def _raises(exc_type):
    ctx = _RaisesCtx(exc_type)
    try:
        yield ctx
    except exc_type as e:
        ctx.value = e
        return
    raise AssertionError(f"expected {exc_type.__name__} was not raised")


class _PytestShim:
    raises = staticmethod(_raises)


pytest = _PytestShim()  # type: ignore[assignment]

from app.spec import (  # noqa: E402
    BUILTIN_UI_EDITORS,
    BUILTIN_UI_SECTIONS,
    BackendApiSpec,
    BackendApiSpecEnvelope,
    BofType,
    ComponentDataSpec,
    ComponentModelField,
    ComponentSpec,
    ComponentSpecEnvelope,
    ConfigProperty,
    CreatedBy,
    FormValueShape,
    Identity,
    Intent,
    Metadata,
    PageSpec,
    PlatformHooks,
    Provenance,
    SceneType,
    Spec,
    UISection,
    WebPageSpecEnvelope,
    WidgetScene,
    is_builtin_editor,
    is_builtin_section,
    validate_spec,
)
from app.spec.schema import (  # noqa: E402
    ApiEndpoint,
    DataSource,
    PageRoute,
)
from app.spec.validators import SpecValidationError  # noqa: E402


# ══════════════════════════════════════════════════════════════
# 辅助构造器
# ══════════════════════════════════════════════════════════════

def _provenance(version: int = 1, parent_version: int | None = None, confidence: float = 0.8) -> Provenance:
    return Provenance(
        brainstorm_session_id="bs_1",
        created_at=datetime.now(timezone.utc),
        created_by=CreatedBy.AGENT,
        model="test-model",
        version=version,
        parent_version=parent_version,
        confidence=confidence,
        open_questions=[],
    )


def _identity_component(widget_code: str = "FORM_CUSTOM_RATING_STAR") -> Identity:
    return Identity(
        code_name="rating-star",
        display_name="评分星",
        description_cn="星级评分组件",
        widget_code=widget_code,
    )


def _intent() -> Intent:
    return Intent(
        original_requirement="做个评分组件",
        core_purpose="用户可选 1~5 星打分",
        acceptance_criteria=["支持 1~5 星可选", "主色可配置"],
    )


def _component_spec_minimal(**overrides) -> ComponentSpec:
    kwargs = dict(
        data=ComponentDataSpec(
            bof_type=BofType.BOF_NUMBER,
            component_model_field=[ComponentModelField.NUM],
            form_value_shape=FormValueShape.SCALAR,
            default_value=0,
            storage_note="整数 1~5",
        ),
        config_properties=[],
        scenes_required=[WidgetScene.EDIT, WidgetScene.READ],
        scenes_optional=[],
        platform_hooks=PlatformHooks(),
        third_party_deps=[],
        constraints_hard=[],
        constraints_soft=[],
    )
    kwargs.update(overrides)
    return ComponentSpec(**kwargs)


def _component_envelope(spec: ComponentSpec | None = None, **prov_overrides) -> ComponentSpecEnvelope:
    return ComponentSpecEnvelope(
        spec_id="spec_xxx",
        provenance=_provenance(**prov_overrides),
        identity=_identity_component(),
        intent=_intent(),
        metadata=Metadata(),
        references=[],
        spec=spec or _component_spec_minimal(),
    )


# ══════════════════════════════════════════════════════════════
# Enum / 正则 / 必填
# ══════════════════════════════════════════════════════════════

def test_identity_widget_code_pattern_valid():
    ident = Identity(
        code_name="rating-star",
        display_name="评分",
        description_cn="x",
        widget_code="FORM_CUSTOM_RATING_STAR",
    )
    assert ident.widget_code == "FORM_CUSTOM_RATING_STAR"


def test_identity_widget_code_pattern_invalid():
    with pytest.raises(ValidationError):
        Identity(
            code_name="rating-star",
            display_name="评分",
            description_cn="x",
            widget_code="form_custom_rating",  # 小写非法
        )


def test_identity_code_name_pattern():
    with pytest.raises(ValidationError):
        Identity(
            code_name="RatingStar",  # 大写驼峰非法
            display_name="评分",
            description_cn="x",
        )


def test_config_property_ui_editor_pattern():
    with pytest.raises(ValidationError):
        ConfigProperty(
            key="color",
            type="string",
            label="颜色",
            default="#fff",
            ui_editor="el-color-picker",  # 非 form-custom-* 前缀
        )


def test_config_property_default_is_required():
    """default 没有默认值，必须显式传；这保证 brainstorm 强制做决策"""
    with pytest.raises(ValidationError):
        ConfigProperty(
            key="color",
            type="string",
            label="颜色",
            ui_editor="form-custom-color-editor",
        )


def test_metadata_forbid_extra_top_level():
    """顶层未知字段必须进 extra 口袋，不能直接加到 Metadata 上"""
    with pytest.raises(ValidationError):
        Metadata(foo="bar")  # type: ignore[call-arg]


def test_metadata_extra_pocket_works():
    m = Metadata(extra={"custom_key": "value"})
    assert m.extra["custom_key"] == "value"


def test_confidence_range():
    with pytest.raises(ValidationError):
        _provenance(confidence=1.5)


# ══════════════════════════════════════════════════════════════
# Discriminated union — 序列化 / 反序列化
# ══════════════════════════════════════════════════════════════

def test_discriminated_union_component():
    env = _component_envelope()
    payload = env.model_dump(mode="json")
    assert payload["scene_type"] == "web_component_dual"

    adapter = TypeAdapter(Spec)
    revived = adapter.validate_python(payload)
    assert isinstance(revived, ComponentSpecEnvelope)
    assert revived.identity.code_name == "rating-star"


def test_discriminated_union_web_page():
    env = WebPageSpecEnvelope(
        spec_id="spec_page",
        provenance=_provenance(),
        identity=Identity(code_name="order-list", display_name="订单列表", description_cn="x"),
        intent=_intent(),
        spec=PageSpec(
            route=PageRoute(router_name="apaas-custom-order-list", menu_title="订单"),
            ui_sections=[UISection(name="main", type="table", config={})],
        ),
    )
    payload = env.model_dump(mode="json")
    revived = TypeAdapter(Spec).validate_python(payload)
    assert isinstance(revived, WebPageSpecEnvelope)
    assert revived.spec.route.router_name == "apaas-custom-order-list"


def test_discriminated_union_backend_api():
    env = BackendApiSpecEnvelope(
        spec_id="spec_api",
        provenance=_provenance(),
        identity=Identity(code_name="user-api", display_name="用户接口", description_cn="x"),
        intent=_intent(),
        spec=BackendApiSpec(
            package_name="com.xdap.custom.user",
            endpoints=[ApiEndpoint(path="/custom/user/get", method="GET", description="查询用户")],
        ),
    )
    payload = env.model_dump(mode="json")
    revived = TypeAdapter(Spec).validate_python(payload)
    assert isinstance(revived, BackendApiSpecEnvelope)


def test_union_rejects_wrong_scene_payload():
    """scene_type 与 spec 结构不匹配时应 fail"""
    bad = {
        "schema_version": "1.0",
        "scene_type": "web_component_dual",
        "spec_id": "x",
        "provenance": {
            "brainstorm_session_id": "x",
            "created_at": "2026-04-19T00:00:00+00:00",
            "created_by": "agent",
            "version": 1,
            "confidence": 0.9,
            "open_questions": [],
        },
        "identity": {"code_name": "x", "display_name": "x", "description_cn": "x"},
        "intent": {"original_requirement": "x", "core_purpose": "x", "acceptance_criteria": ["x"]},
        # spec 给的是 page 结构，不匹配 component
        "spec": {"route": {"router_name": "apaas-custom-x", "menu_title": "x"}, "ui_sections": []},
    }
    with pytest.raises(ValidationError):
        TypeAdapter(Spec).validate_python(bad)


# ══════════════════════════════════════════════════════════════
# Registry
# ══════════════════════════════════════════════════════════════

def test_builtin_editor_registry_basic_entries_present():
    """scaffold 默认附带的 4 个 editor 必须存在"""
    for key in (
        "form-custom-input-editor",
        "form-custom-select-editor",
        "form-custom-textarea-editor",
        "form-custom-switch-editor",
    ):
        assert key in BUILTIN_UI_EDITORS, f"缺失预置 editor {key}"
        assert is_builtin_editor(key)
    assert not is_builtin_editor("form-custom-rating-editor")


def test_builtin_editor_keys_match_regex():
    import re
    pat = re.compile(r"^form-custom-[a-z][a-z0-9-]*-editor$")
    for key in BUILTIN_UI_EDITORS:
        assert pat.match(key), f"预置 editor key 不匹配正则: {key}"
        assert BUILTIN_UI_EDITORS[key]["key"] == key


def test_builtin_section_registry_core_entries():
    for key in ("form", "table", "bar_chart", "line_chart"):
        assert key in BUILTIN_UI_SECTIONS
        assert is_builtin_section(key)
    assert not is_builtin_section("gantt_chart")


# ══════════════════════════════════════════════════════════════
# validators — 通用规则
# ══════════════════════════════════════════════════════════════

def test_validator_version_chain_broken():
    env = _component_envelope(version=2, parent_version=None)
    r = validate_spec(env)
    assert not r.ok
    assert any(e.code == "VERSION_CHAIN_BROKEN" for e in r.errors)


def test_validator_parent_version_invalid():
    env = _component_envelope(version=2, parent_version=5)
    r = validate_spec(env)
    assert any(e.code == "PARENT_VERSION_INVALID" for e in r.errors)


def test_validator_high_confidence_with_open_questions():
    prov = _provenance(confidence=0.95)
    prov.open_questions.append(__import__("app.spec", fromlist=["OpenQuestion"]).OpenQuestion(
        question="主色?", assumed_answer="#409EFF"
    ))
    env = _component_envelope()
    env.provenance = prov
    r = validate_spec(env)
    assert any(w.code == "HIGH_CONFIDENCE_WITH_OPEN_QUESTIONS" for w in r.warnings)


def test_validator_acceptance_criteria_too_short():
    env = _component_envelope()
    env.intent.acceptance_criteria = ["ok"]  # 2 字过短
    r = validate_spec(env)
    assert any(w.code == "ACCEPTANCE_CRITERIA_TOO_SHORT" for w in r.warnings)


# ══════════════════════════════════════════════════════════════
# validators — component 规则
# ══════════════════════════════════════════════════════════════

def test_validator_component_widget_code_required():
    env = _component_envelope()
    env.identity = Identity(code_name="x", display_name="x", description_cn="x", widget_code=None)
    r = validate_spec(env)
    assert any(e.code == "COMPONENT_WIDGET_CODE_REQUIRED" for e in r.errors)


def test_validator_component_code_name_mismatch_warning():
    env = _component_envelope()
    # code_name=rating-star 对应 FORM_CUSTOM_RATING_STAR，这里故意不匹配
    env.identity.widget_code = "FORM_CUSTOM_SOMETHING_ELSE"
    r = validate_spec(env)
    assert any(w.code == "COMPONENT_CODE_NAME_MISMATCH" for w in r.warnings)


def test_validator_editor_marked_custom_but_builtin():
    cp = ConfigProperty(
        key="color", type="string", label="颜色", default="#fff",
        ui_editor="form-custom-color-editor",
        is_custom_editor=True,  # 但 color-editor 其实是预置
    )
    spec = _component_spec_minimal(config_properties=[cp])
    env = _component_envelope(spec=spec)
    r = validate_spec(env)
    assert any(e.code == "EDITOR_MARKED_CUSTOM_BUT_BUILTIN" for e in r.errors)


def test_validator_editor_not_builtin_but_marked_builtin():
    cp = ConfigProperty(
        key="rating", type="number", label="评分", default=0,
        ui_editor="form-custom-rating-star-editor",  # 非预置
        is_custom_editor=False,  # 却标了 builtin
    )
    spec = _component_spec_minimal(config_properties=[cp])
    env = _component_envelope(spec=spec)
    r = validate_spec(env)
    assert any(e.code == "EDITOR_NOT_BUILTIN_BUT_MARKED_BUILTIN" for e in r.errors)


def test_validator_select_editor_missing_options_warning():
    cp = ConfigProperty(
        key="size", type="string", label="尺寸", default="medium",
        ui_editor="form-custom-select-editor",  # 预置
        is_custom_editor=False,
        options=None,  # select 缺 options
    )
    spec = _component_spec_minimal(config_properties=[cp])
    env = _component_envelope(spec=spec)
    r = validate_spec(env)
    assert any(w.code == "SELECT_EDITOR_MISSING_OPTIONS" for w in r.warnings)


def test_validator_scenes_required_optional_overlap():
    spec = _component_spec_minimal(
        scenes_required=[WidgetScene.EDIT, WidgetScene.READ],
        scenes_optional=[WidgetScene.READ],  # 重叠
    )
    env = _component_envelope(spec=spec)
    r = validate_spec(env)
    assert any(e.code == "SCENES_REQUIRED_OPTIONAL_OVERLAP" for e in r.errors)


def test_validator_search_enabled_without_search_scene():
    spec = _component_spec_minimal(
        scenes_required=[WidgetScene.EDIT],
        platform_hooks=PlatformHooks(search_enabled=True),
    )
    env = _component_envelope(spec=spec)
    r = validate_spec(env)
    assert any(w.code == "SEARCH_ENABLED_BUT_NO_SEARCH_SCENE" for w in r.warnings)


# ══════════════════════════════════════════════════════════════
# validators — page 规则
# ══════════════════════════════════════════════════════════════

def _page_envelope(spec: PageSpec) -> WebPageSpecEnvelope:
    return WebPageSpecEnvelope(
        spec_id="p1",
        provenance=_provenance(),
        identity=Identity(code_name="page", display_name="页", description_cn="x"),
        intent=_intent(),
        spec=spec,
    )


def test_validator_section_not_builtin_but_marked_builtin():
    spec = PageSpec(
        route=PageRoute(router_name="apaas-custom-page", menu_title="页"),
        ui_sections=[UISection(name="custom", type="gantt_chart", is_custom_type=False)],
    )
    r = validate_spec(_page_envelope(spec))
    assert any(e.code == "SECTION_NOT_BUILTIN_BUT_MARKED_BUILTIN" for e in r.errors)


def test_validator_section_marked_custom_but_builtin():
    spec = PageSpec(
        route=PageRoute(router_name="apaas-custom-page", menu_title="页"),
        ui_sections=[UISection(name="main", type="table", is_custom_type=True)],
    )
    r = validate_spec(_page_envelope(spec))
    assert any(e.code == "SECTION_MARKED_CUSTOM_BUT_BUILTIN" for e in r.errors)


def test_validator_data_source_api_missing_endpoint():
    spec = PageSpec(
        route=PageRoute(router_name="apaas-custom-page", menu_title="页"),
        ui_sections=[UISection(name="main", type="table", config={})],
        data_sources=[DataSource(name="users", type="api", endpoint=None, method="GET")],
    )
    r = validate_spec(_page_envelope(spec))
    assert any(e.code == "DATA_SOURCE_API_MISSING_ENDPOINT" for e in r.errors)


# ══════════════════════════════════════════════════════════════
# validators — backend 规则
# ══════════════════════════════════════════════════════════════

def test_validator_endpoint_duplicate():
    spec = BackendApiSpec(
        package_name="com.xdap.custom.order",
        endpoints=[
            ApiEndpoint(path="/custom/order/get", method="GET", description="查"),
            ApiEndpoint(path="/custom/order/get", method="GET", description="重复"),
        ],
    )
    env = BackendApiSpecEnvelope(
        spec_id="b1",
        provenance=_provenance(),
        identity=Identity(code_name="order-api", display_name="订单", description_cn="x"),
        intent=_intent(),
        spec=spec,
    )
    r = validate_spec(env)
    assert any(e.code == "ENDPOINT_DUPLICATE" for e in r.errors)


def test_validator_write_endpoint_without_write_table_warning():
    from app.spec.schema import MpaasTable
    spec = BackendApiSpec(
        package_name="com.xdap.custom.order",
        endpoints=[
            ApiEndpoint(path="/custom/order/create", method="POST", description="创建"),
        ],
        mpaas_tables=[MpaasTable(name="t_order", access="read")],
    )
    env = BackendApiSpecEnvelope(
        spec_id="b1",
        provenance=_provenance(),
        identity=Identity(code_name="order-api", display_name="订单", description_cn="x"),
        intent=_intent(),
        spec=spec,
    )
    r = validate_spec(env)
    assert any(w.code == "WRITE_ENDPOINT_WITHOUT_WRITE_TABLE" for w in r.warnings)


# ══════════════════════════════════════════════════════════════
# Happy path + raise_if_invalid
# ══════════════════════════════════════════════════════════════

def test_validator_happy_path_component():
    cp = ConfigProperty(
        key="primaryColor", type="string", label="主色", default="#409EFF",
        ui_editor="form-custom-color-editor",
        is_custom_editor=False,
    )
    spec = _component_spec_minimal(config_properties=[cp])
    env = _component_envelope(spec=spec)
    r = validate_spec(env)
    assert r.ok, f"expected no errors but got {r.errors}"


def test_validation_result_raise_if_invalid():
    env = _component_envelope(version=2, parent_version=None)
    r = validate_spec(env)
    with pytest.raises(SpecValidationError) as exc:
        r.raise_if_invalid()
    assert "VERSION_CHAIN_BROKEN" in str(exc.value)


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
