"""
代码校验器 - 验证生成的代码是否符合aPaaS平台规范
"""

import re
import json
from typing import List, TYPE_CHECKING

from app.coding.form_component_editor import validate_setting_component_contract

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
        if path.startswith("src/form-component-config/form-widget/") and path.endswith(".widget.config.js")
    ]
    if not widget_config_paths:
        return errors

    for widget_config_path in widget_config_paths:
        widget_name = widget_config_path.rsplit("/", 1)[-1].replace(".widget.config.js", "")
        editor_config_path = f"src/form-component-config/form-editor/{widget_name}.editor.config.js"
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
        elif f"./{widget_name}.editor.config" not in editor_index.content:
            errors.append(f"'{editor_index_path}' 未导入 './{widget_name}.editor.config'")

        form_editor_index = file_map.get(form_editor_index_path)
        if not form_editor_index:
            errors.append(f"缺少配置面板聚合文件 '{form_editor_index_path}'")
        elif f"./{widget_name}-setting.vue" not in form_editor_index.content:
            errors.append(f"'{form_editor_index_path}' 未导入 './{widget_name}-setting.vue'")

        component_name_match = re.search(r"componentName:\s*['\"]([^'\"]+)['\"]", editor_config.content)
        setting_name_match = re.search(r"name:\s*['\"]([^'\"]+)['\"]", setting_file.content)
        if not component_name_match:
            errors.append(f"'{editor_config_path}' 缺少 componentName")
        if not setting_name_match:
            errors.append(f"'{setting_path}' 缺少组件 name")
        if component_name_match and setting_name_match:
            if component_name_match.group(1) != setting_name_match.group(1):
                errors.append(
                    f"'{editor_config_path}' 的 componentName 与 '{setting_path}' 的 name 不一致"
                )

    return errors


def _validate_widget_config_contract(files: List["GeneratedFile"]) -> List[str]:
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
