from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


FORM_COMPONENT_PREFIX = "form-component-"
STRING_COMPONENT_MODEL_FIELD_MAX_LENGTH = 500
SUPPORTED_COMPONENT_MODEL_FIELDS = {"STRING", "NUM", "DATE", "BIG_TEXT"}
LEGACY_COMPONENT_MODEL_FIELD_MAP = {
    "TEXT": "STRING",
    "STRING": "STRING",
    "NUMBER": "NUM",
    "NUM": "NUM",
    "DATE": "DATE",
    "BIG_TEXT": "BIG_TEXT",
    "LARGE_TEXT": "BIG_TEXT",
}
COMPONENT_MODEL_FIELD_TO_BOF_TYPE = {
    "STRING": "BOF_TEXT",
    "NUM": "BOF_NUMBER",
    "DATE": "BOF_DATE",
    "BIG_TEXT": "BOF_TEXT",
}

FORBIDDEN_SETTING_API_MARKERS = (
    "updateCustomComponentConfig",
    "updateWidgetConfig",
    "updateWidgetCustomConfig",
    "updateSpecialConfig",
    "setWidgetInfo",
    "update:componentConfig",
)
FORBIDDEN_SETTING_HANDLER_NAMES: tuple[str, ...] = ()
FORBIDDEN_SETTING_METHOD_NAMES: tuple[str, ...] = ()
RESERVED_SETTING_COMPUTED_NAMES = {"widgetObj", "engine", "customComponentConfig"}
RESERVED_SETTING_WATCH_NAMES = {"localConfig", "componentConfig", "customComponentConfig", "formData", "config"}
SETTING_CONTRACT_RULES: tuple[tuple[str, str], ...] = (
    ("forbidden_form_engine_api", r"updateCustomComponentConfig|updateWidgetConfig|updateWidgetCustomConfig|updateSpecialConfig|setWidgetInfo"),
    ("forbidden_emit_update", r"\$emit\(\s*['\"]update:componentConfig['\"]"),
    ("forbidden_local_mirror", r"\b(?:localConfig|formData)\b"),
    ("forbidden_config_mirror", r"(?m)^[ \t]*config\s*:\s*{"),
    ("forbidden_config_binding", r"v-model\s*=\s*['\"]config\."),
    ("forbidden_widget_obj_binding", r"widgetObj\.customComponentConfig|this\.widgetObj\.customComponentConfig"),
    ("forbidden_direct_prop_binding", r"componentConfig\.customComponentConfig|this\.componentConfig\.customComponentConfig"),
    ("forbidden_custom_component_config_assignment", r"\b(?:this|self|vm|ctx)\.customComponentConfig\s*="),
)
SETTING_CONTRACT_ERROR_MESSAGES = {
    "forbidden_form_engine_api": "禁止调用不存在的 formEngine 配置更新方法",
    "forbidden_emit_update": "禁止通过 $emit('update:componentConfig') 回写配置",
    "forbidden_local_mirror": "禁止使用 localConfig 或 formData 镜像配置",
    "forbidden_config_mirror": "禁止在 data/watch 中声明 config 镜像配置",
    "forbidden_config_binding": "模板中禁止绑定 config.xxx，应直接绑定 customComponentConfig.xxx",
    "forbidden_widget_obj_binding": "禁止依赖 widgetObj.customComponentConfig",
    "forbidden_direct_prop_binding": "模板中禁止直接绑定 componentConfig.customComponentConfig",
    "forbidden_custom_component_config_assignment": "禁止整体重设 customComponentConfig，只能直接修改其字段",
    "forbidden_custom_component_config_mirror": "禁止在 data 中声明 customComponentConfig 镜像对象",
    "missing_custom_component_config_computed": "缺少 customComponentConfig 计算属性",
    "missing_custom_component_config_init": "缺少 created 中的 customComponentConfig 初始化逻辑",
}


@dataclass(frozen=True)
class FormComponentEditorSpec:
    full_kebab: str
    short_kebab: str
    prefix: str
    setting_component_name: str
    editor_config_name: str
    setting_code: str

    @property
    def setting_file_path(self) -> str:
        return f"src/form-component/form-editor/{self.full_kebab}-setting.vue"

    @property
    def editor_index_path(self) -> str:
        return "src/form-component/form-editor/index.js"

    @property
    def editor_config_file_path(self) -> str:
        return f"src/form-component-config/form-editor/{self.full_kebab}.editor.config.json"

    @property
    def editor_config_index_path(self) -> str:
        return "src/form-component-config/form-editor/index.js"

    @property
    def widget_config_file_path(self) -> str:
        return f"src/form-component-config/form-widget/{self.full_kebab}.widget.config.json"

    @property
    def widget_index_path(self) -> str:
        return "src/form-component/form-widget/index.js"

    @property
    def widget_config_index_path(self) -> str:
        return "src/form-component-config/form-widget/index.js"

    @property
    def legacy_setting_file_path(self) -> str:
        return "src/form-component/form-editor/setting.vue"

    @property
    def legacy_editor_setting_file_path(self) -> str:
        return "src/form-component-config/form-editor/setting.vue"

    @property
    def misplaced_setting_file_path(self) -> str:
        return f"src/form-component-config/form-widget/setting/{self.full_kebab}-setting.vue"

    @property
    def legacy_widget_setting_file_path(self) -> str:
        return f"src/form-component/form-widget/setting/{self.full_kebab}-setting.vue"

    @property
    def candidate_setting_file_paths(self) -> tuple[str, ...]:
        return (
            self.setting_file_path,
            self.legacy_setting_file_path,
            self.legacy_editor_setting_file_path,
            self.misplaced_setting_file_path,
            self.legacy_widget_setting_file_path,
        )


def discover_form_component_editor_spec(workspace_path: Path) -> FormComponentEditorSpec | None:
    full_kebab = _discover_form_component_name(workspace_path)
    if not full_kebab or not full_kebab.startswith(FORM_COMPONENT_PREFIX):
        return None

    short_kebab = full_kebab[len(FORM_COMPONENT_PREFIX):]
    pascal_suffix = "".join(part.capitalize() for part in short_kebab.split("-") if part)
    prefix = f"FormComponent{pascal_suffix}"
    return FormComponentEditorSpec(
        full_kebab=full_kebab,
        short_kebab=short_kebab,
        prefix=prefix,
        setting_component_name=f"{prefix}Setting",
        editor_config_name=f"{prefix}EditorConfig",
        setting_code=f"FORM_CUSTOM_{short_kebab.replace('-', '_').upper()}_SETTING",
    )


def normalize_form_component_generated_file(
    file_path: str,
    content: str,
    workspace_path: Path,
) -> tuple[str, str]:
    spec = discover_form_component_editor_spec(workspace_path)
    if not spec:
        return file_path, content

    normalized_path = file_path.replace("\\", "/").strip()
    normalized_content = content

    if normalized_path == spec.legacy_setting_file_path:
        normalized_path = spec.setting_file_path
    elif normalized_path == spec.legacy_editor_setting_file_path:
        normalized_path = spec.setting_file_path
    elif normalized_path == spec.misplaced_setting_file_path:
        normalized_path = spec.setting_file_path
    elif normalized_path == spec.legacy_widget_setting_file_path:
        normalized_path = spec.setting_file_path
    elif normalized_path.startswith("src/form-component/form-editor/") and normalized_path.endswith("-setting.vue"):
        normalized_path = spec.setting_file_path
    elif normalized_path.startswith("src/form-component/form-widget/setting/") and normalized_path.endswith("-setting.vue"):
        normalized_path = spec.setting_file_path
    elif normalized_path.startswith("src/form-component-config/form-editor/") and (
        normalized_path.endswith(".editor.config.js") or normalized_path.endswith(".editor.config.json")
    ):
        normalized_path = spec.editor_config_file_path

    if normalized_path == spec.setting_file_path:
        normalized_content = normalize_setting_component_content(spec, normalized_content)
    elif normalized_path == spec.editor_index_path:
        normalized_content = render_form_component_editor_index(spec)
    elif normalized_path == spec.editor_config_file_path:
        normalized_content = render_form_component_editor_config(spec)
    elif normalized_path == spec.editor_config_index_path:
        normalized_content = render_form_component_editor_config_index(spec)
    elif normalized_path == spec.widget_config_file_path:
        normalized_content = normalize_widget_config_content(spec, normalized_content)

    return normalized_path, normalized_content


def normalize_form_component_editor_artifacts(workspace_path: Path) -> list[str]:
    spec = discover_form_component_editor_spec(workspace_path)
    if not spec:
        return []

    changed_files: list[str] = []
    target_setting_path = workspace_path / spec.setting_file_path
    target_setting_path.parent.mkdir(parents=True, exist_ok=True)

    setting_content = None
    best_score = None
    for candidate_path in spec.candidate_setting_file_paths:
        candidate = workspace_path / candidate_path
        if candidate.exists() and candidate.is_file():
            candidate_content = candidate.read_text(encoding="utf-8")
            candidate_score = _setting_content_score(candidate_content)
            if best_score is None or candidate_score > best_score:
                setting_content = candidate_content
                best_score = candidate_score

    if setting_content is None:
        setting_content = render_form_component_setting_stub(spec)
    setting_content = normalize_setting_component_content(spec, setting_content)
    if _write_if_changed(target_setting_path, setting_content):
        changed_files.append(spec.setting_file_path)

    for file_path, content in (
        (spec.editor_index_path, render_form_component_editor_index(spec)),
        (spec.editor_config_file_path, render_form_component_editor_config(spec)),
        (spec.editor_config_index_path, render_form_component_editor_config_index(spec)),
        (spec.widget_index_path, render_form_component_widget_index(spec)),
        (spec.widget_config_index_path, render_form_component_widget_config_index(spec)),
    ):
        if _write_if_changed(workspace_path / file_path, content):
            changed_files.append(file_path)

    widget_config_path = workspace_path / spec.widget_config_file_path
    if widget_config_path.exists():
        widget_config_content = widget_config_path.read_text(encoding="utf-8")
        normalized_widget_config_content = normalize_widget_config_content(spec, widget_config_content)
        if _write_if_changed(widget_config_path, normalized_widget_config_content):
            changed_files.append(spec.widget_config_file_path)

    for extra_path in spec.candidate_setting_file_paths[1:]:
        extra = workspace_path / extra_path
        if extra.exists() and extra != target_setting_path:
            extra.unlink()
            changed_files.append(str(extra.relative_to(workspace_path)))

    editor_config_dir = workspace_path / "src/form-component-config/form-editor"
    if editor_config_dir.exists():
        target_editor_config_name = Path(spec.editor_config_file_path).name
        for pattern in ("*.editor.config.js", "*.editor.config.json"):
            for extra in editor_config_dir.glob(pattern):
                if extra.name != target_editor_config_name:
                    extra.unlink()
                    changed_files.append(str(extra.relative_to(workspace_path)))

    widget_config_dir = workspace_path / "src/form-component-config/form-widget"
    if widget_config_dir.exists():
        target_widget_config_name = Path(spec.widget_config_file_path).name
        for pattern in ("*.widget.config.js", "*.widget.config.json"):
            for extra in widget_config_dir.glob(pattern):
                if extra.name != target_widget_config_name:
                    extra.unlink()
                    changed_files.append(str(extra.relative_to(workspace_path)))

    # 同步 apaas.json：从 widget.config.json 读取权威的 code/text/description
    apaas_changed = _normalize_form_component_apaas_json(workspace_path, spec)
    changed_files.extend(apaas_changed)

    return list(dict.fromkeys(changed_files))


def _normalize_form_component_apaas_json(workspace_path: Path, spec: FormComponentEditorSpec) -> list[str]:
    """同步 apaas.json 的 customWidgetList / copyAssets / outputName，使其与 widget.config.json 保持一致。

    - outputName = form-component-custom-{spec.short_kebab}
    - copyAssets = []  （FORM_COMPONENT 不需要 copyAssets，平台自行处理）
    - customWidgetList[0].code/text/description 来自 widget.config.json 的 code/desc.text/desc.description
    """
    apaas_json_path = workspace_path / "src" / "apaas.json"
    if not apaas_json_path.exists():
        return []

    try:
        apaas = json.loads(apaas_json_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    # 从 widget.config.json 读取 code / text / description
    widget_code, widget_text, widget_description = _read_widget_config_identity(workspace_path, spec)

    # short_kebab 可能已包含 custom-（如 "custom-dev"），避免生成 form-component-custom-custom-dev
    semantic = spec.short_kebab
    if semantic.startswith("custom-"):
        semantic = semantic[len("custom-"):]
    if not semantic or semantic == "dev":
        semantic = "component"
    output_name = f"form-component-custom-{semantic}"
    custom_widget_entry: dict = {
        "code": widget_code or f"FORM_CUSTOM_{spec.short_kebab.replace('-', '_').upper()}",
        "text": widget_text or spec.short_kebab,
        "description": widget_description or spec.short_kebab,
    }

    repaired = dict(apaas)
    repaired["entry"] = "index.js"
    repaired["templateType"] = "FORM_COMPONENT"
    repaired["customWidgetList"] = [custom_widget_entry]
    repaired["copyAssets"] = []
    repaired["outputName"] = output_name

    new_content = json.dumps(repaired, indent=2, ensure_ascii=False) + "\n"
    if _write_if_changed(apaas_json_path, new_content):
        return ["src/apaas.json"]
    return []


def _read_widget_config_identity(workspace_path: Path, spec: FormComponentEditorSpec) -> tuple[str, str, str]:
    """从 widget.config.json 读取 code、desc.text、desc.description。"""
    widget_config_path = workspace_path / spec.widget_config_file_path
    if not widget_config_path.exists():
        return "", "", ""
    try:
        raw = widget_config_path.read_text(encoding="utf-8")
        cfg = json.loads(raw)
        code = cfg.get("code", "")
        desc = cfg.get("desc") or {}
        text = desc.get("text", "")
        description = desc.get("description", "")
        return code, text, description
    except Exception:
        return "", "", ""


def render_form_component_editor_index(spec: FormComponentEditorSpec) -> str:
    return (
        f"import {spec.setting_component_name} from './{spec.full_kebab}-setting.vue'\n\n"
        "const customFormEditorList = [\n"
        f"  {spec.setting_component_name}\n"
        "]\n\n"
        "export default customFormEditorList\n"
    )


def render_form_component_widget_index(spec: FormComponentEditorSpec) -> str:
    """生成 src/form-component/form-widget/index.js — 聚合所有场景组件为数组。"""
    return (
        "import ideFormComponentList from './ide'\n"
        "import editFormComponentList from './edit'\n"
        "import readFormComponentList from './read'\n"
        "import listFormComponentList from './list'\n"
        "import printFormComponentList from './print'\n"
        "import searchFormComponentList from './search'\n"
        "import searchIdeFormComponentList from './search-ide'\n\n"
        "const customFormComponentList = [\n"
        "  ...ideFormComponentList,\n"
        "  ...editFormComponentList,\n"
        "  ...readFormComponentList,\n"
        "  ...listFormComponentList,\n"
        "  ...printFormComponentList,\n"
        "  ...searchFormComponentList,\n"
        "  ...searchIdeFormComponentList,\n"
        "]\n\n"
        "export default customFormComponentList\n"
    )


def render_form_component_widget_config_index(spec: FormComponentEditorSpec) -> str:
    """生成 src/form-component-config/form-widget/index.js — 聚合 widget config 为数组。"""
    return (
        f"import {spec.editor_config_name.replace('EditorConfig', 'WidgetConfig')} "
        f"from './{spec.full_kebab}.widget.config.json'\n\n"
        f"const widgetConfigList = [\n"
        f"  {spec.editor_config_name.replace('EditorConfig', 'WidgetConfig')}\n"
        "]\n\n"
        "export default widgetConfigList\n"
    )


def render_form_component_editor_config(spec: FormComponentEditorSpec) -> str:
    return json.dumps({
        "code": spec.setting_code,
        "editorConfigType": spec.setting_code,
        "componentName": spec.setting_component_name,
        "configProperty": "customComponentConfig",
    }, indent=2, ensure_ascii=False) + "\n"


def render_form_component_editor_config_index(spec: FormComponentEditorSpec) -> str:
    return (
        f"import {spec.editor_config_name} from './{spec.full_kebab}.editor.config.json'\n\n"
        "const editorConfigList = [\n"
        f"  {spec.editor_config_name}\n"
        "]\n\n"
        "export default editorConfigList\n"
    )


def render_form_component_setting_stub(spec: FormComponentEditorSpec) -> str:
    return f"""<template>
  <div class="form-config-item form-config-{spec.short_kebab}-setting">
    <div class="setting-panel">
      <!-- 直接放置 el-form-item，平台外层已提供 el-form -->
      <!-- 在此添加配置项，统一使用 v-model=\"customComponentConfig.xxx\" -->
    </div>
  </div>
</template>

<script>
export default {{
  name: '{spec.setting_component_name}',
  props: {{
    componentConfig: {{ default: null }},
    formEngine: {{ default: null }},
    widget: {{ default: null }},
    editConfig: {{ default: null }},
    configProperty: {{ default: null }},
    formItemList: {{ default: null }},
    formRule: {{ default: null }},
    globalData: {{ default: null }},
    widgetConfig: {{ default: null }},
    disabled: {{ default: false }}
  }},
  inject: {{
    renderGlobal: {{ default: null }},
    getPreviewLanguage: {{ default: null }},
    getI18nShowStatus: {{ default: null }},
    filterTableFromNodeFields: {{ default: null }}
  }},
  computed: {{
    customComponentConfig() {{
      const target = this.componentConfig || this.widget || null
      return (target && target.customComponentConfig) || {{}}
    }},
    engine() {{
      if (this.formEngine) return this.formEngine
      if (this.renderGlobal) return this.renderGlobal
      return null
    }}
  }},
  created() {{
    const target = this.componentConfig || this.widget || null
    if (target && !target.customComponentConfig) {{
      this.$set(target, 'customComponentConfig', {{}})
    }}
  }}
}}
</script>

<style lang="scss">
.form-config-{spec.short_kebab}-setting {{}}
</style>
"""


def normalize_setting_component_content(spec: FormComponentEditorSpec, content: str) -> str:
    normalized = normalize_setting_component_name(content, spec.setting_component_name)
    normalized = strip_setting_el_form_wrapper(normalized)
    normalized = sanitize_setting_component_behavior(spec, normalized)
    normalized = strip_setting_outer_padding(normalized)
    if validate_setting_component_contract(normalized):
        normalized = _force_setting_component_contract(spec, normalized)
        normalized = strip_setting_outer_padding(normalized)
    return normalized


def normalize_setting_component_name(content: str, component_name: str) -> str:
    normalized = content
    if re.search(r"name\s*:\s*['\"][^'\"]+['\"]", normalized):
        return re.sub(
            r"name\s*:\s*['\"][^'\"]+['\"]",
            f"name: '{component_name}'",
            normalized,
            count=1,
        )

    export_default_match = re.search(r"export\s+default\s*{", normalized)
    if export_default_match:
        insert_at = export_default_match.end()
        return normalized[:insert_at] + f"\n  name: '{component_name}'," + normalized[insert_at:]

    return normalized


def sanitize_setting_component_behavior(spec: FormComponentEditorSpec, content: str) -> str:
    if not _contains_invalid_setting_patterns(content):
        return content

    return _force_setting_component_contract(spec, content)


def _force_setting_component_contract(spec: FormComponentEditorSpec, content: str) -> str:
    normalized = content
    sanitized_script = _build_sanitized_setting_script(spec, normalized)
    template_block = _extract_single_file_block(normalized, "template")
    if template_block:
        normalized = normalized.replace(
            template_block,
            _sanitize_setting_template_block(
                template_block,
                allowed_methods=_extract_setting_method_names_from_script(sanitized_script),
            ),
            1,
        )

    script_block = _extract_single_file_block(normalized, "script")
    if script_block:
        normalized = normalized.replace(script_block, sanitized_script, 1)
    else:
        style_block = _extract_single_file_block(normalized, "style")
        insert_at = normalized.find(style_block) if style_block else len(normalized)
        normalized = f"{normalized[:insert_at].rstrip()}\n\n{sanitized_script}\n\n{normalized[insert_at:].lstrip()}"

    return normalized


def _contains_invalid_setting_patterns(content: str) -> bool:
    return bool(validate_setting_component_contract(content))


def _collect_setting_component_violations(content: str) -> list[str]:
    normalized = content or ""
    violations: list[str] = []
    for rule_name, pattern in SETTING_CONTRACT_RULES:
        if re.search(pattern, normalized):
            violations.append(rule_name)
    if re.search(r"(?m)^[ \t]*customComponentConfig\s*:\s*{", normalized):
        violations.append("forbidden_custom_component_config_mirror")
    for handler in FORBIDDEN_SETTING_HANDLER_NAMES:
        if f"{handler}(" in normalized:
            violations.append(f"forbidden_handler_{handler}")
    return list(dict.fromkeys(violations))


def validate_setting_component_contract(content: str) -> list[str]:
    violations = _collect_setting_component_violations(content)
    if not re.search(r"\bcustomComponentConfig\s*\(\)\s*{", content or ""):
        violations.append("missing_custom_component_config_computed")
    if not re.search(r"this\.\$set\(\s*target\s*,\s*['\"]customComponentConfig['\"]\s*,", content or ""):
        violations.append("missing_custom_component_config_init")
    template_block = _extract_single_file_block(content or "", "template") or ""
    script_block = _extract_single_file_block(content or "", "script") or ""
    allowed_methods = _extract_setting_method_names_from_script(script_block)
    for handler_name in _find_undefined_setting_template_handlers(template_block, allowed_methods):
        violations.append(f"undefined_template_handler:{handler_name}")
    messages: list[str] = []
    for code in list(dict.fromkeys(violations)):
        if code in SETTING_CONTRACT_ERROR_MESSAGES:
            messages.append(SETTING_CONTRACT_ERROR_MESSAGES[code])
            continue
        if code.startswith("forbidden_handler_"):
            handler_name = code.removeprefix("forbidden_handler_")
            messages.append(f"禁止保留旧的配置同步方法：{handler_name}")
            continue
        if code.startswith("undefined_template_handler:"):
            handler_name = code.removeprefix("undefined_template_handler:")
            messages.append(f"模板绑定了未定义的方法：{handler_name}")
            continue
        messages.append(code)
    return messages


def validate_form_component_editor_workspace(workspace_path: Path) -> list[str]:
    spec = discover_form_component_editor_spec(workspace_path)
    if not spec:
        return []

    target_setting_path = workspace_path / spec.setting_file_path
    if not target_setting_path.exists():
        return [f"缺少 setting.vue：{spec.setting_file_path}"]

    errors = [
        f"{spec.setting_file_path}: {message}"
        for message in validate_setting_component_contract(
            target_setting_path.read_text(encoding="utf-8")
        )
    ]

    for extra_path in spec.candidate_setting_file_paths[1:]:
        extra = workspace_path / extra_path
        if extra.exists():
            errors.append(f"发现遗留 setting.vue 路径：{extra_path}，应统一落到 {spec.setting_file_path}")

    return list(dict.fromkeys(errors))


def _extract_single_file_block(content: str, tag_name: str) -> str | None:
    match = re.search(rf"<{tag_name}\b[^>]*>.*?</{tag_name}>", content, re.DOTALL)
    if not match:
        return None
    return match.group(0)


def _extract_setting_method_names_from_script(script_block: str) -> set[str]:
    export_body = _extract_export_default_body(script_block or "")
    if export_body is None:
        return set()

    for entry in _split_top_level_entries(export_body):
        if _get_object_entry_name(entry) != "methods":
            continue
        methods_body = _extract_object_body_from_entry(entry) or ""
        return {
            method_name
            for method_entry in _split_top_level_entries(methods_body)
            if (method_name := _get_object_entry_name(method_entry))
        }
    return set()


def _extract_setting_template_handler_names(expression: str) -> set[str]:
    expr = (expression or "").strip()
    if not expr:
        return set()

    handler_names = {
        name
        for name in re.findall(r"\bthis\.([A-Za-z_$][\w$]*)\s*\(", expr)
        if not name.startswith("$")
    }
    handler_names.update(
        name
        for name in re.findall(r"(?<![\w$.])([A-Za-z_$][\w$]*)\s*\(", expr)
        if not name.startswith("$")
    )
    if re.fullmatch(r"[A-Za-z_$][\w$]*", expr) and not expr.startswith("$"):
        handler_names.add(expr)
    return handler_names


def _find_undefined_setting_template_handlers(template_block: str, allowed_methods: set[str]) -> list[str]:
    if not template_block:
        return []

    undefined_handlers: list[str] = []
    for match in re.finditer(r"@[A-Za-z0-9:_-]+=(['\"])(?P<expr>[^'\"]*)\1", template_block):
        handler_names = _extract_setting_template_handler_names(match.group("expr"))
        for handler_name in handler_names:
            if handler_name not in allowed_methods:
                undefined_handlers.append(handler_name)
    return list(dict.fromkeys(undefined_handlers))


def _sanitize_setting_template_block(template_block: str, allowed_methods: set[str] | None = None) -> str:
    normalized = template_block
    event_pattern = re.compile(r"\s+@[A-Za-z0-9:_-]+=(['\"])(?P<expr>[^'\"]*)\1")

    def _replace_event_binding(match: re.Match[str]) -> str:
        expr = match.group("expr")
        handler_names = _extract_setting_template_handler_names(expr)
        if not handler_names:
            return match.group(0)
        if allowed_methods is not None and any(name not in allowed_methods for name in handler_names):
            return ""
        return match.group(0)

    normalized = event_pattern.sub(_replace_event_binding, normalized)
    normalized = re.sub(r"(?<![\w$.])config\.", "customComponentConfig.", normalized)
    normalized = _normalize_setting_custom_config_refs(normalized)
    return normalized


def _build_sanitized_setting_script(spec: FormComponentEditorSpec, content: str) -> str:
    export_body = _extract_export_default_body(content)
    if export_body is None:
        return _extract_single_file_block(render_form_component_setting_stub(spec), "script") or "<script>\nexport default {}\n</script>"

    top_level_entries = _split_top_level_entries(export_body)
    extra_option_entries: list[str] = []
    extra_data_entries: list[str] = []
    extra_computed_entries: list[str] = []
    extra_watch_entries: list[str] = []
    extra_method_entries: list[str] = []
    default_config_literal = "{}"
    original_created_body = ""

    for entry in top_level_entries:
        entry_name = _get_object_entry_name(entry)
        if entry_name == "data":
            data_entries, local_config_literal = _extract_setting_data_entries(entry)
            extra_data_entries.extend(data_entries)
            if local_config_literal:
                default_config_literal = local_config_literal
            continue
        if entry_name == "computed":
            for computed_entry in _split_top_level_entries(_extract_object_body_from_entry(entry) or ""):
                computed_name = _get_object_entry_name(computed_entry)
                if not computed_name or computed_name in RESERVED_SETTING_COMPUTED_NAMES:
                    continue
                sanitized_entry = _sanitize_setting_js_entry(computed_entry)
                if sanitized_entry:
                    extra_computed_entries.append(sanitized_entry)
            continue
        if entry_name == "watch":
            for watch_entry in _split_top_level_entries(_extract_object_body_from_entry(entry) or ""):
                watch_name = _get_object_entry_name(watch_entry)
                if not watch_name or watch_name in RESERVED_SETTING_WATCH_NAMES:
                    continue
                sanitized_entry = _sanitize_setting_js_entry(watch_entry)
                if sanitized_entry:
                    extra_watch_entries.append(sanitized_entry)
            continue
        if entry_name == "methods":
            for method_entry in _split_top_level_entries(_extract_object_body_from_entry(entry) or ""):
                method_name = _get_object_entry_name(method_entry)
                if not method_name or method_name in FORBIDDEN_SETTING_METHOD_NAMES:
                    continue
                if any(marker in method_entry for marker in FORBIDDEN_SETTING_API_MARKERS):
                    continue
                sanitized_entry = _sanitize_setting_js_entry(method_entry)
                if sanitized_entry:
                    extra_method_entries.append(sanitized_entry)
            continue
        if entry_name == "created":
            original_created_body = _sanitize_created_entry_body(entry)
            continue
        if entry_name in {"name", "props", "inject", "mixins"}:
            continue

        sanitized_entry = _sanitize_setting_js_entry(entry)
        if sanitized_entry:
            extra_option_entries.append(sanitized_entry)

    created_body_parts = [
        "const target = this.componentConfig || this.widget || null",
        "if (!target) return",
        f"const defaultConfig = {default_config_literal}",
        (
            "const currentConfig = target.customComponentConfig && typeof target.customComponentConfig === 'object'\n"
            "  ? target.customComponentConfig\n"
            "  : {}"
        ),
        "this.$set(target, 'customComponentConfig', { ...defaultConfig, ...currentConfig })",
    ]
    if original_created_body:
        created_body_parts.append(original_created_body)

    option_entries = [
        f"name: '{spec.setting_component_name}'",
        """props: {
  componentConfig: { default: null },
  formEngine: { default: null },
  widget: { default: null },
  editConfig: { default: null },
  configProperty: { default: null },
  formItemList: { default: null },
  formRule: { default: null },
  globalData: { default: null },
  widgetConfig: { default: null },
  disabled: { default: false }
}""",
        """inject: {
  renderGlobal: { default: null },
  getPreviewLanguage: { default: null },
  getI18nShowStatus: { default: null },
  filterTableFromNodeFields: { default: null }
}""",
    ]
    option_entries.extend(extra_option_entries)
    if extra_data_entries:
        option_entries.append(
            "data() {\n"
            "  return {\n"
            f"{_indent_block(_join_object_entries(extra_data_entries), '    ')}\n"
            "  }\n"
            "}"
        )
    computed_entries = [
        """customComponentConfig() {
  const target = this.componentConfig || this.widget || null
  return (target && target.customComponentConfig) || {}
}""",
        """engine() {
  if (this.formEngine) return this.formEngine
  if (this.renderGlobal) return this.renderGlobal
  return null
}""",
    ]
    computed_entries.extend(extra_computed_entries)
    option_entries.append(
        "computed: {\n"
        f"{_indent_block(_join_object_entries(computed_entries), '  ')}\n"
        "}"
    )
    if extra_watch_entries:
        option_entries.append(
            "watch: {\n"
            f"{_indent_block(_join_object_entries(extra_watch_entries), '  ')}\n"
            "}"
        )
    option_entries.append(
        "created() {\n"
        f"{_indent_block('\n'.join(part for part in created_body_parts if part.strip()), '  ')}\n"
        "}"
    )
    if extra_method_entries:
        option_entries.append(
            "methods: {\n"
            f"{_indent_block(_join_object_entries(extra_method_entries), '  ')}\n"
            "}"
        )

    return (
        "<script>\n"
        "export default {\n"
        f"{_indent_block(_join_object_entries(option_entries), '  ')}\n"
        "}\n"
        "</script>"
    )


def _extract_export_default_body(content: str) -> str | None:
    match = re.search(r"export\s+default\s*{", content)
    if not match:
        return None
    open_index = match.end() - 1
    close_index = _find_matching_delimiter(content, open_index, "{", "}")
    if close_index < 0:
        return None
    return content[open_index + 1:close_index]


def _extract_object_body_from_entry(entry: str) -> str | None:
    stripped = entry.strip()
    colon_index = stripped.find(":")
    if colon_index >= 0:
        open_index = stripped.find("{", colon_index)
    else:
        open_index = stripped.find("{")
    if open_index < 0:
        return None
    close_index = _find_matching_delimiter(stripped, open_index, "{", "}")
    if close_index < 0:
        return None
    return stripped[open_index + 1:close_index]


def _extract_setting_data_entries(entry: str) -> tuple[list[str], str | None]:
    return_match = re.search(r"return\s*{", entry)
    if not return_match:
        return [], None

    open_index = return_match.end() - 1
    close_index = _find_matching_delimiter(entry, open_index, "{", "}")
    if close_index < 0:
        return [], None

    return_body = entry[open_index + 1:close_index]
    extra_entries: list[str] = []
    local_config_literal = None
    for data_entry in _split_top_level_entries(return_body):
        data_name = _get_object_entry_name(data_entry)
        if data_name in {"localConfig", "customComponentConfig", "formData", "config"}:
            local_config_literal = _normalize_js_literal_indentation(_extract_entry_value_literal(data_entry))
            continue
        sanitized_entry = _sanitize_setting_js_entry(data_entry)
        if sanitized_entry:
            extra_entries.append(sanitized_entry)
    return extra_entries, local_config_literal


def _extract_entry_value_literal(entry: str) -> str | None:
    colon_index = entry.find(":")
    if colon_index < 0:
        return None
    value = entry[colon_index + 1:].strip().rstrip(",")
    return value or None


def _normalize_js_literal_indentation(value: str | None) -> str | None:
    if not value:
        return value
    lines = value.strip().splitlines()
    if len(lines) <= 1:
        return lines[0]

    indents = [
        len(line) - len(line.lstrip())
        for line in lines[1:]
        if line.strip()
    ]
    trim = min(indents) if indents else 0
    normalized_lines = [lines[0].lstrip()]
    for line in lines[1:]:
        if not line.strip():
            normalized_lines.append("")
            continue
        normalized_lines.append(line[trim:])
    return "\n".join(normalized_lines)


def _sanitize_created_entry_body(entry: str) -> str:
    open_index = entry.find("{")
    if open_index < 0:
        return ""
    close_index = _find_matching_delimiter(entry, open_index, "{", "}")
    if close_index < 0:
        return ""
    body = entry[open_index + 1:close_index]
    if (
        "localConfig" in body
        or "formData" in body
        or "componentConfig" in body
        or "widgetObj" in body
        or any(marker in body for marker in FORBIDDEN_SETTING_API_MARKERS)
    ):
        return ""
    sanitized = _sanitize_setting_js_entry(body)
    lines = []
    for line in sanitized.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if "localConfig" in stripped or "formData" in stripped or "componentConfig" in stripped or "widgetObj" in stripped:
            continue
        lines.append(line.rstrip())
    return "\n".join(lines).strip()


def _sanitize_setting_js_entry(entry: str) -> str:
    normalized = entry.rstrip().rstrip(",")
    normalized = _normalize_setting_custom_config_refs(normalized)
    normalized = normalized.replace("val?.special?.customComponentConfig", "val?.customComponentConfig")
    normalized = normalized.replace("val.special.customComponentConfig", "val.customComponentConfig")

    filtered_lines: list[str] = []
    for line in normalized.splitlines():
        stripped = line.strip()
        if any(marker in stripped for marker in FORBIDDEN_SETTING_API_MARKERS):
            continue
        if re.search(r"\bthis\.(?:saveConfig|handleChange|updateCustomComponentConfig|updateComponentConfig)\s*\(", stripped):
            continue
        filtered_lines.append(line.rstrip())

    sanitized = "\n".join(filtered_lines).strip()
    if not sanitized:
        return ""
    if re.search(r"\b(?:this|self|vm|ctx)\.(?:localConfig|formData)\b", sanitized):
        return ""
    if re.search(r"(?<![\w$.])(?:localConfig|formData)\b", sanitized):
        return ""
    if re.search(r"\b(?:this|self|vm|ctx)\.componentConfig\.customComponentConfig\b", sanitized):
        return ""
    if re.search(r"\b(?:this|self|vm|ctx)\.widgetObj(?:\.customComponentConfig)?\b", sanitized):
        return ""
    if re.search(r"\b(?:this|self|vm|ctx)\.customComponentConfig\s*=", sanitized):
        return ""
    return sanitized


def _normalize_setting_custom_config_refs(content: str) -> str:
    normalized = content
    replacements = (
        (r"\bthis\.widgetObj\.customComponentConfig\b", "this.customComponentConfig"),
        (r"\bself\.widgetObj\.customComponentConfig\b", "self.customComponentConfig"),
        (r"\bvm\.widgetObj\.customComponentConfig\b", "vm.customComponentConfig"),
        (r"\bctx\.widgetObj\.customComponentConfig\b", "ctx.customComponentConfig"),
        (r"(?<![\w$.])widgetObj\.customComponentConfig\b", "customComponentConfig"),
        (r"\bthis\.componentConfig\.customComponentConfig\b", "this.customComponentConfig"),
        (r"\bself\.componentConfig\.customComponentConfig\b", "self.customComponentConfig"),
        (r"\bvm\.componentConfig\.customComponentConfig\b", "vm.customComponentConfig"),
        (r"\bctx\.componentConfig\.customComponentConfig\b", "ctx.customComponentConfig"),
        (r"(?<![\w$.])componentConfig\.customComponentConfig\b", "customComponentConfig"),
        (r"\bthis\.localConfig\b", "this.customComponentConfig"),
        (r"\bself\.localConfig\b", "self.customComponentConfig"),
        (r"\bvm\.localConfig\b", "vm.customComponentConfig"),
        (r"\bctx\.localConfig\b", "ctx.customComponentConfig"),
        (r"(?<![\w$.])localConfig\b", "customComponentConfig"),
        (r"\bthis\.formData\b", "this.customComponentConfig"),
        (r"\bself\.formData\b", "self.customComponentConfig"),
        (r"\bvm\.formData\b", "vm.customComponentConfig"),
        (r"\bctx\.formData\b", "ctx.customComponentConfig"),
        (r"(?<![\w$.])formData\b", "customComponentConfig"),
        (r"\bthis\.config\b", "this.customComponentConfig"),
        (r"\bself\.config\b", "self.customComponentConfig"),
        (r"\bvm\.config\b", "vm.customComponentConfig"),
        (r"\bctx\.config\b", "ctx.customComponentConfig"),
    )
    for pattern, replacement in replacements:
        normalized = re.sub(pattern, replacement, normalized)
    return normalized


def _split_top_level_entries(content: str) -> list[str]:
    entries: list[str] = []
    start = 0
    brace_depth = 0
    bracket_depth = 0
    paren_depth = 0
    in_string = False
    string_char = ""
    in_line_comment = False
    in_block_comment = False
    escape = False

    for index, char in enumerate(content):
        next_char = content[index + 1] if index + 1 < len(content) else ""

        if in_line_comment:
            if char == "\n":
                in_line_comment = False
            continue
        if in_block_comment:
            if char == "*" and next_char == "/":
                in_block_comment = False
            continue
        if in_string:
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = True
                continue
            if char == string_char:
                in_string = False
            continue

        if char == "/" and next_char == "/":
            in_line_comment = True
            continue
        if char == "/" and next_char == "*":
            in_block_comment = True
            continue
        if char in {"'", '"', "`"}:
            in_string = True
            string_char = char
            continue
        if char == "{":
            brace_depth += 1
            continue
        if char == "}":
            brace_depth -= 1
            continue
        if char == "[":
            bracket_depth += 1
            continue
        if char == "]":
            bracket_depth -= 1
            continue
        if char == "(":
            paren_depth += 1
            continue
        if char == ")":
            paren_depth -= 1
            continue
        if char == "," and brace_depth == 0 and bracket_depth == 0 and paren_depth == 0:
            entry = content[start:index].strip()
            if entry:
                entries.append(entry)
            start = index + 1

    tail = content[start:].strip()
    if tail:
        entries.append(tail)
    return entries


def _get_object_entry_name(entry: str) -> str | None:
    stripped = entry.strip()
    if not stripped:
        return None

    match = re.match(r"(?:async\s+)?([A-Za-z_$][\w$]*)\s*\(", stripped)
    if match:
        return match.group(1)
    match = re.match(r"([A-Za-z_$][\w$]*)\s*:", stripped)
    if match:
        return match.group(1)
    match = re.match(r"['\"]([^'\"]+)['\"]\s*:", stripped)
    if match:
        return match.group(1)
    return None


def _find_matching_delimiter(content: str, open_index: int, open_char: str, close_char: str) -> int:
    depth = 0
    in_string = False
    string_char = ""
    in_line_comment = False
    in_block_comment = False
    escape = False

    for index in range(open_index, len(content)):
        char = content[index]
        next_char = content[index + 1] if index + 1 < len(content) else ""

        if in_line_comment:
            if char == "\n":
                in_line_comment = False
            continue
        if in_block_comment:
            if char == "*" and next_char == "/":
                in_block_comment = False
            continue
        if in_string:
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = True
                continue
            if char == string_char:
                in_string = False
            continue

        if char == "/" and next_char == "/":
            in_line_comment = True
            continue
        if char == "/" and next_char == "*":
            in_block_comment = True
            continue
        if char in {"'", '"', "`"}:
            in_string = True
            string_char = char
            continue
        if char == open_char:
            depth += 1
            continue
        if char == close_char:
            depth -= 1
            if depth == 0:
                return index

    return -1


def _join_object_entries(entries: list[str]) -> str:
    return ",\n".join(entry.rstrip().rstrip(",") for entry in entries if entry.strip())


def _indent_block(content: str, indent: str) -> str:
    return "\n".join(f"{indent}{line}" if line else line for line in content.splitlines())


def strip_setting_el_form_wrapper(content: str) -> str:
    pattern = re.compile(
        r"(?P<indent>^[ \t]*)<el-form\b[^>]*>\n(?P<body>.*?)(?P=indent)</el-form>",
        re.MULTILINE | re.DOTALL,
    )

    def _replace(match: re.Match[str]) -> str:
        indent = match.group("indent")
        body = match.group("body")
        normalized_lines: list[str] = []
        for line in body.splitlines():
            if not line.strip():
                normalized_lines.append(line)
                continue
            if line.startswith(f"{indent}  "):
                normalized_lines.append(f"{indent}{line[len(indent) + 2:]}")
            else:
                normalized_lines.append(line)
        return "\n".join(normalized_lines)

    return pattern.sub(_replace, content)


def strip_setting_outer_padding(content: str) -> str:
    style_pattern = re.compile(r"(<style\b[^>]*>)(?P<body>.*?)(</style>)", re.DOTALL)

    def _replace_style(match: re.Match[str]) -> str:
        body = match.group("body")
        return f"{match.group(1)}{_strip_setting_padding_from_style_body(body)}{match.group(3)}"

    return style_pattern.sub(_replace_style, content)


def _strip_setting_padding_from_style_body(style_body: str) -> str:
    lines = style_body.splitlines()
    result: list[str] = []
    selector_stack: list[str] = []

    for line in lines:
        stripped = line.strip()
        current_selector = selector_stack[-1] if selector_stack else ""
        parent_selectors = selector_stack[:-1]
        is_root_setting_selector = len(selector_stack) == 1 and _is_setting_selector(current_selector)
        is_setting_panel_selector = (
            current_selector == ".setting-panel"
            and any(_is_setting_selector(selector) for selector in parent_selectors)
        )
        should_remove_padding = stripped.startswith("padding:") and (is_root_setting_selector or is_setting_panel_selector)

        if not should_remove_padding:
            result.append(line)

        if stripped.endswith("{"):
            selector_stack.append(stripped[:-1].strip())

        close_count = stripped.count("}")
        for _ in range(close_count):
            if selector_stack:
                selector_stack.pop()

    return "\n".join(result)


def _is_setting_selector(selector: str) -> bool:
    normalized = (selector or "").strip()
    return normalized.startswith(".form-config-") and normalized.endswith("-setting") or (
        normalized.startswith(".form-component-") and normalized.endswith("-setting")
    ) or (
        normalized.startswith(".form-editor-") and normalized.endswith("-setting")
    )

def normalize_widget_config_content(spec: FormComponentEditorSpec, content: str) -> str:
    """三层归一化：文本修复 → JSON 解析 → dict 标准化 → 序列化。"""
    # 层1：修复无法 json.loads 的原始文本
    fixed_text = _attempt_fix_invalid_widget_json(content)

    # 层2：JSON 解析
    try:
        data = json.loads(fixed_text)
    except json.JSONDecodeError:
        return content  # 无法解析则不改动

    if not isinstance(data, dict):
        return content

    # 层3：dict 级标准化
    _normalize_widget_component_names(spec, data)
    _normalize_widget_setting_code_in_dict(spec, data)
    _normalize_widget_icon_in_dict(spec, data)
    _normalize_widget_labels_in_dict(spec, data)
    _normalize_widget_model_field_in_dict(spec, data)
    _normalize_widget_methods(data)

    # Pydantic 结构归一化（兜底 coerce）
    from app.coding.validator import normalize_widget_config_with_pydantic
    data = normalize_widget_config_with_pydantic(data)

    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _attempt_fix_invalid_widget_json(content: str) -> str:
    """修复 AI 生成的 widget.config.json 中无法 json.loads 的文本层问题。

    只做文本层面的修复，不改变数据结构：
    - 去除 JS 语法行（未加引号的 key，如 `key: value,`）
    - 修复尾部逗号（在 ] 或 } 前的逗号）
    """
    lines = content.splitlines()
    cleaned: list[str] = []
    for line in lines:
        stripped = line.strip()
        # JS 语法行：key 未加引号（如 `  key: value,`）
        if re.match(r'^[A-Za-z_]\w*\s*:', stripped):
            continue
        cleaned.append(line)
    fixed = "\n".join(cleaned)
    # 修复尾部逗号
    fixed = re.sub(r',(\s*[}\]])', r'\1', fixed)
    return fixed


def _kebab_to_pascal(s: str) -> str:
    return "".join(p.capitalize() for p in s.split("-") if p)


def _normalize_widget_component_names(spec: FormComponentEditorSpec, data: dict) -> None:
    """将 component.* 字段从 kebab-case 替换为 PascalCase 类名。

    例：`form-component-phone-edit` → `FormComponentPhoneEdit`
    """
    component = data.get("component")
    if isinstance(component, dict):
        for key in list(component):
            val = component[key]
            if isinstance(val, str) and val.startswith("form-component-"):
                component[key] = _kebab_to_pascal(val)

    mobile_component = ((data.get("client") or {}).get("mobile") or {}).get("component")
    if isinstance(mobile_component, dict):
        for key in list(mobile_component):
            val = mobile_component[key]
            if isinstance(val, str) and val.startswith("form-component-"):
                mobile_component[key] = _kebab_to_pascal(val)


def _normalize_widget_setting_code_in_dict(spec: FormComponentEditorSpec, data: dict) -> None:
    """确保 widget.editor.config（和 mobile 对应字段）包含正确的 setting_code。"""
    sc = spec.setting_code

    def _inject(editor: dict) -> None:
        config = editor.get("config")
        if not isinstance(config, list):
            editor["config"] = [sc]
            return
        if sc in config:
            return
        try:
            idx = config.index("FORMULA_RULE")
            config.insert(idx, sc)
        except ValueError:
            config.append(sc)

    widget = data.get("widget")
    if isinstance(widget, dict):
        editor = widget.get("editor")
        if not isinstance(editor, dict):
            widget["editor"] = {"config": [sc], "excludeInTable": ["WIDTH"]}
        else:
            _inject(editor)

    mobile_widget = ((data.get("client") or {}).get("mobile") or {}).get("widget")
    if isinstance(mobile_widget, dict):
        mobile_editor = mobile_widget.get("editor")
        if isinstance(mobile_editor, dict):
            _inject(mobile_editor)


def _normalize_widget_icon_in_dict(spec: FormComponentEditorSpec, data: dict) -> None:
    """若图标不是有效的功能性 SVG，替换为根据组件类型生成的图标。"""
    desc = data.get("desc")
    if not isinstance(desc, dict):
        return
    current_icon = desc.get("icon", "")
    if current_icon and _is_feature_svg_icon(current_icon):
        return
    metadata = f"{spec.short_kebab} {desc.get('text', '')} {desc.get('description', '')}".lower()
    desc["icon"] = render_widget_svg_icon(spec, metadata)
    desc["iconType"] = "DEFAULT"


def _normalize_widget_labels_in_dict(spec: FormComponentEditorSpec, data: dict) -> None:
    """修正 desc.text / desc.description / widget.display.label 中的占位值。"""
    desc = data.get("desc") or {}
    current_text = (desc.get("text") or "").strip()
    current_desc = (desc.get("description") or "").strip()

    if _is_meaningful_widget_meta(current_text, spec):
        title = current_text
    else:
        title, _ = _infer_widget_title_and_description(spec, spec.short_kebab)

    if _is_meaningful_widget_description(current_desc, spec, title):
        description = current_desc
    else:
        _, description = _infer_widget_title_and_description(spec, spec.short_kebab)

    if isinstance(data.get("desc"), dict):
        data["desc"]["text"] = title
        data["desc"]["description"] = description

    widget_display = (data.get("widget") or {}).get("display")
    if isinstance(widget_display, dict):
        current_label = (widget_display.get("label") or "").strip()
        if not _is_meaningful_widget_meta(current_label, spec):
            widget_display["label"] = title


def _normalize_widget_model_field_in_dict(spec: FormComponentEditorSpec, data: dict) -> None:
    """校正 componentModelField 和 frontBusinessObjectComponentType。

    优先尊重 LLM 生成的值，只做：
    1. 旧格式映射（TEXT→STRING、NUMBER→NUM 等）
    2. 非法值兜底为 STRING
    3. frontBusinessObjectComponentType 与 componentModelField 保持一致
    """
    existing = data.get("componentModelField")
    if isinstance(existing, list) and existing:
        raw = str(existing[0]).upper()
        model_field = LEGACY_COMPONENT_MODEL_FIELD_MAP.get(raw)
        if not model_field:
            model_field = "STRING"  # 非法值兜底
    else:
        model_field = "STRING"

    bof_type = COMPONENT_MODEL_FIELD_TO_BOF_TYPE[model_field]
    data["componentModelField"] = [model_field]

    widget = data.get("widget")
    if isinstance(widget, dict):
        special = widget.get("special")
        if isinstance(special, dict):
            special["frontBusinessObjectComponentType"] = bof_type
        else:
            widget["special"] = {"frontBusinessObjectComponentType": bof_type}


def _normalize_widget_methods(data: dict) -> None:
    """将 methods: [] 强制转换为 methods: {}。"""
    if isinstance(data.get("methods"), list):
        data["methods"] = {}



def normalize_widget_config_setting_code(content: str, setting_code: str) -> str:
    normalized = content

    def _replace(match: re.Match[str]) -> str:
        array_body = _remove_setting_code_lines(match.group("body"), setting_code)
        indent = _detect_array_indent(array_body) or "        "
        trimmed_body = array_body.rstrip()
        suffix = array_body[len(trimmed_body):]
        anchor = re.search(r"\n(?P<indent>\s*)'FORMULA_RULE'[^\n]*", trimmed_body)
        if anchor:
            insert_at = anchor.start()
            inserted_body = (
                f"{trimmed_body[:insert_at]}\n"
                f"{indent}'{setting_code}',"
                f"{trimmed_body[insert_at:]}"
                f"{suffix}"
            )
        else:
            normalized_trimmed_body = _ensure_last_array_item_has_comma(trimmed_body)
            inserted_body = f"{normalized_trimmed_body}\n{indent}'{setting_code}',{suffix}"

        return f"{match.group('prefix')}{inserted_body}{match.group('suffix')}"

    pattern = re.compile(
        r"(?P<prefix>editor\s*:\s*\{\s*config\s*:\s*\[\n)(?P<body>.*?)(?P<suffix>\n\s*\])",
        re.DOTALL,
    )
    return pattern.sub(_replace, normalized)


def normalize_widget_config_icon(spec: FormComponentEditorSpec, content: str) -> str:
    current_icon = _extract_widget_icon(content)
    if current_icon and _is_feature_svg_icon(current_icon):
        return content

    svg_icon = render_widget_svg_icon(spec, content)
    icon_pattern = re.compile(r"icon:\s*'[^']*'")
    if icon_pattern.search(content):
        return icon_pattern.sub(f"icon: '{svg_icon}'", content, count=1)
    return content


def normalize_widget_config_labels(spec: FormComponentEditorSpec, content: str) -> str:
    title = _resolve_widget_title(spec, content)
    description = _resolve_widget_description(spec, content, title)

    normalized = content
    text_pattern = re.compile(r"text:\s*'[^']*'")
    description_pattern = re.compile(r"description:\s*'[^']*'")
    label_pattern = re.compile(r"label:\s*'[^']*'")

    if text_pattern.search(normalized):
        normalized = text_pattern.sub(f"text: '{_escape_js_single_quoted(title)}'", normalized, count=1)
    if description_pattern.search(normalized):
        normalized = description_pattern.sub(
            f"description: '{_escape_js_single_quoted(description)}'",
            normalized,
            count=1,
        )
    if label_pattern.search(normalized):
        normalized = label_pattern.sub(f"label: '{_escape_js_single_quoted(title)}'", normalized, count=1)

    return normalized


def normalize_widget_config_component_model_field(spec: FormComponentEditorSpec, content: str) -> str:
    model_field = _infer_component_model_field(spec, content)
    bof_type = COMPONENT_MODEL_FIELD_TO_BOF_TYPE[model_field]

    normalized = re.sub(
        r"(?ms)^[ \t]*componentModelField\s*:\s*\[[^\]]*\],?\n?",
        "",
        content,
    )
    normalized = re.sub(
        r"frontBusinessObjectComponentType\s*:\s*'[^']*'",
        f"frontBusinessObjectComponentType: '{bof_type}'",
        normalized,
        count=1,
    )

    anchor = re.search(r"(?m)^(?P<indent>\s*)(client|methods|formatValueSchema)\s*:", normalized)
    component_model_field_entry = f"  componentModelField: ['{model_field}'],\n"
    if anchor:
        normalized = normalized[:anchor.start()] + component_model_field_entry + normalized[anchor.start():]
    elif re.search(r"(?m)^}\s*$", normalized):
        normalized = re.sub(
            r"(?m)^}\s*$",
            component_model_field_entry + "}",
            normalized,
            count=1,
        )
    else:
        normalized = normalized.rstrip() + "\n" + component_model_field_entry

    return normalized


def _infer_component_model_field(spec: FormComponentEditorSpec, content: str) -> str:
    metadata = " ".join(
        part
        for part in (
            spec.short_kebab,
            _extract_named_single_quoted_value(content, "text"),
            _extract_named_single_quoted_value(content, "description"),
        )
        if part
    ).lower()

    current_model_field = _extract_component_model_field(content)
    max_length_values = [
        int(value)
        for value in re.findall(r"(?:maxLength|maxlength|lengthLimit|textLimit)\s*:\s*(\d+)", content)
    ]
    if max_length_values and max(max_length_values) > STRING_COMPONENT_MODEL_FIELD_MAX_LENGTH:
        return "BIG_TEXT"

    big_text_keywords = (
        # 明确会产生大量字符的类型（序列化后通常 ≥ 500）
        "base64", "textarea", "rich-text", "富文本", "richtext", "html",
        "remark", "memo", "comment", "描述", "大文本",
        "upload", "文件", "file", "attachment", "附件",
        "signature", "签名",
        "chart", "图表",
    )
    # 注意：date-range / daterange / range / 多选 / address 等
    # 序列化后通常远低于 500 字符，应使用 STRING，不在此列表中
    if any(keyword in metadata for keyword in big_text_keywords):
        return "BIG_TEXT"

    # 范围类（存储 JSON 数组，序列化后 < 500 字符）→ STRING
    # 必须在 date_keywords 之前判断，防止 date-range 被误判为 DATE
    string_range_keywords = (
        "date-range", "daterange", "datetimerange", "monthrange", "yearrange",
        "timerange", "time-range", "numberrange", "number-range",
        "range-picker", "rangepicker",
    )
    if any(keyword in metadata for keyword in string_range_keywords):
        return "STRING"

    num_keywords = (
        "star", "rating", "rate", "score", "number", "amount", "price",
        "count", "percent", "progress", "slider", "stepper", "digit", "num", "评分",
    )
    if any(keyword in metadata for keyword in num_keywords):
        return "NUM"

    date_keywords = (
        "date-picker", "datepicker", "calendar", "日期", "date", "month", "year", "time",
    )
    if any(keyword in metadata for keyword in date_keywords):
        return "DATE"

    if current_model_field in SUPPORTED_COMPONENT_MODEL_FIELDS:
        return current_model_field

    return "STRING"


def _extract_component_model_field(content: str) -> str | None:
    match = re.search(r"componentModelField\s*:\s*\[\s*'([^']+)'\s*\]", content)
    if not match:
        return None
    return LEGACY_COMPONENT_MODEL_FIELD_MAP.get(match.group(1).strip().upper())
def render_widget_svg_icon(spec: FormComponentEditorSpec, content: str) -> str:
    keywords = f"{spec.short_kebab} {content}".lower()

    if any(keyword in keywords for keyword in ("date-range", "日期范围", "daterange")):
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
            '<rect x="3" y="5" width="18" height="16" rx="3" fill="#E8F1FF"/>'
            '<path d="M7 3v4M17 3v4M3 9h18" stroke="#1F6FEB" stroke-width="1.8" stroke-linecap="round"/>'
            '<rect x="6" y="12" width="4" height="4" rx="1" fill="#1F6FEB"/>'
            '<rect x="14" y="12" width="4" height="4" rx="1" fill="#7FB3FF"/>'
            '<path d="M11 14h2" stroke="#1F6FEB" stroke-width="1.8" stroke-linecap="round"/>'
            '</svg>'
        )
    if any(keyword in keywords for keyword in ("date-picker", "日期", "calendar")):
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
            '<rect x="3" y="5" width="18" height="16" rx="3" fill="#E8F1FF"/>'
            '<path d="M7 3v4M17 3v4M3 9h18" stroke="#1F6FEB" stroke-width="1.8" stroke-linecap="round"/>'
            '<rect x="7" y="12" width="10" height="6" rx="1.5" fill="#1F6FEB"/>'
            '</svg>'
        )
    if any(keyword in keywords for keyword in ("upload", "上传", "file")):
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
            '<path d="M12 4v10" stroke="#1F6FEB" stroke-width="2" stroke-linecap="round"/>'
            '<path d="M8.5 8 12 4.5 15.5 8" fill="none" stroke="#1F6FEB" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
            '<rect x="4" y="14" width="16" height="6" rx="3" fill="#DCEBFF" stroke="#1F6FEB" stroke-width="1.5"/>'
            '</svg>'
        )
    if any(keyword in keywords for keyword in ("map", "地图", "location", "picker")):
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
            '<path d="M12 21s6-5.33 6-10a6 6 0 1 0-12 0c0 4.67 6 10 6 10Z" fill="#DCEBFF" stroke="#1F6FEB" stroke-width="1.6"/>'
            '<circle cx="12" cy="11" r="2.5" fill="#1F6FEB"/>'
            '</svg>'
        )
    if any(keyword in keywords for keyword in ("qrcode", "二维码", "qr")):
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
            '<rect x="4" y="4" width="6" height="6" rx="1" fill="#1F6FEB"/>'
            '<rect x="14" y="4" width="6" height="6" rx="1" fill="#1F6FEB"/>'
            '<rect x="4" y="14" width="6" height="6" rx="1" fill="#1F6FEB"/>'
            '<rect x="15" y="15" width="2" height="2" rx=".4" fill="#7FB3FF"/>'
            '<rect x="18" y="15" width="2" height="5" rx=".4" fill="#7FB3FF"/>'
            '<rect x="15" y="18" width="5" height="2" rx=".4" fill="#7FB3FF"/>'
            '</svg>'
        )
    if any(keyword in keywords for keyword in ("rate", "rating", "评分", "star")):
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
            '<path d="m12 3.8 2.4 4.86 5.36.78-3.88 3.79.92 5.34L12 16.8l-4.8 2.52.92-5.34-3.88-3.79 5.36-.78L12 3.8Z" fill="#FFB020" stroke="#E58A00" stroke-width="1.2" stroke-linejoin="round"/>'
            '</svg>'
        )
    if any(keyword in keywords for keyword in ("color", "颜色")):
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
            '<path d="M12 4a8 8 0 1 0 0 16h1.2a2.8 2.8 0 0 0 0-5.6H12A2.4 2.4 0 1 1 12 9.6h2.4A3.6 3.6 0 0 0 18 6a2 2 0 0 0-2-2H12Z" fill="#FFF3CD" stroke="#1F6FEB" stroke-width="1.4"/>'
            '<circle cx="8" cy="10" r="1.2" fill="#FF6B6B"/>'
            '<circle cx="10.5" cy="7.5" r="1.2" fill="#FFD166"/>'
            '<circle cx="14" cy="7" r="1.2" fill="#06D6A0"/>'
            '<circle cx="16.2" cy="10.2" r="1.2" fill="#118AB2"/>'
            '</svg>'
        )
    if any(keyword in keywords for keyword in ("rich-text", "富文本", "editor")):
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
            '<rect x="4" y="5" width="16" height="14" rx="2.5" fill="#F5F9FF" stroke="#1F6FEB" stroke-width="1.5"/>'
            '<path d="M8 9h8M8 12h6M8 15h8" stroke="#1F6FEB" stroke-width="1.8" stroke-linecap="round"/>'
            '</svg>'
        )
    if any(keyword in keywords for keyword in ("tree", "组织", "级联", "cascader")):
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
            '<rect x="4" y="4" width="6" height="4" rx="1.2" fill="#1F6FEB"/>'
            '<rect x="14" y="10" width="6" height="4" rx="1.2" fill="#7FB3FF"/>'
            '<rect x="14" y="16" width="6" height="4" rx="1.2" fill="#7FB3FF"/>'
            '<path d="M10 6h2a2 2 0 0 1 2 2v10M12 12h2M12 18h2" stroke="#1F6FEB" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>'
            '</svg>'
        )
    if any(keyword in keywords for keyword in ("table", "表格", "grid", "list")):
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
            '<rect x="4" y="5" width="16" height="14" rx="2" fill="#F5F9FF" stroke="#1F6FEB" stroke-width="1.5"/>'
            '<path d="M4 10h16M10 5v14M15 5v14" stroke="#1F6FEB" stroke-width="1.4"/>'
            '</svg>'
        )
    if any(keyword in keywords for keyword in ("chart", "报表", "analysis", "统计")):
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
            '<path d="M5 19V9M12 19V5M19 19v-7" stroke="#1F6FEB" stroke-width="2.2" stroke-linecap="round"/>'
            '<path d="M4 19h16" stroke="#9DBCFD" stroke-width="1.6" stroke-linecap="round"/>'
            '</svg>'
        )
    if any(keyword in keywords for keyword in ("camera", "拍照", "image", "截图")):
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
            '<path d="M8 6h8l1.2 2H20a2 2 0 0 1 2 2v7a3 3 0 0 1-3 3H5a3 3 0 0 1-3-3v-7a2 2 0 0 1 2-2h2.8L8 6Z" fill="#E8F1FF" stroke="#1F6FEB" stroke-width="1.5"/>'
            '<circle cx="12" cy="13" r="3.2" fill="#1F6FEB"/>'
            '</svg>'
        )
    if any(keyword in keywords for keyword in ("user", "person", "人员", "avatar")):
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
            '<circle cx="12" cy="8" r="3.5" fill="#1F6FEB"/>'
            '<path d="M5 19a7 7 0 0 1 14 0" fill="#DCEBFF" stroke="#1F6FEB" stroke-width="1.6" stroke-linecap="round"/>'
            '</svg>'
        )
    if any(keyword in keywords for keyword in ("countdown", "time", "时间", "clock")):
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
            '<circle cx="12" cy="12" r="8" fill="#F5F9FF" stroke="#1F6FEB" stroke-width="1.6"/>'
            '<path d="M12 8v4l3 2" stroke="#1F6FEB" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>'
            '</svg>'
        )

    first_letter = (spec.short_kebab[:1] or "C").upper()
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<rect x="3" y="3" width="18" height="18" rx="4" fill="#E8F1FF" stroke="#1F6FEB" stroke-width="1.4"/>'
        f'<text x="12" y="16" text-anchor="middle" fill="#1F6FEB" font-size="9" font-family="Arial">{first_letter}</text>'
        '</svg>'
    )


def _resolve_widget_title(spec: FormComponentEditorSpec, content: str) -> str:
    desc_text = _extract_named_single_quoted_value(content, "text")
    display_label = _extract_widget_display_label(content)

    if _is_meaningful_widget_meta(desc_text, spec):
        return desc_text
    if _is_meaningful_widget_meta(display_label, spec):
        return display_label

    title, _ = _infer_widget_title_and_description(spec, content)
    return title


def _resolve_widget_description(spec: FormComponentEditorSpec, content: str, title: str) -> str:
    current_description = _extract_named_single_quoted_value(content, "description")
    if _is_meaningful_widget_description(current_description, spec, title):
        return current_description

    _, description = _infer_widget_title_and_description(spec, content)
    return description


def _infer_widget_title_and_description(spec: FormComponentEditorSpec, content: str) -> tuple[str, str]:
    keywords = f"{spec.short_kebab} {content}".lower()

    if any(keyword in keywords for keyword in ("date-range", "日期范围", "daterange")):
        return "日期范围选择", "支持日期范围选择与快捷区间配置"
    if any(keyword in keywords for keyword in ("chart", "analysis", "统计", "报表", "图表")):
        return "图表分析", "支持图表数据分析与可视化展示"
    if any(keyword in keywords for keyword in ("upload", "上传", "file")):
        return "文件上传", "支持文件上传、预览与删除"
    if any(keyword in keywords for keyword in ("date-picker", "日期", "calendar")):
        return "日期选择", "支持日期选择与格式配置"
    if any(keyword in keywords for keyword in ("qrcode", "二维码", "qr")):
        return "二维码", "支持二维码内容展示"
    if any(keyword in keywords for keyword in ("map", "地图", "location")):
        return "地图选点", "支持地图选点与定位展示"
    if any(keyword in keywords for keyword in ("rate", "rating", "评分", "star")):
        return "评分", "支持评分选择与展示"
    if any(keyword in keywords for keyword in ("color", "颜色")):
        return "颜色选择", "支持颜色选择与结果展示"
    if any(keyword in keywords for keyword in ("rich-text", "富文本", "editor")):
        return "富文本", "支持富文本编辑与内容展示"
    if any(keyword in keywords for keyword in ("tree", "组织", "级联", "cascader")):
        return "树形选择", "支持树形数据选择与展示"
    if any(keyword in keywords for keyword in ("table", "表格", "grid", "list")):
        return "数据表格", "支持表格数据展示"
    if any(keyword in keywords for keyword in ("camera", "拍照", "image", "截图")):
        return "拍照上传", "支持拍照采集与图片上传"
    if any(keyword in keywords for keyword in ("user", "person", "人员", "avatar")):
        return "人员选择", "支持人员选择与信息展示"
    if any(keyword in keywords for keyword in ("countdown", "time", "时间", "clock")):
        return "倒计时", "支持倒计时展示与时间配置"

    title = _humanize_short_kebab(spec.short_kebab)
    return title, f"支持{title}配置与展示"


def _extract_widget_icon(content: str) -> str:
    match = re.search(r"icon:\s*'(?P<icon>[^']*)'", content)
    if not match:
        return ""
    return match.group("icon").strip()


def _extract_widget_display_label(content: str) -> str:
    return _extract_named_single_quoted_value(content, "label")


def _extract_named_single_quoted_value(content: str, field_name: str) -> str:
    match = re.search(rf"{field_name}:\s*'(?P<value>[^']*)'", content)
    if not match:
        return ""
    return match.group("value").strip()


def _is_feature_svg_icon(icon: str) -> bool:
    normalized = (icon or "").strip()
    if not normalized:
        return False
    if normalized == "form-custom-widget":
        return False
    if "<svg" not in normalized:
        return False
    if 'font-size="10">C<' in normalized:
        return False
    return True


def _is_meaningful_widget_meta(value: str, spec: FormComponentEditorSpec) -> bool:
    normalized = (value or "").strip()
    if not normalized:
        return False

    invalid_values = {
        "demo",
        "demo component",
        "组件名称",
        "组件描述",
        "custom",
        "component",
        spec.short_kebab,
        spec.short_kebab.replace("-", " "),
    }
    if normalized.lower() in {item.lower() for item in invalid_values}:
        return False
    return True


def _is_meaningful_widget_description(value: str, spec: FormComponentEditorSpec, title: str) -> bool:
    normalized = (value or "").strip()
    if not normalized:
        return False
    invalid_values = {
        "demo component",
        "组件描述",
        title,
        f"{title}组件",
        spec.short_kebab,
        spec.short_kebab.replace("-", " "),
    }
    if normalized.lower() in {item.lower() for item in invalid_values}:
        return False
    return True


def _humanize_short_kebab(short_kebab: str) -> str:
    parts = [part for part in short_kebab.split("-") if part]
    if not parts:
        return "自定义组件"
    return "".join(part.capitalize() for part in parts)


def _escape_js_single_quoted(value: str) -> str:
    return (value or "").replace("\\", "\\\\").replace("'", "\\'")


_SCAFFOLD_PLACEHOLDER_NAMES = {"form-component-custom-dev", "form-component-demo"}


def _is_scaffold_placeholder(full_kebab: str) -> bool:
    return full_kebab in _SCAFFOLD_PLACEHOLDER_NAMES


def _pick_best_widget_file(files: list, suffix: str) -> str | None:
    """从多个 widget config 文件中选出最合适的（非脚手架占位名）。"""
    if not files:
        return None
    non_scaffold = [f for f in files if not _is_scaffold_placeholder(f.name.removesuffix(suffix))]
    target = non_scaffold[0] if non_scaffold else files[0]
    return target.name.removesuffix(suffix)


def _discover_form_component_name(workspace_path: Path) -> str | None:
    # Widget config 文件是最直接的来源（由 AI 生成，命名即语义名）
    widget_dir = workspace_path / "src" / "form-component-config" / "form-widget"
    if widget_dir.exists():
        for suffix, glob_pattern in (
            (".widget.config.json", "form-component-*.widget.config.json"),
            (".widget.config.js", "form-component-*.widget.config.js"),
        ):
            widget_files = sorted(widget_dir.glob(glob_pattern))
            if widget_files:
                name = _pick_best_widget_file(widget_files, suffix)
                if name:
                    return name

    # Setting.vue 次之
    setting_dir = workspace_path / "src" / "form-component" / "form-editor"
    if setting_dir.exists():
        setting_files = sorted(setting_dir.glob("form-component-*-setting.vue"))
        non_scaffold = [f for f in setting_files if not _is_scaffold_placeholder(f.name.removesuffix("-setting.vue"))]
        target_files = non_scaffold or setting_files
        if target_files:
            return target_files[0].name.removesuffix("-setting.vue")

    # 最后回退到 apaas.json outputName
    # outputName 格式为 form-component-custom-{semantic}，需去掉 custom- 得到组件命名用的 full_kebab
    apaas_json_path = workspace_path / "src" / "apaas.json"
    if apaas_json_path.exists():
        try:
            output_name = json.loads(apaas_json_path.read_text(encoding="utf-8")).get("outputName")
        except Exception:
            output_name = None
        if isinstance(output_name, str) and output_name.startswith(FORM_COMPONENT_PREFIX):
            short = output_name[len(FORM_COMPONENT_PREFIX):]
            # form-component-custom-xxx → form-component-xxx（剥离 custom- 包装前缀）
            if short.startswith("custom-"):
                return f"{FORM_COMPONENT_PREFIX}{short[len('custom-'):]}"
            return output_name

    return None


def _write_if_changed(path: Path, content: str) -> bool:
    existing = path.read_text(encoding="utf-8") if path.exists() else None
    if existing == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def _setting_content_score(content: str) -> int:
    score = len(content or "")
    if "在此添加配置项" in content:
        score -= 100000
    if "TODO" in content:
        score -= 1000
    if "name:" in content:
        score += 100
    if validate_setting_component_contract(content):
        score -= 50000
    return score


def _detect_array_indent(content: str) -> str | None:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("'"):
            return line[: len(line) - len(line.lstrip())]
    return None


def _ensure_last_array_item_has_comma(content: str) -> str:
    lines = content.splitlines()
    for index in range(len(lines) - 1, -1, -1):
        stripped = lines[index].strip()
        if not stripped:
            continue
        if stripped.startswith("'") and not stripped.endswith(","):
            lines[index] = f"{lines[index]},"
        break
    return "\n".join(lines)


def _remove_setting_code_lines(content: str, setting_code: str) -> str:
    lines = content.splitlines()
    filtered_lines = [
        line for line in lines
        if setting_code not in line
    ]
    return "\n".join(filtered_lines)
