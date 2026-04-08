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


def validate_generated_code(files: List["GeneratedFile"], scene: "SceneInfo") -> List[str]:
    """校验生成的代码是否符合aPaaS规范"""
    errors = []

    if not files:
        errors.append("未生成任何文件")
        return errors

    # 通用校验
    errors.extend(_validate_naming_convention(files))

    # 按场景校验
    if scene.category == "frontend":
        errors.extend(_validate_frontend(files, scene))
    elif scene.category == "backend":
        errors.extend(_validate_backend(files, scene))

    return errors


def _validate_naming_convention(files: List["GeneratedFile"]) -> List[str]:
    """校验命名规范"""
    errors = []
    for f in files:
        # 检查自开发模块命名
        if "custom/" in f.path and "apaas-custom-" not in f.path:
            if not any(f.path.endswith(ext) for ext in [".java", ".py", ".groovy"]):
                errors.append(f"文件路径 '{f.path}' 中的模块名未以 apaas-custom- 开头")
    return errors


def _validate_frontend(files: List["GeneratedFile"], scene: "SceneInfo") -> List[str]:
    """校验前端代码规范"""
    errors = []
    file_map = {f.path: f for f in files}

    # 检查是否有apaas.json
    apaas_jsons = [f for f in files if f.path.endswith("apaas.json")]
    if scene.platform in ("web", "mobile") and not apaas_jsons:
        # 脚本和样式场景不需要apaas.json
        if scene.type.value not in ("script_js", "business_dialog", "ui_style", "list_custom_module"):
            errors.append("缺少 apaas.json 配置文件")

    # 检查apaas.json内容
    for f in apaas_jsons:
        try:
            config = json.loads(f.content)
            if "entry" not in config:
                errors.append("apaas.json 缺少 entry 字段")
            if "outputName" not in config:
                errors.append("apaas.json 缺少 outputName 字段")
            output_name = config.get("outputName", "")
            if output_name and not output_name.startswith("apaas-custom-"):
                errors.append(f"apaas.json 的 outputName '{output_name}' 未以 apaas-custom- 开头")
        except json.JSONDecodeError:
            errors.append("apaas.json 不是合法的JSON格式")

    # 检查Vue组件中是否使用了FormWidgetConfigMixin（组件场景）
    if "component" in scene.type.value:
        vue_files = [f for f in files if f.path.endswith(".vue")]
        has_mixin = any("FormWidgetConfigMixin" in f.content for f in vue_files)
        if vue_files and not has_mixin:
            errors.append("组件场景下的Vue文件应使用 FormWidgetConfigMixin")

    # 检查index.js入口
    index_files = [f for f in files if f.path.endswith("index.js")]
    for f in index_files:
        if "install" not in f.content:
            errors.append(f"入口文件 '{f.path}' 缺少 install 方法（Vue插件格式）")

    errors.extend(_validate_form_component_editor_registration(file_map))
    errors.extend(_validate_widget_config_contract(files))

    return errors


def _validate_form_component_editor_registration(file_map: dict[str, "GeneratedFile"]) -> List[str]:
    errors = []
    widget_config_paths = [
        path for path in file_map
        if path.startswith("src/form-component-config/form-widget/") and path.endswith(".widget.config.json")
    ]
    if not widget_config_paths:
        return errors

    for widget_config_path in widget_config_paths:
        widget_name = widget_config_path.rsplit("/", 1)[-1].replace(".widget.config.json", "")
        editor_config_path = f"src/form-component-config/form-editor/{widget_name}.editor.config.json"
        editor_index_path = "src/form-component-config/form-editor/index.js"
        setting_path = f"src/form-component/form-editor/{widget_name}-setting.vue"
        form_editor_index_path = "src/form-component/form-editor/index.js"

        editor_config = file_map.get(editor_config_path)
        if not editor_config:
            errors.append(f"缺少编辑器配置文件 '{editor_config_path}'")
            continue

        setting_file = file_map.get(setting_path)
        if not setting_file:
            legacy_paths = [
                "src/form-component/form-editor/setting.vue",
                "src/form-component-config/form-editor/setting.vue",
                f"src/form-component/form-widget/setting/{widget_name}-setting.vue",
                f"src/form-component-config/form-widget/setting/{widget_name}-setting.vue",
            ]
            matched_legacy_path = next((path for path in legacy_paths if path in file_map), None)
            if matched_legacy_path:
                errors.append(
                    f"设置面板文件路径错误，发现 '{matched_legacy_path}'，应为 '{setting_path}'"
                )
            else:
                errors.append(f"缺少设置面板文件 '{setting_path}'")
            continue
        for contract_error in validate_setting_component_contract(setting_file.content):
            errors.append(f"'{setting_path}' 不符合平台约束：{contract_error}")

        editor_index = file_map.get(editor_index_path)
        if not editor_index:
            errors.append(f"缺少编辑器配置聚合文件 '{editor_index_path}'")
        elif f"./{widget_name}.editor.config.json" not in editor_index.content:
            errors.append(f"'{editor_index_path}' 未导入 './{widget_name}.editor.config.json'")

        form_editor_index = file_map.get(form_editor_index_path)
        if not form_editor_index:
            errors.append(f"缺少配置面板聚合文件 '{form_editor_index_path}'")
        elif f"./{widget_name}-setting.vue" not in form_editor_index.content:
            errors.append(f"'{form_editor_index_path}' 未导入 './{widget_name}-setting.vue'")

        # editor.config.json 用 JSON 解析获取 componentName
        editor_component_name = None
        try:
            editor_data = json.loads(editor_config.content)
            editor_component_name = editor_data.get("componentName")
        except json.JSONDecodeError:
            errors.append(f"'{editor_config_path}' 不是合法的 JSON 格式")

        setting_name_match = re.search(r"name:\s*['\"]([^'\"]+)['\"]", setting_file.content)
        if not editor_component_name:
            errors.append(f"'{editor_config_path}' 缺少 componentName")
        if not setting_name_match:
            errors.append(f"'{setting_path}' 缺少组件 name")
        if editor_component_name and setting_name_match:
            if editor_component_name != setting_name_match.group(1):
                errors.append(
                    f"'{editor_config_path}' 的 componentName 与 '{setting_path}' 的 name 不一致"
                )

    return errors


def _validate_widget_config_contract(files: List["GeneratedFile"]) -> List[str]:
    """使用 Pydantic 校验 .widget.config.json 文件结构"""
    errors = []
    widget_config_files = [f for f in files if f.path.endswith(".widget.config.json")]
    for f in widget_config_files:
        try:
            data = json.loads(f.content)
        except json.JSONDecodeError as e:
            errors.append(f"'{f.path}' 不是合法的 JSON 格式：{e}")
            continue

        try:
            WidgetComponentConfig.model_validate(data)
        except Exception as e:
            for err in getattr(e, "errors", lambda: [{"msg": str(e)}])():
                loc = " -> ".join(str(x) for x in err.get("loc", []))
                msg = err.get("msg", str(err))
                errors.append(f"'{f.path}' 校验失败：{loc} — {msg}" if loc else f"'{f.path}' 校验失败：{msg}")

    return errors


def _validate_widget_config_contract_legacy_regex(files: List["GeneratedFile"]) -> List[str]:
    """旧正则校验逻辑（已停用，保留备用）"""
    errors = []
    widget_config_files = [f for f in files if f.path.endswith(".widget.config.js")]
    for f in widget_config_files:
        root_match = re.search(r"(?m)^  componentModelField\s*:\s*\[\s*'([^']+)'\s*\]", f.content)
        if not root_match:
            errors.append(f"'{f.path}' 的 componentModelField 必须与 widget 同级")
            continue

        component_model_field = root_match.group(1)
        if component_model_field not in SUPPORTED_COMPONENT_MODEL_FIELDS:
            errors.append(
                f"'{f.path}' 的 componentModelField 只能是 STRING / NUM / DATE / BIG_TEXT，当前为 '{component_model_field}'"
            )

        if re.search(r"(?m)^[ \t]{4,}componentModelField\s*:", f.content):
            errors.append(f"'{f.path}' 的 componentModelField 不能写在 widget 内部")

        bof_match = re.search(r"frontBusinessObjectComponentType\s*:\s*'([^']+)'", f.content)
        expected_bof_type = COMPONENT_MODEL_FIELD_TO_BOF_TYPE.get(component_model_field)
        if bof_match and expected_bof_type and bof_match.group(1) != expected_bof_type:
            errors.append(
                f"'{f.path}' 的 frontBusinessObjectComponentType 应为 '{expected_bof_type}'，与 componentModelField 不匹配"
            )

    return errors


def _validate_backend(files: List["GeneratedFile"], scene: "SceneInfo") -> List[str]:
    """校验后端代码规范"""
    errors = []

    java_files = [f for f in files if f.path.endswith(".java")]

    # 检查包名
    for f in java_files:
        package_match = re.search(r'package\s+([\w.]+);', f.content)
        if package_match:
            pkg = package_match.group(1)
            if not pkg.startswith("com.xdap"):
                errors.append(f"文件 '{f.path}' 的包名 '{pkg}' 未以 com.xdap 开头")

    # 检查Controller接口路径
    controller_files = [f for f in java_files if "Controller" in f.path]
    for f in controller_files:
        mappings = re.findall(r'@(?:Request|Get|Post|Put|Delete)Mapping\("([^"]+)"\)', f.content)
        for mapping in mappings:
            if not mapping.startswith("/custom"):
                errors.append(f"接口路径 '{mapping}' 未以 /custom 开头")

    # 检查白名单配置
    has_allow_url = any("AllowUrlManage" in f.content for f in java_files)
    if java_files and not has_allow_url:
        errors.append("缺少 AllowUrlManage 接口实现（接口白名单配置）")

    return errors
