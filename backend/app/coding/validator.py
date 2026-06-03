"""
代码校验器 - 验证生成的代码是否符合aPaaS平台规范
"""

import re
import json
from typing import List, Optional, Any, TYPE_CHECKING

from pydantic import BaseModel, field_validator, model_validator
from app.coding.form_component_editor import validate_setting_component_contract


# ---------------------------------------------------------------------------
# Pydantic models for widget.config.json validation
# ---------------------------------------------------------------------------

class _WidgetDesc(BaseModel):
    iconType: str
    icon: str
    text: str
    description: str

    @field_validator("text")
    @classmethod
    def text_must_not_be_placeholder(cls, v: str) -> str:
        if "demo" in v.lower():
            raise ValueError(f"desc.text 不能使用占位值（含 demo），请填写真实组件名称，当前为 \"{v}\"")
        return v

    @field_validator("iconType")
    @classmethod
    def icon_type_must_be_default(cls, v: str) -> str:
        if v != "DEFAULT":
            raise ValueError("desc.iconType 必须为 \"DEFAULT\"")
        return v

    @field_validator("icon")
    @classmethod
    def icon_must_be_svg(cls, v: str) -> str:
        if not v.strip().startswith("<svg"):
            raise ValueError("desc.icon 必须是 SVG 字符串（以 <svg 开头），不能使用图标类名")
        return v


class _WidgetInstance(BaseModel):
    uuid: str
    inTable: bool


class _WidgetDisplay(BaseModel):
    label: str
    width: int
    mobileWidth: int
    height: int
    hidden: bool
    readOnly: bool
    required: bool
    onlyCreateEdit: bool

    @field_validator("width")
    @classmethod
    def width_must_be_valid(cls, v: int) -> int:
        if v not in (3, 6, 12):
            raise ValueError(f"widget.display.width 只能是 3/6/12，当前为 {v}")
        return v

    @field_validator("mobileWidth")
    @classmethod
    def mobile_width_must_be_valid(cls, v: int) -> int:
        if v not in (6, 12):
            raise ValueError(f"widget.display.mobileWidth 只能是 6/12，当前为 {v}")
        return v


class _WidgetAllow(BaseModel):
    calcRule: bool
    useInTableColumn: bool
    scanCode: bool
    copy: bool


class _WidgetDefault(BaseModel):
    customDefaultKey: str
    value: Any

    @field_validator("value", mode="before")
    @classmethod
    def value_must_be_null(cls, v: Any) -> Any:
        if v is not None:
            raise ValueError(f"widget.default.value 必须为 null，当前为 {repr(v)}")
        return v


class _WidgetValidator(BaseModel):
    uniqueCheck: bool


class _WidgetSpecial(BaseModel):
    frontBusinessObjectComponentType: str

    @field_validator("frontBusinessObjectComponentType")
    @classmethod
    def bof_type_must_be_valid(cls, v: str) -> str:
        if v not in ("BOF_TEXT", "BOF_NUMBER", "BOF_DATE"):
            raise ValueError(f"frontBusinessObjectComponentType 只能是 BOF_TEXT/BOF_NUMBER/BOF_DATE，当前为 {v}")
        return v


class _WidgetEditor(BaseModel):
    config: List[str]
    excludeInTable: List[str]

    @field_validator("config", mode="before")
    @classmethod
    def _flatten_config(cls, v: object) -> list[str]:
        """将二维数组展平为一维字符串数组，过滤非字符串元素。"""
        if not isinstance(v, list):
            return []
        flat: list[str] = []
        for item in v:
            if isinstance(item, list):
                flat.extend(x for x in item if isinstance(x, str))
            elif isinstance(item, str):
                flat.append(item)
        return flat


class _Widget(BaseModel):
    display: _WidgetDisplay
    allow: _WidgetAllow
    default: _WidgetDefault
    validator: _WidgetValidator
    special: _WidgetSpecial
    editor: _WidgetEditor


class _PCComponent(BaseModel):
    ide: str
    edit: str
    read: str
    list: Optional[str] = None
    association: Optional[str] = None
    lov: Optional[str] = None
    print: Optional[str] = None
    search: Optional[str] = None
    searchIde: Optional[str] = None


class _MobileComponent(BaseModel):
    ide: str
    edit: str
    read: str
    list: Optional[str] = None
    association: Optional[str] = None
    lov: Optional[str] = None
    tableColumn: Optional[str] = None


class _MobileEditor(BaseModel):
    config: List[str]
    excludeInTable: List[str]

    @field_validator("config", mode="before")
    @classmethod
    def _flatten_config(cls, v: object) -> list[str]:
        """将二维数组展平为一维字符串数组，过滤非字符串元素。"""
        if not isinstance(v, list):
            return []
        flat: list[str] = []
        for item in v:
            if isinstance(item, list):
                flat.extend(x for x in item if isinstance(x, str))
            elif isinstance(item, str):
                flat.append(item)
        return flat


class _MobileWidget(BaseModel):
    editor: _MobileEditor


class _MobileClient(BaseModel):
    widget: _MobileWidget
    component: _MobileComponent


class _ClientConfig(BaseModel):
    mobile: _MobileClient


class WidgetComponentConfig(BaseModel):
    version: float
    code: str
    desc: _WidgetDesc
    instance: _WidgetInstance
    component: _PCComponent
    widget: _Widget
    client: _ClientConfig
    componentModelField: List[str]
    methods: dict
    formatValueSchema: dict

    @field_validator("code")
    @classmethod
    def code_must_start_with_form_custom(cls, v: str) -> str:
        if not v.startswith("FORM_CUSTOM_"):
            raise ValueError(f"code 必须以 FORM_CUSTOM_ 开头，当前为 \"{v}\"")
        return v

    @field_validator("componentModelField")
    @classmethod
    def component_model_field_must_be_valid(cls, v: List[str]) -> List[str]:
        valid = {"STRING", "NUM", "DATE", "BIG_TEXT"}
        for field in v:
            if field not in valid:
                raise ValueError(f"componentModelField 只能是 STRING/NUM/DATE/BIG_TEXT，当前含 \"{field}\"")
        return v

    @model_validator(mode="after")
    def bof_type_matches_component_model_field(self) -> "WidgetComponentConfig":
        mapping = {"STRING": "BOF_TEXT", "BIG_TEXT": "BOF_TEXT", "NUM": "BOF_NUMBER", "DATE": "BOF_DATE"}
        for cmf in self.componentModelField:
            expected = mapping.get(cmf)
            actual = self.widget.special.frontBusinessObjectComponentType
            if expected and actual != expected:
                raise ValueError(
                    f"componentModelField={cmf} 时 frontBusinessObjectComponentType 应为 {expected}，当前为 {actual}"
                )
        return self

def _flatten_str_list(v: object) -> list[str]:
    """将可能的二维字符串数组展平为一维，过滤非字符串元素。"""
    if not isinstance(v, list):
        return []
    flat: list[str] = []
    for item in v:
        if isinstance(item, list):
            flat.extend(x for x in item if isinstance(x, str))
        elif isinstance(item, str):
            flat.append(item)
    return flat


def normalize_widget_config_with_pydantic(data: dict) -> dict:
    """对 widget.config.json 结构进行 coerce 归一化（类型修正、默认值填充）。

    不抛出异常，始终返回修正后的 dict。
    """
    result = dict(data)

    # methods / formatValueSchema: list → dict
    if isinstance(result.get("methods"), list):
        result["methods"] = {}
    if isinstance(result.get("formatValueSchema"), list):
        result["formatValueSchema"] = {}

    # desc.iconType 强制为 "DEFAULT"
    if isinstance(result.get("desc"), dict):
        result["desc"] = dict(result["desc"])
        result["desc"]["iconType"] = "DEFAULT"

    # widget.editor 确保存在且 excludeInTable 为 list，config 展平为一维字符串数组
    widget = result.get("widget")
    if isinstance(widget, dict):
        result["widget"] = dict(widget)
        editor = result["widget"].get("editor")
        if not isinstance(editor, dict):
            result["widget"]["editor"] = {"config": [], "excludeInTable": ["WIDTH"]}
        else:
            result["widget"]["editor"] = dict(editor)
            if not isinstance(result["widget"]["editor"].get("excludeInTable"), list):
                result["widget"]["editor"]["excludeInTable"] = ["WIDTH"]
            # 展平 config 二维数组
            result["widget"]["editor"]["config"] = _flatten_str_list(
                result["widget"]["editor"].get("config")
            )

    # client.mobile.widget.editor.config 同样展平
    try:
        mobile_widget = result.get("client", {}).get("mobile", {}).get("widget")
        if isinstance(mobile_widget, dict):
            mobile_editor = mobile_widget.get("editor")
            if isinstance(mobile_editor, dict):
                mobile_editor["config"] = _flatten_str_list(mobile_editor.get("config"))
    except Exception:
        pass

    return result


if TYPE_CHECKING:
    from app.coding.generator import GeneratedFile
    from app.coding.scenes import SceneInfo


SUPPORTED_COMPONENT_MODEL_FIELDS = {"STRING", "NUM", "DATE", "BIG_TEXT"}
COMPONENT_MODEL_FIELD_TO_BOF_TYPE = {
    "STRING": "BOF_TEXT",
    "NUM": "BOF_NUMBER",
    "DATE": "BOF_DATE",
    "BIG_TEXT": "BOF_TEXT",
}


