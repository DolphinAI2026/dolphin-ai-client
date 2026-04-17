"""applications 子 package 的共享 helper 集合。

从 __init__.py 抽出（原 L40-815，776 行），供：
- __init__.py 的 CRUD 路由直接 import
- generate.py / docs.py / change_plans.py 通过 `from ._helpers import _xxx` 使用
- 外部引用（如 generation_steps.py 的 `from app.routes.applications import _dump_preview_config`）
  通过 __init__.py 的 re-export 保持兼容
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, Application, DocumentVersion, PlatformEnv, ConfigSnapshot, Conversation
from app.schemas import ApplicationResponse, MergedAppResponse
from app.config import settings, APP_DEPLOY_ABSTRACT
from app.json_utils import loads_if_str
from app.crypto import decrypt_password
from app.apaas_client import APaaSClient

logger = logging.getLogger(__name__)

__all__ = [
    "_DEFAULT_APP_NAMES",
    "_LOCAL_STATUS_MAP",
    "_REMOTE_STATUS_MAP",
    "_bind_pending_doc_versions_to_app",
    "_build_apaas_url",
    "_build_linked",
    "_build_local",
    "_build_remote",
    "_compact_permission_rule",
    "_compact_preview_payload",
    "_component_data_selection_meta_is_stale",
    "_component_type_mismatch_is_stale",
    "_doc_content_looks_like_template",
    "_dump_parsed_config",
    "_dump_preview_config",
    "_enrich",
    "_ensure_doc_version_parsed_config",
    "_ensure_doc_version_rendered_content",
    "_fallback_generated_icon",
    "_infer_app_name_from_doc",
    "_normalize_app_code",
    "_normalize_doc_compare_text",
    "_parsed_config_is_stale",
    "_preview_data",
    "_render_doc_content_from_config",
    "_resolve_builder_llm_cfg",
    "_resolve_display_status",
    "_sync_canonical_config_to_current_doc_version",
]


def _normalize_app_code(candidate: str | None) -> str:
    import re

    raw = str(candidate or "").strip().replace("_", "-")
    raw = re.sub(r"[^A-Za-z0-9-]", "", raw)
    raw = re.sub(r"-{2,}", "-", raw).strip("-")
    if raw and raw[0].isalpha():
        return raw
    return ""


# ── 应用名推断 ──────────────────────────────────────────────
# LLM 解析结果里常见的"默认值"集合。遇到这些值时认为解析没有提取出真实应用名，
# 此时改从文档标题/正文推断，推断不到才退回文件名。
_DEFAULT_APP_NAMES = {"业务应用", "应用", "未命名应用", ""}


def _infer_app_name_from_doc(text: str, filename: str = "") -> str:
    """从文档正文或文件名里推断应用名称。

    策略：
      1. 扫文档正文，取第一行包含"系统"或"应用"且 ≤ 32 字的行作为应用名；
         跳过常见的章节/目录噪声（"设计说明书"、"修订记录"、"目录"、"功能设计"）。
      2. 命中不到时退回文件名（剥掉常见后缀 / 分隔符）。
    返回空串表示推断失败，由调用方决定兜底值。
    """
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        cleaned = stripped.strip("*# ").strip()
        if not cleaned:
            continue
        if any(token in cleaned for token in ("设计说明书", "修订记录", "目录", "功能设计")):
            continue
        if len(cleaned) <= 32 and ("系统" in cleaned or "应用" in cleaned):
            return cleaned

    name = (filename or "").replace('.md', '').replace('-', ' ').replace('_', ' ')
    for suffix in ('功能设计', '设计文档', '需求文档', '设计', '配置文档'):
        name = name.replace(suffix, '')
    return name.strip()


def _compact_permission_rule(rule: dict) -> dict:
    compact_rule = {
        "role": rule.get("role") or rule.get("roleCode") or rule.get("role_code"),
        "roleCode": rule.get("roleCode") or rule.get("role_code") or rule.get("role"),
        "roleName": rule.get("roleName") or rule.get("role_name") or rule.get("role"),
        "op": rule.get("op"),
        "data": rule.get("data") or rule.get("dataScope") or rule.get("data_scope"),
    }
    if "canDraft" in rule:
        compact_rule["canDraft"] = bool(rule.get("canDraft"))
    if "canImport" in rule:
        compact_rule["canImport"] = bool(rule.get("canImport"))
    if "canExport" in rule:
        compact_rule["canExport"] = bool(rule.get("canExport"))

    actions = rule.get("actions")
    if isinstance(actions, list) and actions:
        compact_rule["actions"] = actions

    return {k: v for k, v in compact_rule.items() if v not in (None, "", [])}


def _compact_preview_payload(config: dict | None) -> dict:
    if not isinstance(config, dict):
        return {}

    data = config.get("data", config)
    if not isinstance(data, dict):
        return {}

    def _compact_model_field(field: dict) -> dict:
        compact_field = {
            "code": field.get("code"),
            "name": field.get("name"),
            "type": field.get("type"),
        }
        if field.get("database_field_type") or field.get("databaseFieldType"):
            compact_field["database_field_type"] = field.get("database_field_type") or field.get("databaseFieldType")
        if field.get("max_length") or field.get("maxLength") or field.get("length"):
            compact_field["max_length"] = field.get("max_length") or field.get("maxLength") or field.get("length")
            compact_field["length"] = field.get("length") or field.get("max_length") or field.get("maxLength")
        if field.get("dict") or field.get("dictCode"):
            compact_field["dict"] = field.get("dict") or field.get("dictCode")
        if field.get("ref"):
            compact_field["ref"] = field.get("ref")
        if field.get("required") is True:
            compact_field["required"] = True
        if field.get("comment") or field.get("description"):
            compact_field["comment"] = field.get("comment") or field.get("description")
        if field.get("sub_code"):
            compact_field["sub_code"] = field.get("sub_code")
        if field.get("sub_fields"):
            compact_field["sub_fields"] = [
                _compact_model_field(sub_field)
                for sub_field in (field.get("sub_fields") or [])
                if isinstance(sub_field, dict)
            ]
        return compact_field

    compact_models = []
    for model in data.get("models", []) or []:
        if not isinstance(model, dict):
            continue
        compact_fields = []
        for field in model.get("fields", []) or []:
            if not isinstance(field, dict):
                continue
            compact_fields.append(_compact_model_field(field))

        compact_model = {
            "code": model.get("code"),
            "name": model.get("name"),
            "fields": compact_fields,
        }
        if model.get("table_type"):
            compact_model["table_type"] = model.get("table_type")
        if model.get("parent_model_code"):
            compact_model["parent_model_code"] = model.get("parent_model_code")
        compact_models.append(compact_model)

    compact_forms = []
    for form in data.get("forms", []) or []:
        if not isinstance(form, dict):
            continue
        compact_components = []
        for comp in form.get("components", []) or []:
            if not isinstance(comp, dict):
                continue
            compact_comp = {
                "code": comp.get("code"),
                "label": comp.get("label"),
                "componentType": comp.get("componentType"),
            }
            for key in ("name", "modelCode", "tableModelCode", "sectionType", "modelField", "subTableLabel"):
                if comp.get(key):
                    compact_comp[key] = comp.get(key)
            for key in ("hidden", "readonly", "required", "showInList", "searchable"):
                if key in comp and comp.get(key) is not None:
                    compact_comp[key] = bool(comp.get(key))
            for key in ("dict", "dictCode", "dict_code", "description"):
                if comp.get(key):
                    compact_comp[key] = comp.get(key)
            if comp.get("ref"):
                compact_comp["ref"] = comp.get("ref")
            for key in (
                "selector_form_code",
                "selector_form_name",
                "selector_field_code",
                "selector_field_name",
                "association_form_code",
                "association_form_name",
                "association_origin_field_code",
                "association_origin_field_name",
                "association_target_field_code",
                "association_target_field_name",
                "ref_model_code",
                "ref_display_field_code",
            ):
                if comp.get(key):
                    compact_comp[key] = comp.get(key)
            if comp.get("formAssociationConfig") or comp.get("form_association_config"):
                compact_comp["formAssociationConfig"] = comp.get("formAssociationConfig") or comp.get("form_association_config")
            if comp.get("tableColumn") or comp.get("table_column"):
                compact_columns = []
                for column in (comp.get("tableColumn") or comp.get("table_column") or []):
                    if not isinstance(column, dict):
                        continue
                    compact_col = {
                        "code": column.get("code"),
                        "label": column.get("label"),
                        "componentType": column.get("componentType"),
                    }
                    for key in ("name", "modelCode", "tableModelCode", "sectionType", "modelField"):
                        if column.get(key):
                            compact_col[key] = column.get(key)
                    for key in ("hidden", "readonly", "required", "showInList", "searchable"):
                        if key in column and column.get(key) is not None:
                            compact_col[key] = bool(column.get(key))
                    for key in ("dict", "dictCode", "dict_code", "description"):
                        if column.get(key):
                            compact_col[key] = column.get(key)
                    if column.get("ref"):
                        compact_col["ref"] = column.get("ref")
                    for key in (
                        "selector_form_code",
                        "selector_form_name",
                        "selector_field_code",
                        "selector_field_name",
                        "association_form_code",
                        "association_form_name",
                        "association_origin_field_code",
                        "association_origin_field_name",
                        "association_target_field_code",
                        "association_target_field_name",
                        "ref_model_code",
                        "ref_display_field_code",
                    ):
                        if column.get(key):
                            compact_col[key] = column.get(key)
                    if column.get("formAssociationConfig") or column.get("form_association_config"):
                        compact_col["formAssociationConfig"] = column.get("formAssociationConfig") or column.get("form_association_config")
                    compact_columns.append(compact_col)
                if compact_columns:
                    compact_comp["tableColumn"] = compact_columns
            compact_components.append(compact_comp)

        compact_form = {
            "code": form.get("code") or form.get("formCode"),
            "name": form.get("name") or form.get("formName"),
            "formCode": form.get("formCode") or form.get("code"),
            "modelCode": form.get("modelCode"),
            "components": compact_components,
        }
        if form.get("allModelCodes"):
            compact_form["allModelCodes"] = form.get("allModelCodes")
        compact_forms.append(compact_form)

    compact_permissions = []
    for perm in data.get("permissions", []) or []:
        if not isinstance(perm, dict):
            continue
        compact_perm = {
            "form": perm.get("form") or perm.get("formName") or perm.get("table_name"),
            "formName": perm.get("formName") or perm.get("form") or perm.get("table_name"),
            "formCode": perm.get("formCode") or perm.get("form_code") or perm.get("table_code"),
        }
        rules = []
        raw_rules = perm.get("rules") or perm.get("roles") or perm.get("permissions") or []
        for rule in raw_rules:
            if not isinstance(rule, dict):
                continue
            compact_rule = _compact_permission_rule(rule)
            if compact_rule:
                rules.append(compact_rule)
        if rules:
            compact_perm["rules"] = rules
        if compact_perm.get("form") or compact_perm.get("formName") or compact_perm.get("formCode") or rules:
            compact_permissions.append(compact_perm)

    return {
        "appName": data.get("appName"),
        "appCode": data.get("appCode"),
        "roles": data.get("roles", []),
        "dicts": data.get("dicts", []),
        "models": compact_models,
        "forms": compact_forms,
        "workflows": data.get("workflows", []),
        "permissions": compact_permissions or data.get("permissions", []),
    }


def _dump_preview_config(config: dict | None) -> str:
    compact = _compact_preview_payload(config)
    return json.dumps({"type": "preview", "data": compact}, ensure_ascii=False, separators=(",", ":"))


def _dump_parsed_config(config: dict | None) -> str:
    compact = _compact_preview_payload(config)
    return json.dumps(compact, ensure_ascii=False, separators=(",", ":"))


def _component_data_selection_meta_is_stale(component: dict | None) -> bool:
    if not isinstance(component, dict):
        return False

    has_selector = bool(component.get("selector_form_code"))
    if has_selector and not component.get("selector_field_code"):
        return True

    has_association = bool(
        component.get("association_form_code")
        or component.get("formAssociationConfig")
        or component.get("form_association_config")
    )
    if has_association and (
        not component.get("association_origin_field_code")
        or not component.get("association_target_field_code")
    ):
        return True

    has_ref = bool(component.get("ref_model_code") or component.get("ref"))
    if has_ref and not (
        component.get("ref_display_field_code")
        or component.get("selector_field_code")
        or component.get("association_target_field_code")
    ):
        return True

    return False


def _component_type_mismatch_is_stale(parsed_config: dict | None) -> bool:
    if not isinstance(parsed_config, dict):
        return False

    model_field_map: dict[tuple[str, str], dict] = {}
    for model in parsed_config.get("models", []) or []:
        if not isinstance(model, dict):
            continue
        model_code = str(model.get("code") or "").strip()
        if not model_code:
            continue
        for field in model.get("fields", []) or []:
            if not isinstance(field, dict):
                continue
            field_code = str(field.get("code") or "").strip()
            if field_code:
                model_field_map[(model_code, field_code)] = field

    for form in parsed_config.get("forms", []) or []:
        if not isinstance(form, dict):
            continue
        for component in form.get("components", []) or []:
            if not isinstance(component, dict):
                continue

            model_field = str(component.get("modelField") or component.get("model_field") or "").strip()
            model_code = str(component.get("modelCode") or component.get("model_code") or "").strip()
            field_code = str(component.get("code") or component.get("field_code") or "").strip()
            if "." in model_field:
                model_code, field_code = model_field.split(".", 1)
            if not model_code or not field_code:
                continue

            field_meta = model_field_map.get((model_code, field_code))
            if not isinstance(field_meta, dict):
                continue

            field_type = str(field_meta.get("type") or "").strip()
            has_dict = bool(field_meta.get("dict"))
            has_ref = bool(field_meta.get("ref") or field_meta.get("sub_code"))
            expected_selector = field_type in {"数据单选", "数据选择", "关联表单"} or has_ref
            expected_option = field_type in {"下拉单选", "下拉多选", "单选框", "复选框"} or has_dict
            if not (expected_selector or expected_option):
                continue

            component_type = str(component.get("componentType") or component.get("component_type") or "").strip()
            if component_type in {"", "FORM_TEXT_INPUT", "FORM_TEXTAREA_INPUT", "FORM_TEXTAREA"}:
                return True

    return False


def _parsed_config_is_stale(parsed_config: dict | None) -> bool:
    if not isinstance(parsed_config, dict):
        return True
    if _component_type_mismatch_is_stale(parsed_config):
        return True
    for form in parsed_config.get("forms", []) or []:
        if not isinstance(form, dict):
            continue
        for component in form.get("components", []) or []:
            if _component_data_selection_meta_is_stale(component):
                return True
            for column in component.get("tableColumn", []) or component.get("table_column", []) or []:
                if _component_data_selection_meta_is_stale(column):
                    return True
    return False


async def _ensure_doc_version_parsed_config(
    db: AsyncSession,
    version: DocumentVersion,
) -> dict | None:
    parsed = None
    if version.parsed_config:
        try:
            parsed = loads_if_str(version.parsed_config)
        except Exception:
            parsed = None

    raw_content = str(version.raw_content or "").strip()

    parsed_is_stale = parsed is None or _parsed_config_is_stale(parsed)
    raw_needs_reparse = False

    if parsed is not None and not parsed_is_stale and raw_content and not _doc_content_looks_like_template(raw_content):
        try:
            data = _preview_data(parsed)
            rendered = _render_doc_content_from_config(
                data.get("appName", ""),
                data.get("appCode") or data.get("app_code") or "",
                parsed,
            )
            raw_needs_reparse = _normalize_doc_compare_text(rendered) != _normalize_doc_compare_text(raw_content)
        except Exception:
            raw_needs_reparse = False

    if parsed is not None and not parsed_is_stale and not raw_needs_reparse:
        return parsed

    if not raw_content:
        return parsed

    if _doc_content_looks_like_template(raw_content):
        return parsed

    try:
        from app.doc_pipeline import parse_document

        reparsed = await parse_document(raw_content)
        if reparsed:
            version.parsed_config = _dump_parsed_config(reparsed)
            await db.flush()
            return _compact_preview_payload(reparsed)
    except Exception:
        logger.warning("文档版本重解析失败 id=%s", version.id, exc_info=True)

    return parsed


def _preview_data(config: dict | None) -> dict:
    if not isinstance(config, dict):
        return {}
    return config.get("data", config)


def _normalize_doc_compare_text(content: str | None) -> str:
    return "\n".join(str(content or "").strip().splitlines()).strip()


def _doc_content_looks_like_template(content: str | None) -> bool:
    text = str(content or "").strip()
    if not text:
        return False
    head = "\n".join(text.splitlines()[:20])
    return (
        "标准设计文档模板" in head
        or "使用说明" in head
        or "用户注意事项" in head
    )


def _render_doc_content_from_config(
    app_name: str,
    app_code: str,
    config: dict | None,
) -> str:
    from app.routes.generation_steps import _render_design_doc_markdown

    data = dict(_preview_data(config))
    if app_name and not data.get("appName"):
        data["appName"] = app_name
    final_app_code = data.get("appCode") or data.get("app_code") or app_code or ""
    if final_app_code and not data.get("appCode"):
        data["appCode"] = final_app_code
    return _render_design_doc_markdown(app_name or data.get("appName", ""), final_app_code, data)


async def _ensure_doc_version_rendered_content(
    db: AsyncSession,
    app: Optional[Application],
    version: DocumentVersion,
) -> str:
    raw_content = str(version.raw_content or "").strip()

    if raw_content and not _doc_content_looks_like_template(raw_content):
        await _ensure_doc_version_parsed_config(db, version)
        return raw_content

    parsed = await _ensure_doc_version_parsed_config(db, version)
    if isinstance(parsed, dict):
        app_name = ""
        app_code = ""
        if app is not None:
            app_name = app.app_name or ""
            app_code = app.app_code or ""
        data = _preview_data(parsed)
        final_app_code = data.get("appCode") or data.get("app_code") or app_code or ""
        rendered = _render_doc_content_from_config(
            app_name or data.get("appName", ""),
            final_app_code,
            parsed,
        ).strip()
        if rendered and rendered != raw_content:
            version.raw_content = rendered
            await db.flush()
            return rendered
        if rendered:
            return rendered

    return raw_content


async def _sync_canonical_config_to_current_doc_version(
    db: AsyncSession,
    app: Application,
    config: dict | None,
    *,
    filename: str | None = None,
    summary: str | None = None,
    create_if_missing: bool = False,
) -> Optional[DocumentVersion]:
    if not isinstance(config, dict):
        return None

    import hashlib

    data = _preview_data(config)
    config_json = _dump_parsed_config(config)
    preview_app_code = data.get("appCode") or data.get("app_code") or app.app_code or ""
    rendered_doc = _render_doc_content_from_config(app.app_name or "", preview_app_code, config)
    fallback_summary = (
        summary
        or f"{len(data.get('models', []) or [])} 模型, "
           f"{len(data.get('dicts', []) or [])} 字典, "
           f"{len(data.get('roles', []) or [])} 角色"
    )

    current_version_obj = None
    if app.current_doc_version:
        result = await db.execute(
            select(DocumentVersion).where(
                DocumentVersion.application_id == app.id,
                DocumentVersion.version == app.current_doc_version,
            )
        )
        current_version_obj = result.scalar_one_or_none()

    if current_version_obj:
        current_version_obj.parsed_config = config_json
        current_version_obj.raw_content = rendered_doc
        current_version_obj.content_hash = hashlib.sha256(config_json.encode()).hexdigest()
        if filename:
            current_version_obj.filename = filename
        if fallback_summary:
            current_version_obj.summary = fallback_summary
        return current_version_obj

    if not create_if_missing:
        return None

    new_version = int(app.current_doc_version or 0) or 1
    doc_ver = DocumentVersion(
        application_id=app.id,
        conversation_id=app.conversation_id,
        version=new_version,
        filename=filename or f"{app.app_name or '设计文档'}-V{new_version}.md",
        content_hash=hashlib.sha256(config_json.encode()).hexdigest(),
        raw_content=rendered_doc,
        parsed_config=config_json,
        summary=fallback_summary,
    )
    db.add(doc_ver)
    app.current_doc_version = new_version
    return doc_ver


async def _bind_pending_doc_versions_to_app(
    db: AsyncSession,
    app: Application,
    versions: list[DocumentVersion],
) -> int:
    max_ver = 0
    for version in versions:
        version.application_id = app.id
        max_ver = max(max_ver, int(version.version or 0))
        parsed = await _ensure_doc_version_parsed_config(db, version)
        if isinstance(parsed, dict):
            rendered = _render_doc_content_from_config(
                app.app_name or _preview_data(parsed).get("appName", ""),
                app.app_code or _preview_data(parsed).get("appCode", ""),
                parsed,
            ).strip()
            if rendered:
                import hashlib
                version.raw_content = rendered
                version.content_hash = hashlib.sha256(version.parsed_config.encode() if isinstance(version.parsed_config, str) else _dump_parsed_config(parsed).encode()).hexdigest()
    if max_ver:
        app.current_doc_version = max_ver
    return max_ver


async def _resolve_builder_llm_cfg(
    db: AsyncSession,
    tenant_id: int,
    *,
    conversation_id: Optional[int] = None,
) -> dict | None:
    from app.harness.llm_resolver import resolve_llm_config

    selected_config_id: Optional[int] = None
    if conversation_id is not None:
        conv_result = await db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == tenant_id,
            )
        )
        conversation = conv_result.scalar_one_or_none()
        if conversation:
            selected_config_id = conversation.selected_llm_config_id

    resolved = await resolve_llm_config(
        db,
        tenant_id,
        purpose="builder",
        selected_config_id=selected_config_id,
    )
    if not resolved:
        return None
    return {
        "api_key": resolved.api_key,
        "base_url": resolved.base_url,
        "model": resolved.model,
        "max_tokens": resolved.max_tokens,
        "provider": resolved.provider,
    }


def _fallback_generated_icon(app: Application) -> str:
    label = (app.app_name or app.app_code or "A").strip()[:1] or "A"
    label = (
        label.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 48 48">'
        '<defs><linearGradient id="appIconFallback" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0%" stop-color="#14b8a6"/><stop offset="100%" stop-color="#2dd4bf"/>'
        "</linearGradient></defs>"
        '<rect width="48" height="48" rx="12" fill="url(#appIconFallback)"/>'
        f'<text x="24" y="31" text-anchor="middle" font-size="22" font-weight="700" fill="#ffffff">{label}</text>'
        "</svg>"
    )


def _enrich(app: Application) -> ApplicationResponse:
    config = None
    models = forms = roles = dicts = 0
    resolved_app_code = app.app_code
    if app.config_preview:
        try:
            config = loads_if_str(app.config_preview)
            data = config.get("data", config)
            resolved_app_code = data.get("appCode") or data.get("app_code") or resolved_app_code
            models = len(data.get("models", []))
            forms = models
            roles = len(data.get("roles", []))
            dicts = len(data.get("dicts", []))
        except Exception:
            pass
    return ApplicationResponse(
        id=app.id, app_name=app.app_name, app_code=resolved_app_code,
        icon_svg=app.icon_svg,
        description=app.description, status=app.status,
        conversation_id=app.conversation_id,
        platform_env_id=app.platform_env_id,
        apaas_app_id=app.apaas_app_id, config_preview=config,
        models=models, forms=forms, roles=roles, dicts=dicts,
        created_at=app.created_at, updated_at=app.updated_at
    )


# ── 状态映射 ──

_REMOTE_STATUS_MAP = {
    "ENABLE": "已上线",
    "DISABLE": "已下线",
    "SHUTDOWN": "已下线",
}

_LOCAL_STATUS_MAP = {
    "draft": "草稿",
    "generating": "生成中",
    "updating": "更新中",
    "completed": "已生成",
    "failed": "失败",
}


def _resolve_display_status(app: Application, remote_status: str | None = None) -> str:
    normalized_remote = str(remote_status or "").strip().upper()

    if app.status == "updating":
        return _LOCAL_STATUS_MAP["updating"]

    if app.status == "generating":
        return _LOCAL_STATUS_MAP["generating"]

    if app.status == "failed":
        return _LOCAL_STATUS_MAP["failed"]

    if app.apaas_app_id:
        return _LOCAL_STATUS_MAP["completed"]

    if normalized_remote:
        return _REMOTE_STATUS_MAP.get(normalized_remote, _LOCAL_STATUS_MAP["completed"])

    return _LOCAL_STATUS_MAP.get(app.status, app.status)


def _build_apaas_url(apaas_app_id: str, base_url: str | None = None, tenant_id: str | None = None) -> str:
    """得帆云平台应用直达链接（从环境配置取地址）"""
    host = base_url.rstrip("/").replace("/backend", "") if base_url else "https://apaas-poc.definesys.cn"
    tid = tenant_id or settings.apaas_tenant_id
    return f"{host}/platform/{tid}/admin/app-store/edit-app?appId={apaas_app_id}&currentStepIndex=0"


def _build_local(app: Application, perms: dict | None = None, env_name: str | None = None, env_status: str | None = None) -> MergedAppResponse:
    enriched = _enrich(app)
    return MergedAppResponse(
        id=str(app.id),
        app_name=enriched.app_name,
        app_code=enriched.app_code,
        icon_svg=app.icon_svg,
        description=enriched.description,
        source="local",
        status=_resolve_display_status(app),
        local_status=app.status,
        apaas_app_id=app.apaas_app_id,
        conversation_id=app.conversation_id,
        models=enriched.models, forms=enriched.forms,
        roles=enriched.roles, dicts=enriched.dicts,
        config_preview=enriched.config_preview,
        permissions=perms,
        env_name=env_name,
        env_status=env_status,
        created_at=str(enriched.created_at) if enriched.created_at else None,
        updated_at=str(enriched.updated_at) if enriched.updated_at else None,
    )


def _build_linked(app: Application, remote: dict, perms: dict | None = None, env_base_url: str | None = None, env_tenant_id: str | None = None, env_name: str | None = None, env_status: str | None = None) -> MergedAppResponse:
    enriched = _enrich(app)
    remote_status = remote.get("status") or remote.get("appStatus") or ""
    apaas_id = str(remote.get("id", app.apaas_app_id or ""))
    display_app_code = remote.get("appCode") or enriched.app_code
    return MergedAppResponse(
        id=str(app.id),
        app_name=enriched.app_name,
        app_code=display_app_code,
        icon_svg=app.icon_svg,
        description=enriched.description or remote.get("appDesc"),
        source="linked",
        status=_resolve_display_status(app, remote_status),
        local_status=app.status,
        remote_status=remote_status,
        apaas_app_id=apaas_id,
        apaas_url=_build_apaas_url(apaas_id, env_base_url, env_tenant_id),
        conversation_id=app.conversation_id,
        models=enriched.models, forms=enriched.forms,
        roles=enriched.roles, dicts=enriched.dicts,
        config_preview=enriched.config_preview,
        permissions=perms,
        env_name=env_name,
        env_status=env_status,
        created_at=str(enriched.created_at) if enriched.created_at else None,
        updated_at=str(enriched.updated_at) if enriched.updated_at else None,
    )


def _build_remote(remote: dict, env_base_url: str | None = None, env_tenant_id: str | None = None) -> MergedAppResponse:
    remote_status = remote.get("status") or remote.get("appStatus") or ""
    apaas_id = str(remote.get("id", ""))
    return MergedAppResponse(
        id=f"remote_{apaas_id}",
        app_name=remote.get("appName", "未命名应用"),
        app_code=remote.get("appCode"),
        icon_svg=None,
        description=remote.get("remarks") or remote.get("appDesc"),
        source="remote",
        status=_REMOTE_STATUS_MAP.get(remote_status, "平台应用"),
        remote_status=remote_status,
        apaas_app_id=apaas_id,
        apaas_url=_build_apaas_url(apaas_id, env_base_url, env_tenant_id),
        created_at=remote.get("creationDate"),
        updated_at=remote.get("lastUpdateDate"),
    )
