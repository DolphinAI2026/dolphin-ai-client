"""Preflight checks for generated builder design documents.

The requirements flow should not hand an invalid design doc to the platform
builder. These checks catch the failures that usually surface much later during
deployment, especially duplicate or reserved model/field codes.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from app.config_validator import RESERVED_FIELD_CODES
from app.lowcode_standards import ALLOWED_DATABASE_FIELD_TYPES, normalize_database_field_type


CODE_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")

# Conservative SQL/platform identifiers. Some are not reserved by every
# database, but they are poor business field names and have caused platform
# deployment failures before.
DATABASE_RESERVED_CODES = {
    *RESERVED_FIELD_CODES,
    "add",
    "all",
    "alter",
    "and",
    "as",
    "by",
    "check",
    "column",
    "create",
    "current_date",
    "current_time",
    "database",
    "date",
    "default",
    "delete",
    "desc",
    "distinct",
    "drop",
    "exists",
    "false",
    "from",
    "group",
    "having",
    "index",
    "insert",
    "into",
    "is",
    "join",
    "key",
    "like",
    "limit",
    "not",
    "null",
    "on",
    "or",
    "order",
    "primary",
    "select",
    "set",
    "table",
    "then",
    "true",
    "union",
    "unique",
    "update",
    "user",
    "values",
    "view",
    "where",
}


@dataclass
class DesignDocIssue:
    severity: str
    code: str
    target_type: str
    target_name: str
    current_code: str
    message: str
    suggestion: str = ""


@dataclass
class DesignDocPreflightResult:
    blocking_issues: list[DesignDocIssue]
    warnings: list[DesignDocIssue]
    assistant_message: str

    @property
    def ok(self) -> bool:
        return not self.blocking_issues

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "needs_user_input": not self.ok,
            "assistant_message": self.assistant_message,
            "blocking_issues": [asdict(issue) for issue in self.blocking_issues],
            "warnings": [asdict(issue) for issue in self.warnings],
        }


def validate_design_doc_preflight(doc_result: dict[str, Any]) -> DesignDocPreflightResult:
    """Validate a normalized requirements ``doc_result`` before MD/app creation."""
    blocking: list[DesignDocIssue] = []
    warnings: list[DesignDocIssue] = []

    _check_roles(doc_result, warnings)
    _check_dicts(doc_result, warnings)
    _check_tables(doc_result, blocking, warnings)
    _check_forms(doc_result, blocking, warnings)
    _check_permissions(doc_result, warnings)

    return DesignDocPreflightResult(
        blocking_issues=blocking,
        warnings=warnings,
        assistant_message=_build_assistant_message(blocking, warnings),
    )


def _normalized_code(value: Any) -> str:
    return str(value or "").strip().lower()


def _suggest_code(base: str, *, prefix: str = "", suffix: str = "") -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]+", "_", str(base or "")).strip("_").lower()
    cleaned = re.sub(r"_+", "_", cleaned)
    if not cleaned or not re.match(r"^[a-zA-Z]", cleaned):
        cleaned = "business_record"
    if prefix and not cleaned.startswith(prefix):
        cleaned = f"{prefix}{cleaned}"
    if suffix and not cleaned.endswith(suffix):
        cleaned = f"{cleaned}{suffix}"
    if cleaned in DATABASE_RESERVED_CODES:
        cleaned = f"{cleaned}_value"
    return cleaned[:48].strip("_") or "business_record"


def _issue(
    collection: list[DesignDocIssue],
    *,
    severity: str,
    code: str,
    target_type: str,
    target_name: str,
    current_code: str,
    message: str,
    suggestion: str = "",
) -> None:
    collection.append(
        DesignDocIssue(
            severity=severity,
            code=code,
            target_type=target_type,
            target_name=target_name,
            current_code=current_code,
            message=message,
            suggestion=suggestion,
        )
    )


def _check_code_format(
    *,
    value: str,
    name: str,
    target_type: str,
    collection: list[DesignDocIssue],
    prefix: str = "",
) -> None:
    if not value:
        _issue(
            collection,
            severity="blocking",
            code=f"{target_type}_code_missing",
            target_type=target_type,
            target_name=name,
            current_code=value,
            message=f"{target_type}「{name}」缺少编码。",
            suggestion=_suggest_code(name, prefix=prefix),
        )
        return
    if not CODE_RE.match(value):
        _issue(
            collection,
            severity="blocking",
            code=f"{target_type}_code_invalid",
            target_type=target_type,
            target_name=name,
            current_code=value,
            message=f"{target_type}「{name}」的编码 `{value}` 不合规，需要以英文字母开头，只包含字母、数字和下划线。",
            suggestion=_suggest_code(value or name, prefix=prefix),
        )


def _check_roles(doc_result: dict[str, Any], warnings: list[DesignDocIssue]) -> None:
    seen: dict[str, str] = {}
    for role in doc_result.get("roles") or []:
        if not isinstance(role, dict):
            continue
        code = _normalized_code(role.get("role_code") or role.get("code"))
        name = str(role.get("role_name") or role.get("name") or code).strip()
        if not code:
            continue
        if code in seen:
            _issue(
                warnings,
                severity="warning",
                code="role_code_duplicate",
                target_type="role",
                target_name=name,
                current_code=code,
                message=f"角色编码 `{code}` 在「{seen[code]}」和「{name}」中重复，建议合并或改名。",
                suggestion=_suggest_code(f"{code}_role"),
            )
        seen[code] = name


def _check_dicts(doc_result: dict[str, Any], warnings: list[DesignDocIssue]) -> None:
    seen_dicts: dict[str, str] = {}
    for dictionary in doc_result.get("data_dictionary") or []:
        if not isinstance(dictionary, dict):
            continue
        code = _normalized_code(dictionary.get("dict_code") or dictionary.get("code"))
        name = str(dictionary.get("dict_name") or dictionary.get("name") or code).strip()
        if not code:
            continue
        if code in seen_dicts:
            _issue(
                warnings,
                severity="warning",
                code="dict_code_duplicate",
                target_type="dict",
                target_name=name,
                current_code=code,
                message=f"字典编码 `{code}` 重复，建议调整后再生成。",
                suggestion=_suggest_code(f"{code}_dict"),
            )
        seen_dicts[code] = name

        seen_items: dict[str, str] = {}
        for item in dictionary.get("items") or []:
            if not isinstance(item, dict):
                continue
            item_code = _normalized_code(item.get("item_code") or item.get("code"))
            item_name = str(item.get("item_name") or item.get("name") or item_code).strip()
            if item_code and item_code in seen_items:
                _issue(
                    warnings,
                    severity="warning",
                    code="dict_item_code_duplicate",
                    target_type="dict_item",
                    target_name=f"{name}/{item_name}",
                    current_code=item_code,
                    message=f"字典「{name}」的选项编码 `{item_code}` 重复。",
                    suggestion=_suggest_code(f"{item_code}_item"),
                )
            seen_items[item_code] = item_name


def _check_tables(
    doc_result: dict[str, Any],
    blocking: list[DesignDocIssue],
    warnings: list[DesignDocIssue],
) -> None:
    seen_tables: dict[str, str] = {}
    for table in doc_result.get("tables") or []:
        if not isinstance(table, dict):
            continue
        table_code = _normalized_code(table.get("table_code") or table.get("code"))
        table_name = str(table.get("table_name") or table.get("name") or table_code).strip()
        _check_code_format(
            value=table_code,
            name=table_name,
            target_type="model",
            collection=blocking,
            prefix="t_",
        )
        bare_code = table_code.removeprefix("t_")
        if table_code in DATABASE_RESERVED_CODES or bare_code in DATABASE_RESERVED_CODES:
            _issue(
                blocking,
                severity="blocking",
                code="model_code_reserved",
                target_type="model",
                target_name=table_name,
                current_code=table_code,
                message=f"模型「{table_name}」的编码 `{table_code}` 与数据库/平台保留字冲突。",
                suggestion=_suggest_code(f"{bare_code}_record", prefix="t_"),
            )
        if table_code in seen_tables:
            _issue(
                blocking,
                severity="blocking",
                code="model_code_conflict",
                target_type="model",
                target_name=table_name,
                current_code=table_code,
                message=f"模型编码 `{table_code}` 在「{seen_tables[table_code]}」和「{table_name}」中重复。",
                suggestion=_suggest_code(f"{table_code}_2", prefix="t_"),
            )
        seen_tables[table_code] = table_name
        _check_fields(table, blocking, warnings)


def _check_fields(
    table: dict[str, Any],
    blocking: list[DesignDocIssue],
    warnings: list[DesignDocIssue],
) -> None:
    table_code = _normalized_code(table.get("table_code") or table.get("code"))
    table_name = str(table.get("table_name") or table.get("name") or table_code).strip()
    seen_fields: dict[str, str] = {}
    for field in table.get("fields") or []:
        if not isinstance(field, dict):
            continue
        field_code = _normalized_code(field.get("field_code") or field.get("code"))
        field_name = str(field.get("field_name") or field.get("name") or field_code).strip()
        _check_code_format(
            value=field_code,
            name=f"{table_name}.{field_name}",
            target_type="field",
            collection=blocking,
        )
        if field_code in DATABASE_RESERVED_CODES:
            _issue(
                blocking,
                severity="blocking",
                code="field_code_reserved",
                target_type="field",
                target_name=f"{table_name}.{field_name}",
                current_code=field_code,
                message=f"模型「{table_name}」字段「{field_name}」的编码 `{field_code}` 与数据库/平台保留字段冲突。",
                suggestion=_suggest_code(f"{table_code.removeprefix('t_')}_{field_code}_value"),
            )
        if field_code in seen_fields:
            _issue(
                blocking,
                severity="blocking",
                code="field_code_conflict",
                target_type="field",
                target_name=f"{table_name}.{field_name}",
                current_code=field_code,
                message=f"模型「{table_name}」字段编码 `{field_code}` 在「{seen_fields[field_code]}」和「{field_name}」中重复。",
                suggestion=_suggest_code(f"{field_code}_2"),
            )
        seen_fields[field_code] = field_name
        raw_db_type = (
            field.get("database_field_type")
            or field.get("databaseFieldType")
            or field.get("data_type")
            or field.get("type")
            or ""
        )
        normalized_db_type = normalize_database_field_type(raw_db_type, field_name=field_name)
        if normalized_db_type not in ALLOWED_DATABASE_FIELD_TYPES:
            _issue(
                blocking,
                severity="blocking",
                code="field_database_type_invalid",
                target_type="field",
                target_name=f"{table_name}.{field_name}",
                current_code=field_code,
                message=(
                    f"模型「{table_name}」字段「{field_name}」的数据库字段类型 `{raw_db_type}` "
                    "不符合低代码规范。"
                ),
                suggestion="varchar/text/datetime/date/decimal/int/bigint",
            )
        elif raw_db_type and str(raw_db_type).strip().lower() != normalized_db_type:
            _issue(
                warnings,
                severity="warning",
                code="field_database_type_normalized",
                target_type="field",
                target_name=f"{table_name}.{field_name}",
                current_code=field_code,
                message=f"字段「{field_name}」的数据库字段类型 `{raw_db_type}` 会按规范归一为 `{normalized_db_type}`。",
                suggestion=normalized_db_type,
            )

    main_fields = [
        field for field in (table.get("fields") or [])
        if isinstance(field, dict) and _normalized_code(field.get("field_code") or field.get("code"))
    ]
    if str(table.get("table_type", "主表")).lower() not in {"子表", "sub", "child"} and len(main_fields) < 6:
        _issue(
            warnings,
            severity="warning",
            code="model_fields_too_few",
            target_type="model",
            target_name=table_name,
            current_code=table_code,
            message=f"主模型「{table_name}」字段少于 6 个，可能不足以支撑业务表单。",
            suggestion="补充核心业务字段",
        )


def _check_forms(
    doc_result: dict[str, Any],
    blocking: list[DesignDocIssue],
    warnings: list[DesignDocIssue],
) -> None:
    model_codes = {
        _normalized_code(table.get("table_code") or table.get("code"))
        for table in (doc_result.get("tables") or [])
        if isinstance(table, dict)
    }
    seen_forms: dict[str, str] = {}
    for form in doc_result.get("forms") or []:
        if not isinstance(form, dict):
            continue
        form_code = _normalized_code(form.get("form_code") or form.get("code"))
        form_name = str(form.get("form_name") or form.get("name") or form_code).strip()
        model_code = _normalized_code(form.get("model_code") or form.get("modelCode"))
        if form_code and form_code in seen_forms:
            _issue(
                blocking,
                severity="blocking",
                code="form_code_conflict",
                target_type="form",
                target_name=form_name,
                current_code=form_code,
                message=f"表单编码 `{form_code}` 在「{seen_forms[form_code]}」和「{form_name}」中重复。",
                suggestion=_suggest_code(f"{form_code}_form"),
            )
        if form_code:
            seen_forms[form_code] = form_name
        if model_code and model_code not in model_codes:
            _issue(
                warnings,
                severity="warning",
                code="form_model_missing",
                target_type="form",
                target_name=form_name,
                current_code=model_code,
                message=f"表单「{form_name}」绑定的模型编码 `{model_code}` 不存在。",
                suggestion="检查表单绑定模型",
            )


def _check_permissions(doc_result: dict[str, Any], warnings: list[DesignDocIssue]) -> None:
    role_codes = {
        _normalized_code(role.get("role_code") or role.get("code"))
        for role in (doc_result.get("roles") or [])
        if isinstance(role, dict)
    }
    table_codes = {
        _normalized_code(table.get("table_code") or table.get("code"))
        for table in (doc_result.get("tables") or [])
        if isinstance(table, dict)
    }
    for mapping in doc_result.get("role_table_mapping") or []:
        if not isinstance(mapping, dict):
            continue
        table_code = _normalized_code(mapping.get("table_code") or mapping.get("form_code"))
        if table_code and table_code not in table_codes:
            _issue(
                warnings,
                severity="warning",
                code="permission_table_missing",
                target_type="permission",
                target_name=table_code,
                current_code=table_code,
                message=f"权限矩阵引用的模型编码 `{table_code}` 不存在。",
                suggestion="检查权限表对应模型",
            )
        for permission in mapping.get("permissions") or []:
            if not isinstance(permission, dict):
                continue
            role_code = _normalized_code(permission.get("role_code") or permission.get("role"))
            if role_code and role_code != "all_employee" and role_code not in role_codes:
                _issue(
                    warnings,
                    severity="warning",
                    code="permission_role_missing",
                    target_type="permission",
                    target_name=role_code,
                    current_code=role_code,
                    message=f"权限矩阵引用的角色编码 `{role_code}` 不在角色列表中。",
                    suggestion="检查角色列表或权限矩阵",
                )


def _build_assistant_message(
    blocking: list[DesignDocIssue],
    warnings: list[DesignDocIssue],
) -> str:
    if not blocking:
        if warnings:
            preview = "；".join(issue.message for issue in warnings[:3])
            return f"设计文档预检通过，但有可优化项：{preview}"
        return "设计文档预检通过。"

    lines = ["生成标准 MD 前我发现编码冲突，需要先确认，避免后续创建应用失败："]
    for idx, issue in enumerate(blocking[:6], 1):
        suggestion = f" 建议：`{issue.suggestion}`。" if issue.suggestion else ""
        if issue.target_type == "model":
            lines.append(f"{idx}. {issue.message}{suggestion}请给这个模型一个新的英文编码。")
        elif issue.target_type == "field":
            lines.append(f"{idx}. {issue.message}{suggestion}请给这个字段一个新的英文编码。")
        else:
            lines.append(f"{idx}. {issue.message}{suggestion}")
    if len(blocking) > 6:
        lines.append(f"另外还有 {len(blocking) - 6} 个编码问题，我会在前面几个确认后继续处理。")
    lines.append("请直接回复新的编码，例如：`报销申请模型用 expense_request，状态字段用 request_status`。")
    return "\n".join(lines)
