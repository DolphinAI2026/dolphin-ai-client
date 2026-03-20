"""
代码校验器 - 验证生成的代码是否符合aPaaS平台规范
"""

import re
import json
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from app.coding.generator import GeneratedFile
    from app.coding.scenes import SceneInfo


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
