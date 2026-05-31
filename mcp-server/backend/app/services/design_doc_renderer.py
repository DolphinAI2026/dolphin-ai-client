"""把配置数据（data dict）渲染成人类可读的"应用设计文档" markdown。

从 app/routes/generation_steps.py 抽出，模块内部按 section 再拆成若干纯函数：
  - _section_app_info
  - _section_roles
  - _section_dicts
  - _section_models
  - _section_forms
  - _section_workflows
  - _section_permissions
  - _section_custom_development

render(app_name, app_code, data) 是外部唯一入口，保持与原
_render_design_doc_markdown 同签名同输出（snapshot 测试覆盖）。
"""
from __future__ import annotations

from typing import Callable

from app.lowcode_standards import normalize_database_field_type


def _first_bool(*values) -> bool:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and value.strip() == "":
            continue
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"1", "true", "yes", "y", "是"}:
                return True
            if lowered in {"0", "false", "no", "n", "否"}:
                return False
        return bool(value)
    return False


def _section_app_info(app_name: str, app_code: str, data: dict) -> list[str]:
    app_description = str(data.get("description") or data.get("appDescription") or data.get("remark") or "").strip()
    return [
        "# 应用设计文档",
        "",
        "## 一、应用信息",
        "",
        "| 项目 | 内容 |",
        "|---|---|",
        f"| 应用名称 | {app_name or ''} |",
        f"| 应用编码 | {app_code or ''} |",
        f"| 说明 | {app_description} |",
        "",
        "---",
        "",
    ]


def _section_roles(roles: list[dict]) -> list[str]:
    lines = [
        "## 二、角色列表",
        "",
        "| 角色编码 | 角色名称 |",
        "|---|---|",
    ]
    if roles:
        lines.extend([f"| {r.get('code', '')} | {r.get('name', '')} |" for r in roles])
    else:
        lines.append("|  |  |")
    lines.extend(["", "---", ""])
    return lines


def _section_dicts(dicts: list[dict]) -> list[str]:
    lines = ["## 三、数据字典", ""]
    if dicts:
        for idx, item in enumerate(dicts, start=1):
            lines.extend([
                f"### 3.{idx} {item.get('name') or item.get('code') or f'字典{idx}'}",
                "",
                "| 字典编码 | 字典名称 |",
                "|---|---|",
                f"| {item.get('code', '')} | {item.get('name', '')} |",
                "",
                "| 选项编码 | 选项名称 |",
                "|---|---|",
            ])
            options = item.get("options") or item.get("values") or []
            if options:
                for option in options:
                    if isinstance(option, str):
                        lines.append(f"|  | {option} |")
                    else:
                        lines.append(f"| {option.get('code') or option.get('item_code') or ''} | {option.get('name') or option.get('item_name') or ''} |")
            else:
                lines.append("|  |  |")
            lines.append("")
    else:
        lines.append("暂无")
        lines.append("")
    lines.extend(["---", ""])
    return lines


def _section_models(models: list[dict]) -> list[str]:
    lines = ["## 四、数据模型", ""]
    if models:
        lines.extend([
            "### 4.1 模型定义",
            "",
            "| 模型编码 | 模型名称 |",
            "|---|---|",
        ])
        lines.extend([
            f"| {model.get('code', '')} | {model.get('name', '')} |"
            for model in models
        ] or ["|  |  |"])
        lines.extend([
            "",
            "### 4.2 模型字段",
            "",
            "| 模型编码 | 字段编码 | 字段名称 | 数据库字段类型 | 长度/精度 |",
            "|---|---|---|---|---|",
        ])
        model_field_rows: list[str] = []
        for model in models:
            for field in (model.get("fields") or []):
                database_field_type = (
                    field.get("database_field_type")
                    or field.get("databaseFieldType")
                    or field.get("db_type")
                    or field.get("field_type")
                    or ""
                )
                database_field_type = normalize_database_field_type(
                    database_field_type,
                    component_type=field.get("type") or field.get("componentType"),
                    field_name=str(field.get("name") or field.get("fieldName") or ""),
                )
                length_or_precision = (
                    field.get("max_length")
                    or field.get("maxLength")
                    or field.get("length")
                    or field.get("precision")
                    or ""
                )
                model_field_rows.append(
                    f"| {model.get('code', '')} | {field.get('code', '')} | {field.get('name', '')} | {database_field_type} | {length_or_precision} |"
                )
        lines.extend(model_field_rows or ["|  |  |  |  |  |"])
        lines.append("")
    else:
        lines.append("暂无")
        lines.append("")
    lines.extend(["---", ""])
    return lines


def _section_forms(
    data: dict,
    models: list[dict],
    models_by_code: dict[str, dict],
    fields_by_model: dict[str, dict],
    *,
    iter_form_definitions: Callable,
    field_code_from_model_field: Callable,
    field_ref_meta_from_component: Callable,
    component_type_label: Callable,
    bool_label: Callable,
    is_sub_table_component: Callable,
) -> tuple[list[str], dict[str, str]]:
    """返回 (lines, form_name_by_code)；form_name_by_code 供权限 section 复用。"""
    lines = ["## 五、表单定义", ""]
    form_defs = iter_form_definitions(data, models)
    form_name_by_code: dict[str, str] = {}
    if form_defs:
        form_summary_rows: list[str] = []
        main_field_rows: list[str] = []
        sub_region_rows: list[str] = []
        sub_field_rows: list[str] = []
        for idx, form in enumerate(form_defs, start=1):
            form_name = form.get("formName") or form.get("form_name") or form.get("name") or form.get("code") or f"表单{idx}"
            form_code = form.get("formCode") or form.get("form_code") or form.get("code") or ""
            model_code = form.get("modelCode") or form.get("model_code") or form.get("bindModelCode") or form.get("code") or ""
            if form_code:
                form_name_by_code[str(form_code)] = str(form_name)
            if model_code:
                form_name_by_code[str(model_code)] = str(form_name)
            form_summary_rows.append(
                f"| {form_code} | {form_name} | {model_code} | {form.get('description') or form.get('remark') or ''} |"
            )
            components = form.get("components") or form.get("formComponents") or form.get("fields") or []
            main_components = [comp for comp in components if not is_sub_table_component(comp)]
            sub_tables = [comp for comp in components if is_sub_table_component(comp)]
            if main_components:
                for component in main_components:
                    field_code = str(component.get("code") or field_code_from_model_field(component.get("modelField", ""))).strip()
                    field_meta = fields_by_model.get(str(model_code).strip(), {}).get(field_code, {})
                    ref_model_code, ref_field_code, origin_field_code = field_ref_meta_from_component(
                        component,
                        field_meta,
                        models_by_code,
                        fields_by_model,
                        form_name_by_code,
                    )
                    main_field_rows.append(
                        f"| {form_name} | {field_code} | {component.get('label') or component.get('name') or field_meta.get('name', '')} | "
                        f"{component_type_label(component.get('componentType') or component.get('component_type'), field_meta.get('type', ''))} | "
                        f"{bool_label(component.get('required'))} | {bool_label(component.get('hidden'))} | {bool_label(_first_bool(component.get('readonly'), component.get('readOnly')))} | "
                        f"{bool_label(_first_bool(component.get('showInList'), component.get('list_visible')))} | {bool_label(_first_bool(component.get('searchable'), component.get('queryable')))} | "
                        f"{component.get('dict_code') or component.get('dictCode') or component.get('dict') or field_meta.get('dict_code') or field_meta.get('dict') or ''} | {ref_model_code} | {ref_field_code} | {origin_field_code} | "
                        f"{component.get('description') or field_meta.get('description', '')} |"
                    )
            if sub_tables:
                for sub_table in sub_tables:
                    table_model_code = str(sub_table.get("tableModelCode") or sub_table.get("table_model_code") or "").strip()
                    sub_model = models_by_code.get(table_model_code, {})
                    sub_model_name = sub_model.get("name", "")
                    sub_label = sub_table.get("label") or sub_table.get("name") or sub_model_name or table_model_code
                    sub_region_rows.append(
                        f"| {form_name} | {sub_label} | {table_model_code} | {sub_table.get('description') or ''} |"
                    )
                    table_columns = sub_table.get("tableColumn") or sub_table.get("table_column") or []
                    if table_columns:
                        sub_fields = fields_by_model.get(table_model_code, {})
                        for column in table_columns:
                            column_code = str(column.get("code") or field_code_from_model_field(column.get("modelField", ""))).strip()
                            field_meta = sub_fields.get(column_code, {})
                            ref_model_code, ref_field_code, origin_field_code = field_ref_meta_from_component(
                                column,
                                field_meta,
                                models_by_code,
                                fields_by_model,
                                form_name_by_code,
                            )
                            sub_field_rows.append(
                                f"| {form_name} | {sub_label} | {column_code} | {column.get('label') or column.get('name') or field_meta.get('name', '')} | "
                                f"{component_type_label(column.get('componentType') or column.get('component_type'), field_meta.get('type', ''))} | "
                                f"{bool_label(column.get('required'))} | {bool_label(column.get('hidden'))} | {bool_label(_first_bool(column.get('readonly'), column.get('readOnly')))} | "
                                f"{bool_label(_first_bool(column.get('showInList'), column.get('list_visible')))} | {bool_label(_first_bool(column.get('searchable'), column.get('queryable')))} | "
                                f"{column.get('dict_code') or column.get('dictCode') or column.get('dict') or field_meta.get('dict_code') or field_meta.get('dict') or ''} | {ref_model_code} | {ref_field_code} | {origin_field_code} | "
                                f"{column.get('description') or field_meta.get('description', '')} |"
                            )
        lines.extend([
            "### 5.1 表单清单",
            "",
            "| 表单编码 | 表单名称 | 绑定主表模型 | 说明 |",
            "|---|---|---|---|",
        ])
        lines.extend(form_summary_rows or ["|  |  |  |  |"])
        lines.extend([
            "",
            "### 5.2 主表字段定义",
            "",
            "| 表单名称 | 字段编码 | 字段名称 | 组件类型 | 必填 | 隐藏 | 只读 | 列表展示 | 查询条件 | 字典编码 | 目标模型编码 | 目标字段编码 | 本表关联字段编码 | 说明 |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        ])
        lines.extend(main_field_rows or ["|  |  |  |  | 否 | 否 | 否 | 否 | 否 |  |  |  |  |  |"])
        lines.extend([
            "",
            "### 5.3 子表区域定义",
            "",
            "| 表单名称 | 子表区域名称 | 绑定模型 | 说明 |",
            "|---|---|---|---|",
        ])
        lines.extend(sub_region_rows or ["|  |  |  |  |"])
        lines.extend([
            "",
            "### 5.4 子表字段定义",
            "",
            "| 表单名称 | 子表区域名称 | 字段编码 | 字段名称 | 组件类型 | 必填 | 隐藏 | 只读 | 列表展示 | 查询条件 | 字典编码 | 目标模型编码 | 目标字段编码 | 本表关联字段编码 | 说明 |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        ])
        lines.extend(sub_field_rows or ["|  |  |  |  |  | 否 | 否 | 否 | 否 | 否 |  |  |  |  |  |"])
    else:
        lines.append("暂无")
        lines.append("")

    lines.extend(["---", ""])
    return lines, form_name_by_code


def _section_permissions(
    permissions: list[dict],
    form_name_by_code: dict[str, str],
    *,
    data_scope_label: Callable,
) -> list[str]:
    lines = [
        "## 七、权限定义",
        "",
        "| 表单名称 | 角色编码 | 可暂存 | 可新增 | 可导入 | 可查看 | 可编辑 | 可删除 | 可导出 | 数据范围 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    if permissions:
        for perm in permissions:
            form_code = perm.get("form_code") or perm.get("table_code") or perm.get("code") or perm.get("form") or ""
            form_name = form_name_by_code.get(form_code) or form_code
            role_rows = perm.get("roles") or perm.get("rules") or perm.get("permissions") or []
            if not role_rows:
                lines.append(f"| {form_name} |  | 否 | 否 | 否 | 否 | 否 | 否 | 否 |  |")
                continue
            for role in role_rows:
                raw_actions = role.get("actions") or role.get("operations") or role.get("permissions") or role.get("op") or []
                if isinstance(raw_actions, str):
                    actions = {item.strip() for item in raw_actions.split(",") if item.strip()}
                else:
                    actions = {str(action).strip() for action in raw_actions}
                is_all = "all" in actions
                can_draft = bool(role.get("canDraft")) or "draft" in actions or "stash" in actions or "save" in actions
                can_import = bool(role.get("canImport")) or "import" in actions
                can_export = bool(role.get("canExport")) or "export" in actions
                lines.append(
                    f"| {form_name} | {role.get('role_code') or role.get('roleCode') or role.get('code') or role.get('role') or ''} | "
                    f"{'是' if can_draft else '否'} | "
                    f"{'是' if is_all or 'add' in actions or '新增' in actions or 'create' in actions else '否'} | "
                    f"{'是' if can_import else '否'} | "
                    f"{'是' if is_all or 'view' in actions or '查看' in actions or 'read' in actions else '否'} | "
                    f"{'是' if is_all or 'edit' in actions or '编辑' in actions or 'update' in actions else '否'} | "
                    f"{'是' if is_all or 'delete' in actions or '删除' in actions else '否'} | "
                    f"{'是' if can_export else '否'} | "
                    f"{data_scope_label(role.get('data_scope') or role.get('scope') or role.get('dataScope') or role.get('data') or '')} |"
                )
    else:
        lines.append("|  |  | 否 | 否 | 否 | 否 | 否 | 否 | 否 |  |")
    lines.extend(["", "---", ""])
    return lines


def _section_workflows(workflows: list[dict]) -> list[str]:
    lines = ["## 六、流程配置", ""]
    if workflows:
        for idx, flow in enumerate(workflows, start=1):
            flow_name = flow.get("name") or flow.get("flow_name") or flow.get("workflowName") or f"流程{idx}"
            flow_code = flow.get("code") or flow.get("flow_code") or flow.get("workflowCode") or ""
            flow_desc = flow.get("description") or flow.get("remark") or ""
            lines.extend([
                f"### {flow_name}（{flow_code or '-'}）",
                "",
            ])
            if flow_desc:
                lines.extend([str(flow_desc), ""])
            lines.extend([
                "| 步骤 | 动作 | 角色 | 状态/结果 |",
                "|---|---|---|---|",
            ])
            steps = flow.get("steps") or flow.get("nodes") or flow.get("actions") or []
            if steps:
                for step_idx, step in enumerate(steps, start=1):
                    lines.append(
                        f"| {step.get('step') or step.get('order') or step_idx} | "
                        f"{step.get('action') or step.get('name') or step.get('label') or ''} | "
                        f"{step.get('role') or step.get('assignee') or ''} | "
                        f"{step.get('status') or step.get('result') or ''} |"
                    )
            else:
                lines.append("|  |  |  |  |")
            lines.append("")
    else:
        lines.extend([
            "暂无流程配置；默认先按表单的基础新增、查看、编辑和权限控制闭环。",
            "",
        ])
    lines.extend(["---", ""])
    return lines


def _normalize_custom_development_items(data: dict) -> list[dict[str, str]]:
    source = (
        data.get("custom_development")
        or data.get("customDevelopment")
        or data.get("custom_dev")
        or []
    )
    if isinstance(source, dict):
        source = source.get("items") or source.get("tasks") or source.get("features") or []
    if not isinstance(source, list):
        source = []

    items: list[dict[str, str]] = []
    for idx, item in enumerate(source):
        if not isinstance(item, dict):
            continue
        deliverables = item.get("deliverables") or item.get("deliverable") or ""
        if isinstance(deliverables, list):
            deliverables_text = "、".join(str(value) for value in deliverables if str(value).strip())
        else:
            deliverables_text = str(deliverables or "").strip()
        items.append({
            "type": str(item.get("type") or item.get("scene") or item.get("category") or "自开发扩展").strip(),
            "name": str(item.get("name") or item.get("item_name") or item.get("title") or f"自开发项 {idx + 1}").strip(),
            "trigger": str(item.get("trigger") or item.get("reason") or item.get("condition") or item.get("description") or "配置能力无法完整覆盖").strip(),
            "scope": str(item.get("scope") or item.get("implementation") or deliverables_text or "在 IDE 中实现并回写项目上下文").strip(),
            "acceptance": str(item.get("acceptance") or item.get("acceptance_criteria") or item.get("test") or "完成源码、联调和可演示验证").strip(),
        })

    return items or [{
        "type": "配置优先",
        "name": "暂无强制自开发项",
        "trigger": "当前需求可先由模型、表单、权限和基础流程配置覆盖",
        "scope": "如后续出现复杂交互、外部接口、算法规则或报表看板，再进入 IDE 补充",
        "acceptance": "低代码配置可完成主流程演示",
    }]


def _section_custom_development(data: dict) -> list[str]:
    lines = [
        "## 八、自开发定义",
        "",
        "| 类型 | 名称 | 触发条件 | 实现范围 | 验收口径 |",
        "|---|---|---|---|---|",
    ]
    for item in _normalize_custom_development_items(data):
        lines.append(
            f"| {item['type']} | {item['name']} | {item['trigger']} | {item['scope']} | {item['acceptance']} |"
        )
    lines.append("")
    return lines


def render(
    app_name: str,
    app_code: str,
    data: dict,
    *,
    build_model_maps: Callable,
    iter_form_definitions: Callable,
    field_code_from_model_field: Callable,
    field_ref_meta_from_component: Callable,
    component_type_label: Callable,
    bool_label: Callable,
    is_sub_table_component: Callable,
    data_scope_label: Callable,
) -> str:
    """渲染设计文档 markdown。

    通过关键字传入的 Callable 是 generation_steps.py 中的既有 helper
    （保持与原逻辑 1:1 等价；将这些 helper 进一步搬出是后续批次工作）。
    """
    roles = data.get("roles", []) or []
    dicts = data.get("dicts", []) or []
    models = data.get("models", []) or []
    workflows = data.get("workflows") or data.get("flows") or []
    permissions = data.get("permissions", []) or []
    models_by_code, fields_by_model = build_model_maps(models)

    lines: list[str] = []
    lines.extend(_section_app_info(app_name, app_code, data))
    lines.extend(_section_roles(roles))
    lines.extend(_section_dicts(dicts))
    lines.extend(_section_models(models))
    form_lines, form_name_by_code = _section_forms(
        data,
        models,
        models_by_code,
        fields_by_model,
        iter_form_definitions=iter_form_definitions,
        field_code_from_model_field=field_code_from_model_field,
        field_ref_meta_from_component=field_ref_meta_from_component,
        component_type_label=component_type_label,
        bool_label=bool_label,
        is_sub_table_component=is_sub_table_component,
    )
    lines.extend(form_lines)
    lines.extend(_section_workflows(workflows))
    lines.extend(_section_permissions(
        permissions,
        form_name_by_code,
        data_scope_label=data_scope_label,
    ))
    lines.extend(_section_custom_development(data))

    return "\n".join(lines).strip() + "\n"
