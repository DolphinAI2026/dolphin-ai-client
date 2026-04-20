"""Spec 契约模块 — BrainstormAgent 与 CodingAgent 之间的结构化契约定义。

见 docs/internal/INTELLIGENT_DEV_AGENT_ARCHITECTURE_V1_2026-04-19.md § 3。

子模块：
- schema.py：Pydantic 模型（Spec Envelope + ComponentSpec/PageSpec/BackendApiSpec）
- ui_editor_registry.py：预置 UI Editor 清单 + LLM prompt 片段
- ui_section_registry.py：预置 UI Section 清单 + LLM prompt 片段
- validators.py：Pydantic 之外的业务规则校验（如 widget_code 必填、is_custom_editor 一致性）
"""

from app.spec.schema import (
    BackendApiSpec,
    BackendApiSpecEnvelope,
    BackendFeignSpecEnvelope,
    BackendScheduledSpecEnvelope,
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
    MobilePageSpecEnvelope,
    OpenQuestion,
    PageSpec,
    PlatformHooks,
    Provenance,
    SceneType,
    Spec,
    SpecReference,
    SpecRelation,
    UISection,
    WebPageSpecEnvelope,
    WidgetScene,
)
from app.spec.ui_editor_registry import (
    BUILTIN_UI_EDITORS,
    EDITOR_PROMPT_SECTION,
    is_builtin_editor,
)
from app.spec.ui_section_registry import (
    BUILTIN_UI_SECTIONS,
    SECTION_PROMPT_SECTION,
    is_builtin_section,
)
from app.spec.validators import (
    SpecError,
    SpecValidationError,
    SpecValidationResult,
    validate_spec,
)

__all__ = [
    # 枚举
    "SceneType",
    "BofType",
    "ComponentModelField",
    "FormValueShape",
    "WidgetScene",
    "CreatedBy",
    "SpecRelation",
    # 通用子结构
    "OpenQuestion",
    "Provenance",
    "Identity",
    "Intent",
    "Metadata",
    "SpecReference",
    # ComponentSpec
    "ComponentDataSpec",
    "ConfigProperty",
    "PlatformHooks",
    "ComponentSpec",
    # PageSpec / BackendApiSpec
    "PageSpec",
    "UISection",
    "BackendApiSpec",
    # Envelopes + 顶层 Union
    "ComponentSpecEnvelope",
    "WebPageSpecEnvelope",
    "MobilePageSpecEnvelope",
    "BackendApiSpecEnvelope",
    "BackendFeignSpecEnvelope",
    "BackendScheduledSpecEnvelope",
    "Spec",
    # Registries
    "BUILTIN_UI_EDITORS",
    "EDITOR_PROMPT_SECTION",
    "is_builtin_editor",
    "BUILTIN_UI_SECTIONS",
    "SECTION_PROMPT_SECTION",
    "is_builtin_section",
    # Validators
    "SpecError",
    "SpecValidationError",
    "SpecValidationResult",
    "validate_spec",
]
