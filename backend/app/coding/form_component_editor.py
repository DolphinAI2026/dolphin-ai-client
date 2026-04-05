from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


FORM_COMPONENT_PREFIX = "form-component-"


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
        return f"src/form-component-config/form-editor/{self.full_kebab}.editor.config.js"

    @property
    def editor_config_index_path(self) -> str:
        return "src/form-component-config/form-editor/index.js"

    @property
    def widget_config_file_path(self) -> str:
        return f"src/form-component-config/form-widget/{self.full_kebab}.widget.config.js"

    @property
    def legacy_setting_file_path(self) -> str:
        return "src/form-component/form-editor/setting.vue"

    @property
    def misplaced_setting_file_path(self) -> str:
        return f"src/form-component-config/form-widget/setting/{self.full_kebab}-setting.vue"


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
        setting_code=f"FORM_CUSTOM_COMPONENT_{short_kebab.replace('-', '_').upper()}_SETTING",
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
    elif normalized_path == spec.misplaced_setting_file_path:
        normalized_path = spec.setting_file_path
    elif normalized_path.startswith("src/form-component/form-editor/") and normalized_path.endswith("-setting.vue"):
        normalized_path = spec.setting_file_path
    elif normalized_path.startswith("src/form-component-config/form-editor/") and normalized_path.endswith(".editor.config.js"):
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
    for candidate in (
        target_setting_path,
        workspace_path / spec.legacy_setting_file_path,
        workspace_path / spec.misplaced_setting_file_path,
    ):
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
    ):
        if _write_if_changed(workspace_path / file_path, content):
            changed_files.append(file_path)

    widget_config_path = workspace_path / spec.widget_config_file_path
    if widget_config_path.exists():
        widget_config_content = widget_config_path.read_text(encoding="utf-8")
        normalized_widget_config_content = normalize_widget_config_content(spec, widget_config_content)
        if _write_if_changed(widget_config_path, normalized_widget_config_content):
            changed_files.append(spec.widget_config_file_path)

    for extra in (
        workspace_path / spec.legacy_setting_file_path,
        workspace_path / spec.misplaced_setting_file_path,
    ):
        if extra.exists() and extra != target_setting_path:
            extra.unlink()
            changed_files.append(str(extra.relative_to(workspace_path)))

    editor_config_dir = workspace_path / "src/form-component-config/form-editor"
    if editor_config_dir.exists():
        for extra in editor_config_dir.glob("*.editor.config.js"):
            if extra.name != Path(spec.editor_config_file_path).name:
                extra.unlink()
                changed_files.append(str(extra.relative_to(workspace_path)))

    return list(dict.fromkeys(changed_files))


def render_form_component_editor_index(spec: FormComponentEditorSpec) -> str:
    return (
        f"import {spec.setting_component_name} from './{spec.full_kebab}-setting.vue'\n\n"
        "const customFormEditorList = [\n"
        f"  {spec.setting_component_name}\n"
        "]\n\n"
        "export default customFormEditorList\n"
    )


def render_form_component_editor_config(spec: FormComponentEditorSpec) -> str:
    return (
        f"const {spec.editor_config_name} = {{\n"
        f"  code: '{spec.setting_code}',\n"
        f"  editorConfigType: '{spec.setting_code}',\n"
        f"  componentName: '{spec.setting_component_name}',\n"
        "  configProperty: 'customComponentConfig'\n"
        "}\n\n"
        f"export default {spec.editor_config_name}\n"
    )


def render_form_component_editor_config_index(spec: FormComponentEditorSpec) -> str:
    return (
        f"import {spec.editor_config_name} from './{spec.full_kebab}.editor.config'\n\n"
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
      <!-- 在此添加配置项，使用 v-model + @change=\"saveConfig\" -->
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
  data() {{
    return {{
      localConfig: {{}}
    }}
  }},
  computed: {{
    widgetObj() {{
      return this.componentConfig || this.widget || {{}}
    }},
    engine() {{
      if (this.formEngine) return this.formEngine
      if (this.renderGlobal) return this.renderGlobal
      return null
    }}
  }},
  created() {{
    const saved = this.widgetObj.customComponentConfig || {{}}
    Object.keys(this.localConfig).forEach(key => {{
      if (saved[key] !== undefined) this.localConfig[key] = saved[key]
    }})
  }},
  methods: {{
    saveConfig() {{
      this.$set(this.widgetObj, 'customComponentConfig', {{ ...this.localConfig }})
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
    return strip_setting_outer_padding(normalized)


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
    normalized = normalize_widget_config_setting_code(content, spec.setting_code)
    normalized = normalize_widget_config_icon(spec, normalized)
    return normalize_widget_config_labels(spec, normalized)


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


def _discover_form_component_name(workspace_path: Path) -> str | None:
    widget_dir = workspace_path / "src" / "form-component-config" / "form-widget"
    if widget_dir.exists():
        widget_files = sorted(widget_dir.glob("form-component-*.widget.config.js"))
        if widget_files:
            return widget_files[0].name.removesuffix(".widget.config.js")

    setting_dir = workspace_path / "src" / "form-component" / "form-editor"
    if setting_dir.exists():
        setting_files = sorted(setting_dir.glob("form-component-*-setting.vue"))
        if setting_files:
            return setting_files[0].name.removesuffix("-setting.vue")

    apaas_json_path = workspace_path / "src" / "apaas.json"
    if apaas_json_path.exists():
        try:
            output_name = json.loads(apaas_json_path.read_text(encoding="utf-8")).get("outputName")
        except Exception:
            output_name = None
        if isinstance(output_name, str) and output_name.startswith(FORM_COMPONENT_PREFIX):
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
