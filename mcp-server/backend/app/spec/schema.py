"""Spec 1.0 契约 — Pydantic 模型定义。

Brainstorm Agent 产出、Coding Agent 消费的结构化契约。详见：
  docs/internal/INTELLIGENT_DEV_AGENT_ARCHITECTURE_V1_2026-04-19.md § 3

顶层结构：schema_version / spec_id / scene_type(discriminator) /
          provenance / identity / intent / spec / metadata / references
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


# ══════════════════════════════════════════════════════════════
# 枚举
# ══════════════════════════════════════════════════════════════

class SceneType(str, Enum):
    """Spec 1.0 覆盖的场景类型"""
    WEB_COMPONENT_DUAL = "web_component_dual"
    WEB_PAGE = "web_page"
    MOBILE_PAGE = "mobile_page"
    BACKEND_API = "backend_api"
    BACKEND_FEIGN = "backend_feign"
    BACKEND_SCHEDULED = "backend_scheduled"
    # 预留扩展：web_list_view / web_layout / web_login / web_plugin
    # 届时只需新增枚举值 + 对应 Spec + Envelope 类，不破坏现有 schema


class BofType(str, Enum):
    """aPaaS 平台字段类型（组件场景）"""
    BOF_TEXT = "BOF_TEXT"
    BOF_NUMBER = "BOF_NUMBER"
    BOF_DATE = "BOF_DATE"


class ComponentModelField(str, Enum):
    """平台存储字段类型"""
    STRING = "STRING"
    NUM = "NUM"
    DATE = "DATE"
    BIG_TEXT = "BIG_TEXT"


class FormValueShape(str, Enum):
    """formValue 形态 — 影响 edit.vue 的数据绑定方式"""
    SCALAR = "scalar"   # 单值
    RANGE = "range"     # 范围 {start, end}
    ARRAY = "array"     # 多值


class WidgetScene(str, Enum):
    """form-component 的 7 个渲染场景"""
    EDIT = "edit"
    READ = "read"
    IDE = "ide"
    LIST = "list"
    PRINT = "print"
    SEARCH = "search"
    SEARCH_IDE = "search-ide"


class CreatedBy(str, Enum):
    """Spec 版本的产出方"""
    AGENT = "agent"      # BrainstormAgent 产出
    USER = "user"        # 用户在编辑器改出来的
    MIXED = "mixed"      # 用户在 agent 基础上改了一点


class SpecRelation(str, Enum):
    """Spec 间关联类型（1.0 最小集合）"""
    DEPENDS_ON = "depends_on"   # 硬依赖，被关联方必须先存在/先完成
    RELATED = "related"         # 软关联，同批次同业务域但无依赖


# ══════════════════════════════════════════════════════════════
# 通用子结构
# ══════════════════════════════════════════════════════════════

class OpenQuestion(BaseModel):
    """BrainstormAgent 未消解的模糊点 + 做的默认假设"""
    question: str = Field(..., description="原始模糊点")
    assumed_answer: str = Field(..., description="agent 做的默认决策")


class Provenance(BaseModel):
    """Spec 版本来源信息（谁产出的 / 版本号 / 置信度 / 默认假设）"""
    brainstorm_session_id: str
    created_at: datetime
    created_by: CreatedBy
    model: Optional[str] = Field(
        None,
        description="产出该版本的 LLM 模型名。user 版本为 None",
    )
    version: int = Field(1, ge=1, description="Spec 实例版本号（v1, v2, ...）")
    parent_version: Optional[int] = Field(
        None,
        description="从哪个版本派生（形成版本链）",
    )
    confidence: float = Field(..., ge=0.0, le=1.0, description="方案置信度 0-1")
    open_questions: list[OpenQuestion] = Field(default_factory=list)


class Identity(BaseModel):
    """规范化标识 — code / name / display"""
    code_name: str = Field(
        ...,
        pattern=r"^[a-z][a-z0-9-]*$",
        description="kebab-case 英文名，用于文件名、包名",
    )
    display_name: str = Field(..., description="中文显示名")
    description_cn: str
    widget_code: Optional[str] = Field(
        None,
        pattern=r"^FORM_CUSTOM_[A-Z][A-Z0-9_]*$",
        description="仅组件场景必填；其他场景为 None",
    )


class Intent(BaseModel):
    """用户意图描述 — 原始需求 + 核心目的 + 验收点"""
    original_requirement: str = Field(..., description="用户原话（首轮需求）")
    core_purpose: str = Field(..., description="agent 总结的一句话意图")
    acceptance_criteria: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "验收点。1.0 用字符串数组（简单，足够跑通主链路）；"
            "1.1 会升级为结构化对象（id + description + verifiable_evidence）"
        ),
    )


class Metadata(BaseModel):
    """扩展信息 — 预定义字段强类型，其他走 extra 口袋"""
    attachments: list[str] = Field(
        default_factory=list,
        description="用户上传附件的 URL 列表（图片、文档等）",
    )
    reference_component_ids: list[str] = Field(
        default_factory=list,
        description="brainstorm 阶段参考过的相似组件 spec_id",
    )
    ui_mockup_url: Optional[str] = Field(
        None,
        description="UI 设计稿 URL（如有）",
    )
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "未分类信息。实验性/临时字段放这里，"
            "某个 key 被多 agent 读时再提升为预定义字段（升 schema_version）"
        ),
    )

    model_config = ConfigDict(extra="forbid")  # 强制：未知字段必须走 extra，不能在顶层


class SpecReference(BaseModel):
    """Spec 间关联（多 widget 协同场景）"""
    spec_id: str
    relation: SpecRelation
    note: Optional[str] = None


# ══════════════════════════════════════════════════════════════
# ComponentSpec — scene_type = web_component_dual
# ══════════════════════════════════════════════════════════════

class ComponentDataSpec(BaseModel):
    """组件数据存储规格（BOF 类型 / 值形态 / 存储字段）"""
    bof_type: BofType
    component_model_field: list[ComponentModelField] = Field(..., min_length=1)
    form_value_shape: FormValueShape
    default_value: Any = None
    storage_note: str = Field("", description="存储格式的自然语言说明")


class PropValidation(BaseModel):
    """配置项校验规则（按 prop.type 使用对应字段，其余字段留 None）

    - type="number"  → 填 min / max / step
    - type="string"  → 填 min_length / max_length / pattern
    - type="array"   → 填 min_items / max_items
    - type="boolean" → 通常无需 validation，留 None
    """
    # ── number ──
    min: Optional[float] = Field(None, description="最小值（number 专用）")
    max: Optional[float] = Field(None, description="最大值（number 专用）")
    step: Optional[float] = Field(None, description="步长（number 专用）")
    # ── string ──
    min_length: Optional[int] = Field(None, description="最小长度（string 专用）")
    max_length: Optional[int] = Field(None, description="最大长度（string 专用）")
    pattern: Optional[str] = Field(
        None,
        description="正则表达式字符串（不含 / 围栏），如 '^#[0-9A-Fa-f]{3,6}$'（string 专用）",
    )
    # ── array ──
    min_items: Optional[int] = Field(None, description="最少条目数（array 专用）")
    max_items: Optional[int] = Field(None, description="最多条目数（array 专用）")


class ConfigProperty(BaseModel):
    """setting.vue 里一个配置项的规格"""
    key: str = Field(
        ...,
        pattern=r"^[a-zA-Z][a-zA-Z0-9]*$",
        description="配置项键名（camelCase）",
    )
    type: Literal["string", "number", "boolean", "array", "object"]
    label: str
    default: Any = Field(..., description="必填 — 强制 brainstorm 决策默认值，防漏填")
    required: bool = False

    ui_editor: str = Field(
        ...,
        pattern=r"^form-custom-[a-z][a-z0-9-]*-editor$",
        description=(
            "预置 editor（见 ui_editor_registry.BUILTIN_UI_EDITORS）或自定义 editor；"
            "命名格式必须 form-custom-{semantic}-editor"
        ),
    )
    is_custom_editor: bool = Field(
        default=False,
        description=(
            "True 表示 ui_editor 非预置，CodingAgent 需要生成对应 Vue 组件到 "
            "form-editor/components/{editor_name}.vue"
        ),
    )

    editor_props: dict[str, Any] = Field(
        default_factory=dict,
        description="传给 editor 的额外 props（如 placeholder / activeText）",
    )
    validation: Optional[PropValidation] = Field(
        None,
        description=(
            "校验规则（按 prop.type 填对应字段）。"
            "number → min/max/step；string → min_length/max_length/pattern；"
            "array → min_items/max_items。CodingAgent 读此字段生成 :rules。"
        ),
    )
    description: Optional[str] = None
    options: Optional[list[dict[str, Any]]] = Field(
        None,
        description="select 类型 editor 的选项列表",
    )


class PlatformHooks(BaseModel):
    """平台能力钩子（组件是否支持列表/搜索/打印等场景）"""
    in_table_supported: bool = True
    search_enabled: bool = False
    print_enabled: bool = False


class ComponentSpec(BaseModel):
    """web_component_dual 场景的规格"""
    data: ComponentDataSpec
    config_properties: list[ConfigProperty] = Field(default_factory=list)
    scenes_required: list[WidgetScene] = Field(..., min_length=1)
    scenes_optional: list[WidgetScene] = Field(default_factory=list)
    platform_hooks: PlatformHooks = Field(default_factory=PlatformHooks)
    third_party_deps: list[str] = Field(default_factory=list)
    constraints_hard: list[str] = Field(
        default_factory=list,
        description="硬约束，违反必须 fail（如平台规范）",
    )
    constraints_soft: list[str] = Field(
        default_factory=list,
        description="软约束，违反仅 warning（如最佳实践）",
    )


# ══════════════════════════════════════════════════════════════
# PageSpec — scene_type = web_page / mobile_page
# ══════════════════════════════════════════════════════════════

class PageRoute(BaseModel):
    """页面路由配置"""
    router_name: str = Field(..., pattern=r"^apaas-custom-[a-z0-9-]+$")
    menu_title: str


class DataSource(BaseModel):
    """页面数据源定义"""
    name: str
    type: Literal["api", "static", "mock"]
    endpoint: Optional[str] = None
    method: Optional[Literal["GET", "POST", "PUT", "DELETE"]] = None
    params_schema: dict[str, Any] = Field(default_factory=dict)


class UISection(BaseModel):
    """页面 UI 区块（允许自定义 type，见 ui_section_registry 推荐清单）"""
    name: str
    type: str = Field(
        ...,
        description=(
            "区块类型。推荐用 BUILTIN_UI_SECTIONS 里的值"
            "（form/table/card_group/bar_chart 等）；可自定义"
        ),
    )
    is_custom_type: bool = Field(
        default=False,
        description="True 表示非预置 type，CodingAgent 需自行选库实现",
    )
    config: dict[str, Any] = Field(default_factory=dict)


class PageSpec(BaseModel):
    """web_page / mobile_page 场景的规格"""
    route: PageRoute
    layout: Literal["standard", "fullscreen", "sidebar"] = "standard"
    data_sources: list[DataSource] = Field(default_factory=list)
    ui_sections: list[UISection] = Field(..., min_length=1)
    third_party_deps: list[str] = Field(default_factory=list)
    constraints_hard: list[str] = Field(default_factory=list)
    constraints_soft: list[str] = Field(default_factory=list)


# ══════════════════════════════════════════════════════════════
# BackendApiSpec — backend_api / backend_feign / backend_scheduled
# ══════════════════════════════════════════════════════════════

class ApiParam(BaseModel):
    """接口参数定义"""
    type: Literal["string", "number", "boolean", "array", "object"]
    required: bool = False
    description: Optional[str] = None


class ApiEndpoint(BaseModel):
    """单个接口定义"""
    path: str = Field(..., pattern=r"^/custom/")
    method: Literal["GET", "POST", "PUT", "DELETE"]
    description: str
    request: dict[str, ApiParam] = Field(default_factory=dict)
    response: dict[str, Any] = Field(default_factory=dict)


class MpaasTable(BaseModel):
    """MpaaS 数据库表使用声明"""
    name: str
    access: Literal["read", "write", "readwrite"] = "read"


class BackendApiSpec(BaseModel):
    """backend_api / backend_feign / backend_scheduled 场景的规格

    三者共用一套 schema（结构类似，都是 Java 接口 + DTO）。未来需要分化时可拆。
    """
    package_name: str = Field(..., pattern=r"^com\.xdap(\.[a-z][a-z0-9_]*)+$")
    endpoints: list[ApiEndpoint] = Field(..., min_length=1)
    mpaas_tables: list[MpaasTable] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    third_party_deps: list[str] = Field(default_factory=list)
    constraints_hard: list[str] = Field(default_factory=list)
    constraints_soft: list[str] = Field(default_factory=list)


# ══════════════════════════════════════════════════════════════
# 顶层 Envelope + 联合类型（discriminated union）
# ══════════════════════════════════════════════════════════════

class BaseSpecEnvelope(BaseModel):
    """所有场景 Spec 的公共头部字段"""
    schema_version: Literal["1.0"] = "1.0"
    spec_id: str
    provenance: Provenance
    identity: Identity
    intent: Intent
    metadata: Metadata = Field(default_factory=Metadata)
    references: list[SpecReference] = Field(
        default_factory=list,
        description="关联的其他 Spec ID（多 widget 协同场景）",
    )


class ComponentSpecEnvelope(BaseSpecEnvelope):
    scene_type: Literal[SceneType.WEB_COMPONENT_DUAL] = SceneType.WEB_COMPONENT_DUAL
    spec: ComponentSpec


class WebPageSpecEnvelope(BaseSpecEnvelope):
    scene_type: Literal[SceneType.WEB_PAGE] = SceneType.WEB_PAGE
    spec: PageSpec


class MobilePageSpecEnvelope(BaseSpecEnvelope):
    scene_type: Literal[SceneType.MOBILE_PAGE] = SceneType.MOBILE_PAGE
    spec: PageSpec


class BackendApiSpecEnvelope(BaseSpecEnvelope):
    scene_type: Literal[SceneType.BACKEND_API] = SceneType.BACKEND_API
    spec: BackendApiSpec


class BackendFeignSpecEnvelope(BaseSpecEnvelope):
    scene_type: Literal[SceneType.BACKEND_FEIGN] = SceneType.BACKEND_FEIGN
    # feign 调用外部 API，结构类似 backend_api（三者未来可能分化）
    spec: BackendApiSpec


class BackendScheduledSpecEnvelope(BaseSpecEnvelope):
    scene_type: Literal[SceneType.BACKEND_SCHEDULED] = SceneType.BACKEND_SCHEDULED
    spec: BackendApiSpec


# 顶层 Spec：discriminated union（Pydantic 按 scene_type 字段区分）
Spec = Annotated[
    Union[
        ComponentSpecEnvelope,
        WebPageSpecEnvelope,
        MobilePageSpecEnvelope,
        BackendApiSpecEnvelope,
        BackendFeignSpecEnvelope,
        BackendScheduledSpecEnvelope,
    ],
    Field(discriminator="scene_type"),
]
