"""Spec 业务规则校验 — Pydantic schema 之外的交叉字段规则。

Pydantic 负责：单字段类型 / 正则 / 长度 / 枚举。
validators 负责：多字段一致性、场景特定要求、Registry 对齐等。

用法：

    from app.spec.schema import Spec
    from app.spec.validators import validate_spec, SpecValidationError

    try:
        validate_spec(spec_envelope)
    except SpecValidationError as e:
        # e.errors: list[dict]，包含 path / code / message
        ...

错误分级：
- hard errors → BrainstormAgent 必须修复（raise）
- soft warnings → 以 warnings list 返回（供前端展示 hint）
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.spec.schema import (
    BackendApiSpecEnvelope,
    BackendFeignSpecEnvelope,
    BackendScheduledSpecEnvelope,
    ComponentSpec,
    ComponentSpecEnvelope,
    MobilePageSpecEnvelope,
    PageSpec,
    SceneType,
    Spec,
    WebPageSpecEnvelope,
)
from app.spec.ui_editor_registry import is_builtin_editor
from app.spec.ui_section_registry import is_builtin_section


# ══════════════════════════════════════════════════════════════
# 错误模型
# ══════════════════════════════════════════════════════════════

@dataclass
class SpecError:
    """一条业务规则违规"""
    path: str               # JSON-pointer-ish 路径，如 "identity.widget_code"
    code: str               # 错误码，便于前端国际化/条件展示
    message: str            # 人读文案（中文）


@dataclass
class SpecValidationResult:
    """校验结果聚合"""
    errors: list[SpecError] = field(default_factory=list)
    warnings: list[SpecError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def raise_if_invalid(self) -> None:
        if self.errors:
            raise SpecValidationError(self.errors)


class SpecValidationError(ValueError):
    """业务规则校验失败（hard errors 非空）"""

    def __init__(self, errors: list[SpecError]) -> None:
        self.errors = errors
        msg = "; ".join(f"[{e.code}] {e.path}: {e.message}" for e in errors)
        super().__init__(f"Spec validation failed: {msg}")


# ══════════════════════════════════════════════════════════════
# 组件规则
# ══════════════════════════════════════════════════════════════

def _validate_component(envelope: ComponentSpecEnvelope, r: SpecValidationResult) -> None:
    """组件场景（web_component_dual）业务规则"""
    identity = envelope.identity
    spec: ComponentSpec = envelope.spec

    # 1. widget_code 必填
    if not identity.widget_code:
        r.errors.append(SpecError(
            path="identity.widget_code",
            code="COMPONENT_WIDGET_CODE_REQUIRED",
            message="组件场景必须提供 widget_code（FORM_CUSTOM_*）",
        ))

    # 2. code_name 与 widget_code 对齐（建议）
    if identity.widget_code and identity.code_name:
        expected_suffix = identity.code_name.replace("-", "_").upper()
        if not identity.widget_code.endswith(expected_suffix):
            r.warnings.append(SpecError(
                path="identity.widget_code",
                code="COMPONENT_CODE_NAME_MISMATCH",
                message=(
                    f"widget_code={identity.widget_code} 与 code_name={identity.code_name} "
                    f"命名不一致，建议 FORM_CUSTOM_{expected_suffix}"
                ),
            ))

    # 3. ConfigProperty: is_custom_editor 与 registry 对齐
    for i, cp in enumerate(spec.config_properties):
        builtin = is_builtin_editor(cp.ui_editor)
        if builtin and cp.is_custom_editor:
            r.errors.append(SpecError(
                path=f"spec.config_properties[{i}].is_custom_editor",
                code="EDITOR_MARKED_CUSTOM_BUT_BUILTIN",
                message=(
                    f"ui_editor={cp.ui_editor} 属于预置 editor，"
                    "is_custom_editor 应为 false（否则会让 CodingAgent 重复生成）"
                ),
            ))
        if not builtin and not cp.is_custom_editor:
            r.errors.append(SpecError(
                path=f"spec.config_properties[{i}].is_custom_editor",
                code="EDITOR_NOT_BUILTIN_BUT_MARKED_BUILTIN",
                message=(
                    f"ui_editor={cp.ui_editor} 不在预置 editor 清单中，"
                    "is_custom_editor 必须为 true，否则 CodingAgent 会找不到组件"
                ),
            ))

        # 4. type=select 类下拉应提供 options
        if cp.ui_editor == "form-custom-select-editor" and not cp.options:
            r.warnings.append(SpecError(
                path=f"spec.config_properties[{i}].options",
                code="SELECT_EDITOR_MISSING_OPTIONS",
                message="form-custom-select-editor 通常需要配合 options 使用",
            ))

        # 5. required=true 时 default 不应为 None/""
        if cp.required and (cp.default is None or cp.default == ""):
            r.warnings.append(SpecError(
                path=f"spec.config_properties[{i}].default",
                code="REQUIRED_WITHOUT_DEFAULT",
                message=f"配置项 {cp.key} required=true 但未提供有意义的 default",
            ))

    # 6. scenes_required / scenes_optional 不允许重叠
    overlap = set(spec.scenes_required) & set(spec.scenes_optional)
    if overlap:
        r.errors.append(SpecError(
            path="spec.scenes_optional",
            code="SCENES_REQUIRED_OPTIONAL_OVERLAP",
            message=f"scenes_required 和 scenes_optional 不应重叠：{sorted(s.value for s in overlap)}",
        ))

    # 7. platform_hooks.search_enabled=true → scenes 应含 search / search-ide
    if spec.platform_hooks.search_enabled:
        all_scenes = set(spec.scenes_required) | set(spec.scenes_optional)
        from app.spec.schema import WidgetScene
        if WidgetScene.SEARCH not in all_scenes and WidgetScene.SEARCH_IDE not in all_scenes:
            r.warnings.append(SpecError(
                path="spec.platform_hooks.search_enabled",
                code="SEARCH_ENABLED_BUT_NO_SEARCH_SCENE",
                message="platform_hooks.search_enabled=true 但 scenes 未包含 search / search-ide",
            ))


# ══════════════════════════════════════════════════════════════
# 页面规则
# ══════════════════════════════════════════════════════════════

def _validate_page(
    envelope: WebPageSpecEnvelope | MobilePageSpecEnvelope,
    r: SpecValidationResult,
) -> None:
    spec: PageSpec = envelope.spec

    # 1. UISection.is_custom_type 与 registry 对齐
    for i, sec in enumerate(spec.ui_sections):
        builtin = is_builtin_section(sec.type)
        if builtin and sec.is_custom_type:
            r.errors.append(SpecError(
                path=f"spec.ui_sections[{i}].is_custom_type",
                code="SECTION_MARKED_CUSTOM_BUT_BUILTIN",
                message=(
                    f"section type={sec.type} 属于预置清单，is_custom_type 应为 false"
                ),
            ))
        if not builtin and not sec.is_custom_type:
            r.errors.append(SpecError(
                path=f"spec.ui_sections[{i}].is_custom_type",
                code="SECTION_NOT_BUILTIN_BUT_MARKED_BUILTIN",
                message=(
                    f"section type={sec.type} 不在预置清单中，"
                    "is_custom_type 必须为 true，否则 CodingAgent 不知道如何渲染"
                ),
            ))

    # 2. type=api 的 DataSource 必须有 endpoint
    for i, ds in enumerate(spec.data_sources):
        if ds.type == "api" and not ds.endpoint:
            r.errors.append(SpecError(
                path=f"spec.data_sources[{i}].endpoint",
                code="DATA_SOURCE_API_MISSING_ENDPOINT",
                message=f"data_source[{ds.name}] type=api 时必须提供 endpoint",
            ))
        if ds.type == "api" and not ds.method:
            r.warnings.append(SpecError(
                path=f"spec.data_sources[{i}].method",
                code="DATA_SOURCE_API_MISSING_METHOD",
                message=f"data_source[{ds.name}] type=api 时建议明确 method，默认按 GET 处理",
            ))


# ══════════════════════════════════════════════════════════════
# 后端规则
# ══════════════════════════════════════════════════════════════

def _validate_backend(
    envelope: BackendApiSpecEnvelope | BackendFeignSpecEnvelope | BackendScheduledSpecEnvelope,
    r: SpecValidationResult,
) -> None:
    spec = envelope.spec

    # 1. endpoints path 不能重复（method + path 组合）
    seen: set[tuple[str, str]] = set()
    for i, ep in enumerate(spec.endpoints):
        key = (ep.method, ep.path)
        if key in seen:
            r.errors.append(SpecError(
                path=f"spec.endpoints[{i}]",
                code="ENDPOINT_DUPLICATE",
                message=f"接口重复：{ep.method} {ep.path}",
            ))
        seen.add(key)

    # 2. mpaas_tables 访问权限与 endpoints 是否协调（仅 warning）
    has_write_endpoint = any(ep.method in ("POST", "PUT", "DELETE") for ep in spec.endpoints)
    if has_write_endpoint and spec.mpaas_tables:
        any_write = any(t.access in ("write", "readwrite") for t in spec.mpaas_tables)
        if not any_write:
            r.warnings.append(SpecError(
                path="spec.mpaas_tables",
                code="WRITE_ENDPOINT_WITHOUT_WRITE_TABLE",
                message="存在写接口（POST/PUT/DELETE）但未声明任何 write/readwrite 表",
            ))

    # 3. scheduled 场景：至少一个 endpoint 语义上应是任务入口（仅 warning）
    if envelope.scene_type == SceneType.BACKEND_SCHEDULED and not spec.endpoints:
        r.errors.append(SpecError(
            path="spec.endpoints",
            code="SCHEDULED_NEEDS_TRIGGER",
            message="backend_scheduled 场景至少需要 1 个 endpoint 作为任务触发入口",
        ))


# ══════════════════════════════════════════════════════════════
# 通用规则（provenance / intent）
# ══════════════════════════════════════════════════════════════

def _validate_common(envelope: Spec, r: SpecValidationResult) -> None:
    # 1. version > 1 时必须有 parent_version
    if envelope.provenance.version > 1 and envelope.provenance.parent_version is None:
        r.errors.append(SpecError(
            path="provenance.parent_version",
            code="VERSION_CHAIN_BROKEN",
            message=f"version={envelope.provenance.version} > 1 必须提供 parent_version",
        ))

    # 2. parent_version 若存在必须小于 version
    if (
        envelope.provenance.parent_version is not None
        and envelope.provenance.parent_version >= envelope.provenance.version
    ):
        r.errors.append(SpecError(
            path="provenance.parent_version",
            code="PARENT_VERSION_INVALID",
            message=(
                f"parent_version={envelope.provenance.parent_version} 应小于 "
                f"version={envelope.provenance.version}"
            ),
        ))

    # 3. confidence 与 open_questions 一致性（soft）
    if envelope.provenance.confidence >= 0.9 and envelope.provenance.open_questions:
        r.warnings.append(SpecError(
            path="provenance.confidence",
            code="HIGH_CONFIDENCE_WITH_OPEN_QUESTIONS",
            message="confidence >= 0.9 但仍有未消解的 open_questions，建议降低置信度或先反问",
        ))

    # 4. acceptance_criteria 每条应 >= 5 字符（soft — 防止 LLM 偷懒只写"能用"）
    for i, ac in enumerate(envelope.intent.acceptance_criteria):
        if len(ac.strip()) < 5:
            r.warnings.append(SpecError(
                path=f"intent.acceptance_criteria[{i}]",
                code="ACCEPTANCE_CRITERIA_TOO_SHORT",
                message=f"验收点 {i} 过于简短：{ac!r}，建议补充可验证的细节",
            ))


# ══════════════════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════════════════

def validate_spec(envelope: Spec) -> SpecValidationResult:
    """校验一个 Spec envelope，返回 errors + warnings。

    调用方负责决定如何处理：
    - BrainstormAgent 自我校验时：errors 非空 → 再跑一轮反问 / 重新 emit
    - API 层确认 Spec 时：errors 非空 → 拒绝确认，返给前端
    - CodingAgent 消费前：errors 非空 → 拒绝执行（不应该发生，除非 schema 绕过）
    """
    r = SpecValidationResult()
    _validate_common(envelope, r)

    if isinstance(envelope, ComponentSpecEnvelope):
        _validate_component(envelope, r)
    elif isinstance(envelope, (WebPageSpecEnvelope, MobilePageSpecEnvelope)):
        _validate_page(envelope, r)
    elif isinstance(envelope, (BackendApiSpecEnvelope, BackendFeignSpecEnvelope, BackendScheduledSpecEnvelope)):
        _validate_backend(envelope, r)
    # 新场景自行扩展 elif 分支

    return r
