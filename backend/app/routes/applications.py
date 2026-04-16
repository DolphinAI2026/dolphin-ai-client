from __future__ import annotations
import json
import logging
from datetime import datetime
from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy import select, desc, func as sa_func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse
from app.database import get_db
from app.models import User, Application, DocumentVersion, ChangePlan, ApiCallLog, PlatformEnv, Conversation, ConfigSnapshot
from app.auth import get_current_user
from app.schemas import ApplicationCreate, ApplicationResponse, MergedAppResponse
from app.deps import get_auth_context, AuthContext
from app.permissions import has_org_permission, check_resource_permission, batch_get_permissions, Action
from jose import JWTError, jwt
from app.config import settings, APP_DEPLOY_ABSTRACT
from app.apaas_client import APaaSClient
from app.crypto import decrypt_password
from app.json_utils import loads_if_str

from app.services.config_converter import convert_analysis_to_app_config

router = APIRouter(prefix="/applications", tags=["应用"])
logger = logging.getLogger(__name__)


class GenerateAppIconResponse(BaseModel):
    ok: bool
    app_id: int
    icon_svg: str


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


@router.get("", response_model=List[MergedAppResponse])
async def list_applications(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    team_scope: Optional[str] = Query(None),
    include_remote: bool = Query(True),
    source_filter: Optional[str] = Query(None),  # local / remote / linked
):
    """获取应用列表（本地 + 得帆云平台合并）"""
    # 1. 查本地应用
    query = select(Application).where(Application.tenant_id == ctx.tenant_id)
    if team_scope == "personal":
        query = query.where(Application.created_by == ctx.user.id, Application.team_id.is_(None))
    elif team_scope and team_scope.isdigit():
        query = query.where(Application.team_id == int(team_scope))
    query = query.order_by(desc(Application.updated_at))
    result = await db.execute(query)
    local_apps = result.scalars().all()

    permissions_list = await batch_get_permissions(ctx, db, local_apps, "application")

    # 1.5 获取所有环境信息（用于构建 URL 和显示环境名称）
    env_base_url = None
    env_tenant_id = None
    env_map: dict[int, dict] = {}  # env_id → {env_name, status}
    try:
        from app.models import PlatformEnv
        env_result = await db.execute(
            select(PlatformEnv).where(PlatformEnv.tenant_id == ctx.tenant_id)
        )
        all_envs = env_result.scalars().all()
        for env in all_envs:
            env_map[env.id] = {"env_name": env.env_name, "status": env.status}
            if env.is_default:
                env_base_url = env.base_url
                env_tenant_id = env.platform_tenant_id
    except Exception:
        pass

    # 2. 拉取远程应用（降级处理）
    remote_apps: list = []
    if include_remote and ctx.user.apaas_token and source_filter != "local":
        try:
            from app.apaas_client import APaaSClient
            client = APaaSClient(base_url=ctx.user.apaas_base_url, tenant_id=ctx.user.apaas_tenant_id, token=ctx.user.apaas_token)
            remote_apps = await client.query_app_list()
        except Exception as e:
            logger.warning(f"拉取得帆云应用列表失败（降级）: {e}")

    # 3. 合并
    remote_map = {}
    for r in remote_apps:
        rid = str(r.get("id", ""))
        if rid:
            remote_map[rid] = r

    merged: list[MergedAppResponse] = []
    matched_remote_ids: set[str] = set()

    for app, perms in zip(local_apps, permissions_list):
        # 查找应用关联的环境信息
        app_env = env_map.get(app.platform_env_id) if app.platform_env_id else None
        app_env_name = app_env["env_name"] if app_env else None
        app_env_status = app_env["status"] if app_env else None

        if app.apaas_app_id:
            if app.apaas_app_id in remote_map:
                matched_remote_ids.add(app.apaas_app_id)
            if source_filter and source_filter != "linked":
                continue
            merged.append(
                _build_linked(
                    app,
                    remote_map.get(app.apaas_app_id, {}),
                    perms,
                    env_base_url,
                    env_tenant_id,
                    app_env_name,
                    app_env_status,
                )
            )
        else:
            if source_filter and source_filter != "local":
                continue
            merged.append(_build_local(app, perms, app_env_name, app_env_status))

    # 未匹配的远程应用
    if source_filter != "local":
        for rid, remote in remote_map.items():
            if rid not in matched_remote_ids:
                if source_filter and source_filter != "remote":
                    continue
                merged.append(_build_remote(remote, env_base_url, env_tenant_id))

    return merged


@router.get("/{app_id}", response_model=ApplicationResponse)
async def get_application(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    result = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")

    # 检查查看权限
    await check_resource_permission(ctx, db, app, "application", Action.VIEW)

    resp = _enrich(app)
    resp.permissions = (await batch_get_permissions(ctx, db, [app], "application"))[0]

    # 构建平台直达链接
    if app.apaas_app_id:
        env_base_url = env_tenant_id = None
        if app.platform_env_id:
            env_result = await db.execute(select(PlatformEnv).where(PlatformEnv.id == app.platform_env_id))
            env = env_result.scalar_one_or_none()
            if env:
                env_base_url, env_tenant_id = env.base_url, env.platform_tenant_id
        if not env_base_url:
            # 回退到默认环境
            default_env_result = await db.execute(
                select(PlatformEnv).where(PlatformEnv.tenant_id == ctx.tenant_id, PlatformEnv.is_default == True)
            )
            default_env = default_env_result.scalar_one_or_none()
            if default_env:
                env_base_url, env_tenant_id = default_env.base_url, default_env.platform_tenant_id
        resp.apaas_url = _build_apaas_url(str(app.apaas_app_id), env_base_url, env_tenant_id)

    return resp


@router.post("", response_model=ApplicationResponse)
async def create_application(
    data: ApplicationCreate,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    granted_permissions = sorted(
        code for code, allowed in (ctx.org_permissions or {}).items() if allowed
    )
    logger.info(
        "create_application request user_id=%s tenant_id=%s tenant_role=%s conversation_id=%s app_code=%s platform_env_id=%s granted_permissions=%s",
        ctx.user.id,
        ctx.tenant_id,
        ctx.tenant_role,
        data.conversation_id,
        data.app_code,
        data.platform_env_id,
        granted_permissions,
    )

    # 检查创建权限
    if not has_org_permission(ctx.org_permissions, "application", Action.CREATE):
        logger.warning(
            "create_application forbidden user_id=%s tenant_id=%s tenant_role=%s missing_permission=%s granted_permissions=%s",
            ctx.user.id,
            ctx.tenant_id,
            ctx.tenant_role,
            "application:create",
            granted_permissions,
        )
        raise HTTPException(status_code=403, detail="你的角色没有创建应用的权限")

    config_str = _dump_preview_config(data.config_preview) if data.config_preview else None
    app = Application(
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        created_by=ctx.user.id,
        team_id=None,  # 默认个人应用，后续可以转移到团队
        conversation_id=data.conversation_id,
        app_name=data.app_name,
        app_code=data.app_code,
        description=data.description,
        platform_env_id=data.platform_env_id,
        config_preview=config_str,
        status="draft"
    )
    db.add(app)
    await db.commit()
    await db.refresh(app)

    logger.info(
        "create_application success app_id=%s user_id=%s tenant_id=%s app_code=%s",
        app.id,
        ctx.user.id,
        ctx.tenant_id,
        app.app_code,
    )

    # 把对话中已创建的 DocumentVersion 关联到新 Application
    if data.conversation_id:
        try:
            from sqlalchemy import update as sa_update
            result = await db.execute(
                select(DocumentVersion).where(
                    DocumentVersion.conversation_id == data.conversation_id,
                    DocumentVersion.application_id.is_(None)
                )
            )
            conv_versions = result.scalars().all()
            if conv_versions:
                max_ver = await _bind_pending_doc_versions_to_app(db, app, conv_versions)
                app.current_doc_version = max_ver
                await db.commit()
                await db.refresh(app)
                logger.info(f"Linked {len(conv_versions)} DocumentVersion(s) to app {app.id}")
            else:
                # 兼容旧流程：对话里没有挂起版本时，也只允许从 canonical config 创建版本，
                # 绝不再把上传原文直接回灌到 DocumentVersion.raw_content。
                from app.models import Message

                doc_filename = f"{data.app_name or 'design-doc'}.md"
                msg_result = await db.execute(
                    select(Message).where(
                        Message.conversation_id == data.conversation_id,
                        Message.role == "system",
                        Message.content.like('%doc_raw%')
                    ).order_by(Message.id.desc()).limit(1)
                )
                doc_msg = msg_result.scalar_one_or_none()
                if doc_msg and doc_msg.content:
                    try:
                        raw = doc_msg.content
                        if '```doc_raw' in raw:
                            json_str = raw.split('```doc_raw\n', 1)[1].rsplit('\n```', 1)[0]
                        else:
                            json_str = raw
                        doc_data = json.loads(json_str)
                        doc_filename = doc_data.get("filename", doc_filename) or doc_filename
                    except (json.JSONDecodeError, IndexError, ValueError):
                        pass

                if data.config_preview:
                    await _sync_canonical_config_to_current_doc_version(
                        db,
                        app,
                        data.config_preview,
                        filename=doc_filename,
                        create_if_missing=True,
                    )
                    await db.commit()
                    await db.refresh(app)
                    logger.info("Fallback: created canonical DocumentVersion V1 for app %s", app.id)
        except Exception as e:
            logger.warning(f"Failed to link/create DocumentVersion: {e}")

    if data.config_preview:
        await _sync_canonical_config_to_current_doc_version(
            db,
            app,
            data.config_preview,
            create_if_missing=not bool(app.current_doc_version),
        )
        app.config_preview = _dump_preview_config(data.config_preview)
        await db.commit()
        await db.refresh(app)

    resp = _enrich(app)
    resp.permissions = {Action.EDIT: True, Action.DELETE: True, Action.CLONE: True}  # 创建者全部权限
    return resp


class AutoCreateRequest(BaseModel):
    """前端首次生成配置时自动创建应用"""
    app_name: str
    config_preview: dict
    conversation_id: Optional[int] = None


class AutoCreateResponse(BaseModel):
    app_id: int
    app_name: str
    app_code: str
    is_new: bool  # True=新建, False=已存在


@router.post("/auto-create", response_model=AutoCreateResponse)
async def auto_create_application(
    data: AutoCreateRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """首次生成配置时自动创建 Application。

    如果 conversation_id 已有关联应用，返回已有应用（不重复创建）。
    否则创建新的 draft 应用。
    """
    # 如果有 conversation_id，检查是否已有关联应用
    if data.conversation_id:
        result = await db.execute(
            select(Application).where(
                Application.conversation_id == data.conversation_id,
                Application.tenant_id == ctx.tenant_id,
            ).order_by(Application.id.desc()).limit(1)
        )
        existing = result.scalar_one_or_none()
        if existing:
            # 更新配置，并把本次对话里尚未绑定的最新文档版本挂到当前应用
            existing.config_preview = _dump_preview_config(data.config_preview)
            existing.app_name = data.app_name
            try:
                doc_ver_result = await db.execute(
                    select(DocumentVersion).where(
                        DocumentVersion.conversation_id == data.conversation_id,
                        DocumentVersion.application_id.is_(None),
                    ).order_by(DocumentVersion.version.desc())
                )
                pending_versions = doc_ver_result.scalars().all()
                if pending_versions:
                    latest_version = await _bind_pending_doc_versions_to_app(db, existing, pending_versions)
                    existing.current_doc_version = latest_version or existing.current_doc_version
            except Exception as e:
                logger.warning(f"auto-create(existing): link DocumentVersions failed: {e}")
            await _sync_canonical_config_to_current_doc_version(
                db,
                existing,
                data.config_preview,
                create_if_missing=not bool(existing.current_doc_version),
            )
            await db.commit()
            return AutoCreateResponse(
                app_id=existing.id,
                app_name=existing.app_name,
                app_code=existing.app_code,
                is_new=False,
            )

    # 生成 app_code：优先使用解析文档中的 appCode
    import hashlib
    preview_data = data.config_preview.get("data", data.config_preview) if isinstance(data.config_preview, dict) else {}
    ascii_code = _normalize_app_code(preview_data.get("appCode") if isinstance(preview_data, dict) else "")
    if not ascii_code:
        code_base = data.app_name.lower().replace(" ", "-").replace("_", "-")
        ascii_code = ''.join(c for c in code_base if c.isascii() and (c.isalnum() or c == '-'))
        ascii_code = ascii_code.strip('-')
    if len(ascii_code) < 2:
        ascii_code = "app-" + hashlib.md5(data.app_name.encode()).hexdigest()[:6]

    config_str = _dump_preview_config(data.config_preview)
    app = Application(
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        created_by=ctx.user.id,
        conversation_id=data.conversation_id,
        app_name=data.app_name,
        app_code=ascii_code,
        config_preview=config_str,
        status="draft",
    )
    db.add(app)
    await db.commit()
    await db.refresh(app)

    # 关联已有的 DocumentVersion
    if data.conversation_id:
        try:
            result = await db.execute(
                select(DocumentVersion).where(
                    DocumentVersion.conversation_id == data.conversation_id,
                    DocumentVersion.application_id.is_(None),
                )
            )
            linked_versions = result.scalars().all()
            max_ver = await _bind_pending_doc_versions_to_app(db, app, linked_versions)
            if max_ver:
                app.current_doc_version = max_ver
            await _sync_canonical_config_to_current_doc_version(
                db,
                app,
                data.config_preview,
                create_if_missing=not bool(max_ver),
            )
            await db.commit()
        except Exception as e:
            logger.warning(f"auto-create: link DocumentVersions failed: {e}")

    logger.info(f"auto-create: app_id={app.id}, app_name={app.app_name}")
    return AutoCreateResponse(
        app_id=app.id,
        app_name=app.app_name,
        app_code=app.app_code,
        is_new=True,
    )


# ============================================================
# 从平台导入已有应用
# ============================================================

class ImportFromPlatformRequest(BaseModel):
    env_id: int
    apaas_app_id: str


@router.post("/import-from-platform", response_model=ApplicationResponse)
async def import_from_platform(
    body: ImportFromPlatformRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """从平台导入已有应用：拉取结构 → 生成 config_preview + markdown 需求文档"""
    from app.platform_sync import sync_from_platform_full
    from app.services.config_to_spec import config_to_markdown

    # 1. 获取环境
    env_result = await db.execute(
        select(PlatformEnv).where(
            PlatformEnv.id == body.env_id,
            PlatformEnv.tenant_id == ctx.tenant_id,
        )
    )
    env = env_result.scalar_one_or_none()
    if not env:
        raise HTTPException(status_code=404, detail="环境不存在")
    if not env.token:
        raise HTTPException(status_code=400, detail="环境未连接，请先登录")

    # 2. 检查是否已导入
    existing = await db.execute(
        select(Application).where(
            Application.tenant_id == ctx.tenant_id,
            Application.apaas_app_id == body.apaas_app_id,
        )
    )
    existing_app = existing.scalar_one_or_none()

    # 3. 创建 client，获取应用信息
    client = APaaSClient(
        base_url=env.base_url,
        tenant_id=env.platform_tenant_id,
        token=env.token,
    )

    try:
        app_detail = await client.query_app_detail(body.apaas_app_id)
    except Exception:
        # token 可能过期，尝试刷新
        if env.username and env.password_enc:
            try:
                password = decrypt_password(env.password_enc)
                login_result = await client.login(env.username, password)
                env.token = login_result.get("token", "")
                env.status = "connected"
                await db.commit()
                client = APaaSClient(
                    base_url=env.base_url,
                    tenant_id=env.platform_tenant_id,
                    token=env.token,
                )
                app_detail = await client.query_app_detail(body.apaas_app_id)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"获取应用信息失败: {e}")
        else:
            raise HTTPException(status_code=400, detail="token 过期且无登录凭据")

    if not app_detail:
        raise HTTPException(status_code=404, detail="平台上未找到该应用")

    app_name = app_detail.get("appName", app_detail.get("name", "未命名"))
    app_code = app_detail.get("appCode", app_detail.get("code", ""))
    app_desc = app_detail.get("description", app_detail.get("appDescription", ""))

    # 4. 完整反向解析
    try:
        config = await sync_from_platform_full(client, body.apaas_app_id, app_name)
    except Exception as e:
        logger.error(f"反向解析失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"反向解析应用结构失败: {e}")

    config = dict(config or {})
    config["appName"] = app_name
    if app_code:
        config["appCode"] = app_code

    # 5. 生成 markdown 需求文档
    try:
        markdown_spec = config_to_markdown(config, app_description=app_desc)
    except Exception as e:
        logger.warning(f"生成 markdown 失败: {e}")
        markdown_spec = ""

    resolved_app_code = app_code or _normalize_app_code(config.get("appCode")) or app_name.lower().replace(" ", "_")

    # 6. 已存在同平台应用：作为新版本重新导入
    if existing_app:
        import hashlib

        max_ver_result = await db.execute(
            select(sa_func.max(DocumentVersion.version)).where(
                DocumentVersion.application_id == existing_app.id
            )
        )
        max_ver = int(max_ver_result.scalar() or 0)
        new_version = max_ver + 1
        config_json = _dump_parsed_config(config)
        rendered_doc = _render_doc_content_from_config(
            app_name or existing_app.app_name or "",
            resolved_app_code or existing_app.app_code or "",
            config,
        )

        doc_ver = DocumentVersion(
            application_id=existing_app.id,
            conversation_id=existing_app.conversation_id,
            version=new_version,
            filename=f"{app_name or existing_app.app_name or '设计文档'}-V{new_version}.md",
            content_hash=hashlib.sha256(config_json.encode()).hexdigest(),
            raw_content=rendered_doc,
            parsed_config=config_json,
            parent_version=max_ver if max_ver > 0 else None,
            summary="从平台重新导入生成",
        )
        db.add(doc_ver)

        existing_app.app_name = app_name or existing_app.app_name
        existing_app.app_code = resolved_app_code or existing_app.app_code
        existing_app.description = app_desc
        existing_app.config_preview = _dump_preview_config(config)
        existing_app.requirement_doc = markdown_spec
        existing_app.platform_env_id = body.env_id
        existing_app.current_doc_version = new_version
        existing_app.status = "completed"

        await db.commit()
        await db.refresh(existing_app)

        logger.info(
            "应用重新导入成功: %s (apaas_id=%s, version=%s)",
            app_name,
            body.apaas_app_id,
            new_version,
        )
        return _enrich(existing_app)

    # 7. 创建本地 Application 记录
    config_str = _dump_preview_config(config)
    new_app = Application(
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        created_by=ctx.user.id,
        app_name=app_name,
        app_code=resolved_app_code,
        description=app_desc,
        config_preview=config_str,
        requirement_doc=markdown_spec,
        apaas_app_id=body.apaas_app_id,
        platform_env_id=body.env_id,
        status="completed",
    )
    db.add(new_app)
    await db.flush()
    await _sync_canonical_config_to_current_doc_version(
        db,
        new_app,
        config,
        filename=f"{app_name or '设计文档'}-V1.md",
        summary="从平台导入自动生成",
        create_if_missing=True,
    )
    await db.commit()
    await db.refresh(new_app)

    logger.info(f"应用导入成功: {app_name} (apaas_id={body.apaas_app_id})")
    return _enrich(new_app)


@router.put("/{app_id}", response_model=ApplicationResponse)
async def update_application(
    app_id: int,
    data: ApplicationCreate,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """更新应用配置（继续完善后重新生成前调用）"""
    result = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")

    await check_resource_permission(ctx, db, app, "application", Action.EDIT)

    app.app_name = data.app_name
    app.description = data.description
    if hasattr(data, 'app_code') and data.app_code:
        app.app_code = data.app_code
    if hasattr(data, 'platform_env_id') and data.platform_env_id is not None:
        app.platform_env_id = data.platform_env_id
    if data.config_preview:
        app.config_preview = _dump_preview_config(data.config_preview)
        await _sync_canonical_config_to_current_doc_version(
            db,
            app,
            data.config_preview,
            create_if_missing=not bool(app.current_doc_version),
        )
    # 已上平台的应用再次修改时进入“更新中”，未完成的应用才回到草稿。
    if app.apaas_app_id or app.status in ("completed", "updating"):
        app.status = "updating"
    elif app.status == "failed":
        app.status = "draft"
    await db.commit()
    await db.refresh(app)
    return _enrich(app)


@router.patch("/{app_id}/code")
async def update_app_code(
    app_id: int,
    body: dict,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """更新应用编码（部署失败后修改）"""
    result = await db.execute(
        select(Application).where(Application.id == app_id, Application.tenant_id == ctx.tenant_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    new_code = body.get("app_code")
    if not new_code:
        raise HTTPException(status_code=400, detail="app_code 不能为空")
    app.app_code = new_code
    if app.config_preview:
        try:
            config = loads_if_str(app.config_preview)
            data = config.get("data", config)
            data["app_code"] = new_code
            app.config_preview = _dump_preview_config(config)

            if app.current_doc_version:
                import hashlib
                from app.routes.generation_steps import _render_design_doc_markdown

                config_json = _dump_parsed_config(config)
                rendered_doc = _render_design_doc_markdown(app.app_name, new_code, data)
                version_result = await db.execute(
                    select(DocumentVersion).where(
                        DocumentVersion.application_id == app.id,
                        DocumentVersion.version == app.current_doc_version,
                    )
                )
                current_doc_ver = version_result.scalar_one_or_none()
                if current_doc_ver:
                    current_doc_ver.filename = f"{app.app_name or '设计文档'}-V{app.current_doc_version}.md"
                    current_doc_ver.content_hash = hashlib.sha256(config_json.encode()).hexdigest()
                    current_doc_ver.raw_content = rendered_doc
                    current_doc_ver.parsed_config = config_json
                    current_doc_ver.summary = f"初始版本（已完成应用编码修复：{new_code}）"
        except Exception as e:
            logger.warning(f"同步应用编码到文档版本失败: {e}")
    await db.commit()
    return {"ok": True, "app_code": new_code}


@router.post("/{app_id}/generate-icon", response_model=GenerateAppIconResponse)
async def generate_application_icon(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")

    await check_resource_permission(ctx, db, app, "application", Action.EDIT)

    icon_svg = _fallback_generated_icon(app)
    app.icon_svg = icon_svg
    await db.commit()

    return GenerateAppIconResponse(ok=True, app_id=app.id, icon_svg=icon_svg)


@router.post("/{app_id}/publish")
async def publish_application(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """上线应用（发布到平台）。"""
    result = await db.execute(
        select(Application).where(Application.id == app_id, Application.tenant_id == ctx.tenant_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    if not app.apaas_app_id:
        raise HTTPException(status_code=400, detail="应用尚未部署，不能上线")

    await check_resource_permission(ctx, db, app, "application", Action.EDIT)

    env = None
    if app.platform_env_id:
        env_result = await db.execute(select(PlatformEnv).where(PlatformEnv.id == app.platform_env_id))
        env = env_result.scalar_one_or_none()
    if not env:
        env_result = await db.execute(
            select(PlatformEnv).where(PlatformEnv.tenant_id == ctx.tenant_id, PlatformEnv.is_default == True)
        )
        env = env_result.scalar_one_or_none()
    if not env:
        env_result = await db.execute(
            select(PlatformEnv).where(
                PlatformEnv.tenant_id == ctx.tenant_id,
                PlatformEnv.status == "connected",
            ).limit(1)
        )
        env = env_result.scalar_one_or_none()
    if not env:
        raise HTTPException(status_code=400, detail="未找到可用的平台环境")

    token = env.token
    if not token and env.username and env.password_enc:
        try:
            password = decrypt_password(env.password_enc)
            login_client = APaaSClient(base_url=env.base_url, tenant_id=env.platform_tenant_id)
            login_result = await login_client.login(env.username, password)
            token = login_result.get("token", "")
            if token:
                env.token = token
                env.status = "connected"
                await db.commit()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"平台登录失败: {e}")
    if not token:
        raise HTTPException(status_code=400, detail="平台 token 不可用，请先在环境管理中登录")

    try:
        client = APaaSClient(base_url=env.base_url, tenant_id=env.platform_tenant_id, token=token)
        app_detail = await client.query_app_detail(str(app.apaas_app_id))
        current_version = app_detail.get("appVersion", app_detail.get("version", ""))
        if current_version:
          parts = current_version.split(".")
          try:
              nums = [int(p) for p in parts]
              nums[-1] += 1
              next_version = ".".join(str(p) for p in nums)
          except Exception:
              next_version = "1.0.1"
        else:
          next_version = "1.0.0"
        await client.deploy_app(str(app.apaas_app_id), next_version, abstract=APP_DEPLOY_ABSTRACT)
        app.status = "completed"
        await db.commit()
        return {"ok": True, "version": next_version, "remote_status": "ENABLE"}
    except Exception as e:
        detail = str(e)
        if ("Token已过期或无效" in detail or "401" in detail) and env.username and env.password_enc:
            try:
                password = decrypt_password(env.password_enc)
                refresh_client = APaaSClient(base_url=env.base_url, tenant_id=env.platform_tenant_id)
                login_result = await refresh_client.login(env.username, password)
                token = login_result.get("token", "")
                if token:
                    env.token = token
                    env.status = "connected"
                    await db.commit()
                    client = APaaSClient(base_url=env.base_url, tenant_id=env.platform_tenant_id, token=token)
                    app_detail = await client.query_app_detail(str(app.apaas_app_id))
                    current_version = app_detail.get("appVersion", app_detail.get("version", ""))
                    if current_version:
                        parts = current_version.split(".")
                        try:
                            nums = [int(p) for p in parts]
                            nums[-1] += 1
                            next_version = ".".join(str(p) for p in nums)
                        except Exception:
                            next_version = "1.0.1"
                    else:
                        next_version = "1.0.0"
                    await client.deploy_app(str(app.apaas_app_id), next_version, abstract=APP_DEPLOY_ABSTRACT)
                    app.status = "completed"
                    await db.commit()
                    return {"ok": True, "version": next_version, "remote_status": "ENABLE"}
            except Exception as retry_error:
                raise HTTPException(status_code=401, detail=f"平台登录失效，请重新连接APaaS平台：{retry_error}")
        raise HTTPException(status_code=400, detail=f"上线失败: {detail}")


class PlatformConfigUpdate(BaseModel):
    """更新应用的平台环境配置"""
    platform_url: Optional[str] = None
    platform_tenant_id: Optional[str] = None
    platform_username: Optional[str] = None
    platform_password_enc: Optional[str] = None


@router.patch("/{app_id}/platform-config")
async def update_platform_config(
    app_id: int,
    data: PlatformConfigUpdate,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """更新应用的平台环境配置"""
    result = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")

    await check_resource_permission(ctx, db, app, "application", Action.EDIT)

    if data.platform_url is not None:
        app.platform_url = data.platform_url
    if data.platform_tenant_id is not None:
        app.platform_tenant_id = data.platform_tenant_id
    if data.platform_username is not None:
        app.platform_username = data.platform_username
    if data.platform_password_enc is not None:
        app.platform_password_enc = data.platform_password_enc

    await db.commit()
    return {"success": True, "message": "平台配置已更新"}


@router.delete("/{app_id}")
async def delete_application(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """删除本地应用记录及其关联数据"""
    try:
        result = await db.execute(
            select(Application).where(
                Application.id == app_id,
                Application.tenant_id == ctx.tenant_id
            )
        )
        app = result.scalar_one_or_none()
        if not app:
            raise HTTPException(status_code=404, detail="应用不存在")

        await check_resource_permission(ctx, db, app, "application", Action.DELETE)

        if app.status in {"completed", "generating"} or app.apaas_app_id:
            raise HTTPException(status_code=400, detail="已构建或已同步到平台的应用不允许删除")

        # 先清理依赖当前 application_id 的关联数据，避免外键约束导致主记录删除失败。
        await db.execute(
            delete(DocumentVersion).where(DocumentVersion.application_id == app.id)
        )
        await db.execute(
            delete(ChangePlan).where(ChangePlan.application_id == app.id)
        )
        await db.execute(
            delete(ConfigSnapshot).where(ConfigSnapshot.application_id == app.id)
        )
        await db.execute(
            delete(ApiCallLog).where(ApiCallLog.application_id == app.id)
        )
        await db.execute(
            delete(Application).where(
                Application.id == app.id,
                Application.tenant_id == ctx.tenant_id,
            )
        )

        await db.commit()
        return {"ok": True}
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        logger.exception("delete application failed: app_id=%s tenant_id=%s", app_id, ctx.tenant_id)
        raise HTTPException(status_code=500, detail=f"删除失败: {exc}")


@router.get("/{app_id}/generate")
async def generate_application(
    app_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    token: Optional[str] = Query(None),
):
    from app.apaas_client import APaaSClient
    from app.generator_v2 import run_complete_generation

    # SSE不能设置Authorization header，通过query param传token
    if not token:
        raise HTTPException(status_code=401, detail="缺少认证token")
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        user_id = int(payload.get("sub", 0))
        tenant_id = payload.get("tid")
        if tenant_id is None:
            raise HTTPException(status_code=403, detail="平台管理员无法生成应用")
        tenant_id = int(tenant_id)
    except (JWTError, Exception):
        raise HTTPException(status_code=401, detail="无效的认证凭证")

    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    current_user = result.scalar_one_or_none()
    if not current_user:
        raise HTTPException(status_code=401, detail="用户不存在")

    result = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == tenant_id
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    if not app.config_preview:
        raise HTTPException(status_code=400, detail="应用配置为空")
    if not current_user.apaas_token:
        raise HTTPException(status_code=400, detail="未连接得帆云平台，请先在设置中连接APaaS平台")

    config = loads_if_str(app.config_preview)
    client = APaaSClient(base_url=current_user.apaas_base_url, tenant_id=current_user.apaas_tenant_id, token=current_user.apaas_token)
    # 记住已有的 apaas_app_id（SSE generator 需要自己的 session）
    existing_apaas_app_id = app.apaas_app_id

    async def event_generator():
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            # 在新 session 中重新加载 app 对象
            result = await session.execute(
                select(Application).where(Application.id == app_id)
            )
            app_obj = result.scalar_one()

            try:
                if not existing_apaas_app_id:
                    apaas_result = await client.create_app(app_obj.app_name, app_obj.app_code, app_obj.description or "")
                    apaas_app_id = str(apaas_result) if isinstance(apaas_result, str) else str(apaas_result.get("id", apaas_result.get("appId", "")))
                    app_obj.apaas_app_id = apaas_app_id
                    app_obj.status = "generating"
                    await session.commit()
                    logger.info(f"应用 {app_id} 平台创建成功, apaas_app_id={apaas_app_id}")
                    yield {"event": "progress", "data": json.dumps({"stage": -1, "status": "running", "step": f"应用已创建: {app_obj.app_name}"}, ensure_ascii=False)}
                else:
                    apaas_app_id = existing_apaas_app_id
                    app_obj.status = "generating"
                    await session.commit()
                    yield {"event": "progress", "data": json.dumps({"stage": -1, "status": "running", "step": f"复用已有平台应用: {apaas_app_id}"}, ensure_ascii=False)}

                async for event in run_complete_generation(client, apaas_app_id, config):
                    yield {"event": "progress", "data": json.dumps(event, ensure_ascii=False)}
                    if event.get("type") == "complete":
                        app_obj.status = "completed"
                        await session.commit()
                    elif event.get("status") == "error":
                        app_obj.status = "failed"
                        await session.commit()

                yield {"event": "done", "data": json.dumps({"type": "done"})}
            except Exception as e:
                logger.error(f"应用 {app_id} 生成失败: {e}")
                app_obj.status = "failed"
                await session.commit()

                # 特殊处理401错误
                error_msg = str(e)
                if "401" in error_msg or "Token已过期" in error_msg or "Unauthorized" in error_msg:
                    error_msg = "APaaS平台Token已过期，请重新连接平台后再试"

                yield {"event": "error", "data": json.dumps({"type": "error", "message": error_msg}, ensure_ascii=False)}

    return EventSourceResponse(event_generator())


@router.post("/upload-doc")
async def upload_design_doc(
    file: UploadFile = File(...),
    ctx: Annotated[AuthContext, Depends(get_auth_context)] = None,
):
    """上传功能设计文档(.md)，用 AI 解析为 preview JSON"""
    if not file.filename or not file.filename.endswith('.md'):
        raise HTTPException(status_code=400, detail="仅支持 .md 格式文件")

    content = await file.read()
    text = content.decode('utf-8')

    from app.doc_pipeline import parse_document
    try:
        result = await parse_document(text)
        data = result.get("data", result)
    except Exception as e:
        logger.error(f"文档解析失败: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"文档解析失败: {e}")

    # 若解析结果是默认值，优先从文档正文/标题推断，退回文件名
    if str(data.get("appName") or "").strip() in _DEFAULT_APP_NAMES:
        inferred = _infer_app_name_from_doc(text, file.filename or "")
        if inferred:
            data["appName"] = inferred

    return {
        "type": "preview",
        "data": data,
        "document_content": text
    }


@router.post("/upload-doc-with-conversation")
async def upload_doc_with_conversation(
    file: UploadFile = File(...),
    conversation_id: Optional[int] = Form(None),
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    ctx: Annotated[AuthContext, Depends(get_auth_context)] = None,
):
    """上传功能设计文档并创建对话会话（SSE 流式返回解析进度）

    支持两种模式：
    - V1（首次上传）：不传 conversation_id，完整解析，创建新对话
    - V2+（增量上传）：传 conversation_id，对比文档文本，只解析变化部分

    事件格式：
    - event: progress / data: {"message": "..."} — 解析进度
    - event: done / data: {"conversation_id":N, "preview":{...}} — 完成
    - event: error / data: {"message": "..."} — 失败
    """
    if not file.filename or not file.filename.endswith('.md'):
        raise HTTPException(status_code=400, detail="仅支持 .md 格式文件")

    content = await file.read()
    text = content.decode('utf-8')
    fname = file.filename or ""

    # 把 db session 相关的值先存好
    user_id = current_user.id
    tenant_id = ctx.tenant_id
    existing_conversation_id = conversation_id

    # 获取当前对话/租户绑定的 Builder 模型，避免文档解析回退到 .env 默认模型
    _tenant_llm_cfg = await _resolve_builder_llm_cfg(
        db,
        tenant_id,
        conversation_id=existing_conversation_id,
    )

    # 如果传了 conversation_id，预先查找 V1 文档版本
    v1_doc_info: Optional[dict] = None
    if existing_conversation_id:
        v1_result = await db.execute(
            select(DocumentVersion)
            .where(DocumentVersion.conversation_id == existing_conversation_id)
            .order_by(desc(DocumentVersion.version))
            .limit(1)
        )
        v1_doc_obj = v1_result.scalar_one_or_none()
        if v1_doc_obj:
            v1_doc_info = {
                "raw_content": v1_doc_obj.raw_content,
                "parsed_config": v1_doc_obj.parsed_config,
                "version": v1_doc_obj.version,
            }

    async def event_generator():
        import asyncio
        from app.database import AsyncSessionLocal
        from app.doc_text_differ import diff_sections, get_diff_stats
        from app.doc_pipeline import parse_document
        from app.config_diff import compute_config_diff

        data = None
        diff_result = None
        is_incremental = bool(v1_doc_info)
        v1_parsed_config = None

        try:
            # ── 增量模式：有 V1 文档时先检查是否有变化 ──
            if v1_doc_info and v1_doc_info.get("raw_content"):
                yield {"event": "progress", "data": json.dumps({"message": "正在对比文档..."}, ensure_ascii=False)}
                diff_result = diff_sections(v1_doc_info["raw_content"], text)
                diff_stats = get_diff_stats(diff_result)
                total_changes = diff_stats["added"] + diff_stats["modified"] + diff_stats["removed"]

                if total_changes == 0:
                    yield {"event": "error", "data": json.dumps({"message": "文档内容无变化，无需重新上传"}, ensure_ascii=False)}
                    return

                yield {"event": "progress", "data": json.dumps({
                    "message": f"发现 {total_changes} 个章节变化（新增 {diff_stats['added']} 个，修改 {diff_stats['modified']} 个，删除 {diff_stats['removed']} 个）",
                    "diff_stats": diff_stats,
                }, ensure_ascii=False)}

            # ── 全量解析：用 asyncio.Queue 实时把进度推给前端 ──
            # 队列中的元素为 (msg, batch) 元组，batch 为可选的已解析模块数据
            progress_queue: asyncio.Queue = asyncio.Queue()

            async def _on_progress(msg: str, *, batch=None):
                await progress_queue.put((msg, batch))

            # 启动解析任务（与 SSE 流并发）
            parse_task = asyncio.create_task(
                parse_document(text, llm_cfg=_tenant_llm_cfg, on_progress=_on_progress)
            )

            # 实时转发进度消息，直到解析完成
            while not parse_task.done():
                try:
                    item = await asyncio.wait_for(progress_queue.get(), timeout=0.2)
                    msg, batch = item if isinstance(item, tuple) else (item, None)
                    payload = {"message": msg}
                    if batch is not None:
                        payload["batch"] = batch
                    yield {"event": "progress", "data": json.dumps(payload, ensure_ascii=False)}
                except asyncio.TimeoutError:
                    pass

            # 排干队列中剩余消息
            while not progress_queue.empty():
                item = progress_queue.get_nowait()
                msg, batch = item if isinstance(item, tuple) else (item, None)
                payload = {"message": msg}
                if batch is not None:
                    payload["batch"] = batch
                yield {"event": "progress", "data": json.dumps(payload, ensure_ascii=False)}

            # 取解析结果（若抛异常会在此处重新抛出）
            parse_result = parse_task.result()
            parse_meta = parse_result.get("parse_meta", {}) if isinstance(parse_result, dict) else {}
            data = parse_result.get("data", parse_result)

            # LLM 返回的 appName 常常是"应用"/"未命名应用"等默认值；必须在发出任何
            # SSE 事件（skeleton/complete/done）之前把它推断为文档里的真实名字，
            # 否则前端 skeleton 阶段会先把默认值写入 store，后续事件的守卫逻辑会
            # 阻止覆盖，最终界面显示"未命名应用"。
            if isinstance(data, dict) and str(data.get("appName") or "").strip() in _DEFAULT_APP_NAMES:
                inferred = _infer_app_name_from_doc(text, fname)
                if inferred:
                    data["appName"] = inferred

            # ── 增量模式：用纯代码 diff 与 V1 config 对比，继承编码 ──
            if v1_doc_info and v1_doc_info.get("parsed_config"):
                try:
                    v1_parsed_config = loads_if_str(v1_doc_info["parsed_config"])
                    yield {"event": "progress", "data": json.dumps({"message": "对比配置差异..."}, ensure_ascii=False)}
                    resource_diff = compute_config_diff(v1_parsed_config, data)
                    if resource_diff.normalized_new_config:
                        data = resource_diff.normalized_new_config
                except Exception as e:
                    logger.warning(f"增量 diff 失败，使用全量解析结果: {e}")

            if data:
                roles_count = len(data.get("roles", []))
                dicts_count = len(data.get("dicts", []))
                models_count = len(data.get("models", []))

                skeleton_data = {
                    "appName": data.get("appName", ""),
                    "appCode": data.get("appCode", ""),
                    "roles": data.get("roles", []),
                }
                yield {"event": "progress", "data": json.dumps({
                    "message": f"[skeleton] 骨架完成：{models_count} 个模型、{dicts_count} 个字典、{roles_count} 个角色",
                    "data": skeleton_data,
                }, ensure_ascii=False)}

                if data.get("roles"):
                    yield {"event": "progress", "data": json.dumps({
                        "message": f"[roles] 角色生成完成：{roles_count} 个",
                        "batch": data["roles"],
                    }, ensure_ascii=False)}
                if data.get("dicts"):
                    yield {"event": "progress", "data": json.dumps({
                        "message": f"[dicts] 字典生成完成：{dicts_count} 个",
                        "batch": data["dicts"],
                    }, ensure_ascii=False)}
                if data.get("models"):
                    yield {"event": "progress", "data": json.dumps({
                        "message": f"[models] 模型生成完成：{models_count} 个",
                        "batch": data["models"],
                    }, ensure_ascii=False)}
                if data.get("forms"):
                    forms_count = len(data.get("forms", []))
                    yield {"event": "progress", "data": json.dumps({
                        "message": f"[forms] 表单生成完成：{forms_count} 个",
                        "batch": data["forms"],
                    }, ensure_ascii=False)}
                if data.get("permissions"):
                    yield {"event": "progress", "data": json.dumps({
                        "message": "[permissions] 权限生成完成",
                        "batch": data["permissions"],
                    }, ensure_ascii=False)}
                yield {"event": "progress", "data": json.dumps({
                    "message": "[complete] 配置组装完成",
                    "data": data,
                    "parse_meta": parse_meta,
                }, ensure_ascii=False)}

        except Exception as e:
            err_msg = str(e) or repr(e) or type(e).__name__
            logger.error(f"文档解析失败: {err_msg}", exc_info=True)
            yield {"event": "error", "data": json.dumps({"message": f"文档解析失败: {err_msg}"}, ensure_ascii=False)}
            return

        if not data:
            yield {"event": "error", "data": json.dumps({"message": "配置生成失败：无数据"}, ensure_ascii=False)}
            return

        # 兜底：若推断仍未覆盖（例如进入了增量 diff 分支把 data 换了引用），
        # 这里再兜一次，确保最终保存到 DB / SSE done 事件里的 appName 不是默认值。
        if str(data.get("appName") or "").strip() in _DEFAULT_APP_NAMES:
            data["appName"] = _infer_app_name_from_doc(text, fname) or "业务应用"

        # 创建对话 + 消息（用独立 session）
        async with AsyncSessionLocal() as session:
            from app.models import Conversation, Message

            # 增量模式复用已有对话，首次上传创建新对话
            if existing_conversation_id:
                conv_id = existing_conversation_id
            else:
                conversation = Conversation(
                    user_id=user_id, tenant_id=tenant_id,
                    title=f"文档：{fname}", agent_type="builder", status="active"
                )
                session.add(conversation)
                await session.flush()
                conv_id = conversation.id

            # 系统上下文
            models_summary = []
            for m in data.get("models", []):
                field_names = [f.get("name", "") for f in m.get("fields", [])]
                models_summary.append(f"- {m.get('name')}：{', '.join(field_names)}")
            dicts_summary = [f"- {d.get('name')}（{d.get('code')}）：{', '.join(o.get('name','') for o in d.get('options',[]))}" for d in data.get("dicts", [])]
            roles_summary = [r.get('name', '') for r in data.get("roles", [])]

            context_content = f"用户上传了设计文档《{fname}》，已解析为以下配置摘要：\n\n"
            context_content += f"应用名：{data.get('appName', '业务应用')}\n"
            context_content += f"角色：{', '.join(roles_summary)}\n\n"
            context_content += f"数据字典：\n" + "\n".join(dicts_summary) + "\n\n"
            context_content += f"业务表单：\n" + "\n".join(models_summary) + "\n\n"
            context_content += "用户可能会要求修改配置。当用户确认后，生成完整的配置JSON。"

            session.add(Message(conversation_id=conv_id, role="system", content=context_content))

            # 保存原始文档内容（供后续创建 DocumentVersion 使用）
            doc_raw_msg = json.dumps({"type": "doc_raw", "filename": fname, "content": text}, ensure_ascii=False)
            session.add(Message(conversation_id=conv_id, role="system", content=doc_raw_msg))

            models_count = len(data.get("models", []))
            roles_count = len(data.get("roles", []))
            dicts_count = len(data.get("dicts", []))
            if is_incremental and v1_parsed_config:
                # 增量模式：用 config_diff 展示差异（会自动完成编码继承）
                v1_for_diff = v1_parsed_config
                resource_diff = compute_config_diff(v1_for_diff, data)
                # 使用编码继承后的配置，确保 V1 的 code 被保留
                if resource_diff.normalized_new_config:
                    data = resource_diff.normalized_new_config

            # 保存完整配置 JSON 作为 system 消息（刷新页面时可恢复）
            config_msg = '```json\n' + _dump_preview_config(data) + '\n```'
            session.add(Message(conversation_id=conv_id, role="system", content=config_msg))

            # 保存原始文档内容（用于后续创建 DocumentVersion）
            doc_msg = '```doc_raw\n' + json.dumps({"filename": fname, "raw_content": text}, ensure_ascii=False) + '\n```'
            session.add(Message(conversation_id=conv_id, role="system", content=doc_msg))

            # 自动保存 DocumentVersion（conversation_id 关联，application_id 待后续绑定）
            import hashlib
            # 检查同一 conversation 下已有版本号
            existing_ver_result = await session.execute(
                select(sa_func.max(DocumentVersion.version))
                .where(DocumentVersion.conversation_id == conv_id)
            )
            max_ver = existing_ver_result.scalar() or 0
            new_version = max_ver + 1

            config_json_str = _dump_parsed_config(data)
            rendered_doc = _render_doc_content_from_config(
                data.get("appName", ""),
                data.get("appCode", ""),
                data,
            )

            doc_ver = DocumentVersion(
                application_id=None,
                conversation_id=conv_id,
                version=new_version,
                filename=fname,
                content_hash=hashlib.sha256(config_json_str.encode()).hexdigest(),
                raw_content=rendered_doc,
                parsed_config=config_json_str,
                parent_version=max_ver if max_ver > 0 else None,
                summary=f"{models_count} 模型, {dicts_count} 字典, {roles_count} 角色",
            )
            session.add(doc_ver)

            await session.commit()

            done_data = {
                "conversation_id": conv_id,
                "preview": data,
                "rendered_doc": rendered_doc,
                "parse_meta": parse_meta,
                "version": new_version,
                "is_incremental": is_incremental,
            }
            # 增量模式下额外返回 diff 信息
            if is_incremental and v1_parsed_config:
                resource_diff_dict = resource_diff.to_dict()
                done_data["diff"] = resource_diff_dict

            yield {
                "event": "done",
                "data": json.dumps(done_data, ensure_ascii=False)
            }

    from sse_starlette.sse import EventSourceResponse
    return EventSourceResponse(event_generator())


# ── 文档驱动增量开发 ──────────────────────────────────


class SelectionsUpdate(BaseModel):
    """更新 change plan 中 actions 的选择状态"""
    selections: dict  # {action_id: bool}


def _merge_configs(v1_config: dict, partial_v2_config: dict, text_diff: dict) -> dict:
    """合并 V1 未变更部分 + V2 变更部分（AI 只解析了变更章节）。

    策略：以 V1 config 为基础，用 partial_v2_config（变更章节的解析结果）覆盖/补充。
    - partial_v2_config 中的 models/dicts/roles：如果 code 匹配 V1 则替换，否则新增
    - V1 中不在 partial_v2_config 中出现的（未变更章节的数据）：保留
    - removed 章节对应的数据：不包含在 partial_v2_config 中，需要从 V1 移除
    """
    from copy import deepcopy

    merged = deepcopy(v1_config)

    # 收集变更解析出的 codes
    v2_model_codes = {m.get("code", ""): m for m in partial_v2_config.get("models", []) if m.get("code")}
    v2_dict_codes = {d.get("code", ""): d for d in partial_v2_config.get("dicts", []) if d.get("code")}
    v2_role_codes = {r.get("code", ""): r for r in partial_v2_config.get("roles", []) if r.get("code")}

    # 更新 models：替换已存在的，追加新增的
    existing_model_codes = {m.get("code", "") for m in merged.get("models", [])}
    new_models = []
    for m in merged.get("models", []):
        code = m.get("code", "")
        if code in v2_model_codes:
            new_models.append(v2_model_codes[code])  # 替换为新版本
        else:
            new_models.append(m)  # 保留未变更的
    # 追加全新的模型
    for code, m in v2_model_codes.items():
        if code not in existing_model_codes:
            new_models.append(m)
    merged["models"] = new_models

    # 更新 dicts
    existing_dict_codes = {d.get("code", "") for d in merged.get("dicts", [])}
    new_dicts = []
    for d in merged.get("dicts", []):
        code = d.get("code", "")
        if code in v2_dict_codes:
            new_dicts.append(v2_dict_codes[code])
        else:
            new_dicts.append(d)
    for code, d in v2_dict_codes.items():
        if code not in existing_dict_codes:
            new_dicts.append(d)
    merged["dicts"] = new_dicts

    # 更新 roles
    existing_role_codes = {r.get("code", "") for r in merged.get("roles", [])}
    new_roles = []
    for r in merged.get("roles", []):
        code = r.get("code", "")
        if code in v2_role_codes:
            new_roles.append(v2_role_codes[code])
        else:
            new_roles.append(r)
    for code, r in v2_role_codes.items():
        if code not in existing_role_codes:
            new_roles.append(r)
    merged["roles"] = new_roles

    # 更新 appName（如果变更解析结果中有）
    if partial_v2_config.get("appName"):
        merged["appName"] = partial_v2_config["appName"]

    return merged


def _remove_deleted_from_config(v1_config: dict, text_diff: dict) -> dict:
    """当只有删除章节（无新增/修改）时，从 V1 config 中移除被删除章节对应的内容。

    注意：由于章节标题和 config 中的 model/dict 名称不一定完全对应，
    这里采取保守策略 — 只返回 V1 config 的副本。
    真正的删除判断由后续的 semantic_diff 来处理。
    """
    from copy import deepcopy
    return deepcopy(v1_config)


@router.post("/{app_id}/upload-doc-version")
async def upload_doc_version(
    app_id: int,
    file: UploadFile = File(...),
    conversation_id: int = Form(...),
    ctx: Annotated[AuthContext, Depends(get_auth_context)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """上传新版本设计文档，AI 解析后与当前配置做语义对比（SSE 流式返回进度）"""
    if not file.filename or not file.filename.endswith('.md'):
        raise HTTPException(status_code=400, detail="仅支持 .md 格式文件")

    # 加载应用
    result = await db.execute(
        select(Application).where(Application.id == app_id, Application.tenant_id == ctx.tenant_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    await check_resource_permission(ctx, db, app, "application", Action.EDIT)

    content_bytes = await file.read()
    text = content_bytes.decode('utf-8')
    fname = file.filename or ""

    # 获取租户 LLM 配置（供 AI 解析使用）
    from app.routes.chat import _get_tenant_llm_config as _get_llm_cfg
    _tenant_llm_cfg = await _get_llm_cfg(db, ctx.tenant_id)

    # 提前获取需要的值（SSE generator 不能用原始 db session）
    app_id_val = app.id
    tenant_id_val = ctx.tenant_id
    current_config_str = app.config_preview
    doc_llm_cfg = await _resolve_builder_llm_cfg(
        db,
        tenant_id_val,
        conversation_id=conversation_id,
    )

    async def event_generator():
        from app.database import AsyncSessionLocal
        from app.doc_differ import build_structure_index, semantic_diff, diff_to_actions, compute_hash
        from app.config_diff import compute_config_diff
        from app.doc_text_differ import diff_sections, get_diff_stats
        import hashlib

        current_step = "初始化"

        try:
            current_step = "读取文档内容"
            yield {"event": "progress", "data": json.dumps({"step": "读取文档内容..."}, ensure_ascii=False)}

            # 1. 计算 hash
            content_hash = compute_hash(text)

            # 2. 检查是否与最新版本重复 & 获取 V1 文档版本
            v1_doc: Optional[dict] = None
            async with AsyncSessionLocal() as session:
                # 只和最新版本比较 hash（允许回退到旧版本）
                latest_result = await session.execute(
                    select(DocumentVersion).where(
                        DocumentVersion.application_id == app_id_val,
                    ).order_by(DocumentVersion.version.desc()).limit(1)
                )
                latest_ver = latest_result.scalar_one_or_none()
                if latest_ver and latest_ver.content_hash == content_hash:
                    yield {"event": "error", "data": json.dumps({"message": "文档内容未变化，无需上传"}, ensure_ascii=False)}
                    return

                # 3. 获取当前最大 version 及其 DocumentVersion 记录
                max_ver_result = await session.execute(
                    select(sa_func.max(DocumentVersion.version)).where(
                        DocumentVersion.application_id == app_id_val
                    )
                )
                max_ver = max_ver_result.scalar() or 0
                new_version = max_ver + 1

                # 获取 V1 文档记录（用于文本对比）
                if max_ver > 0:
                    v1_result = await session.execute(
                        select(DocumentVersion).where(
                            DocumentVersion.application_id == app_id_val,
                            DocumentVersion.version == max_ver,
                        )
                    )
                    v1_doc_obj = v1_result.scalar_one_or_none()
                    if v1_doc_obj:
                        # 提取需要的字段，避免 session 外访问
                        v1_doc = {
                            "raw_content": v1_doc_obj.raw_content,
                            "parsed_config": v1_doc_obj.parsed_config,
                            "version": v1_doc_obj.version,
                        }

            current_step = "解析文档结构"
            yield {"event": "progress", "data": json.dumps({"step": "解析文档结构..."}, ensure_ascii=False)}

            # 4. 构建章节索引
            structure_index = build_structure_index(text)

            # ── 全量解析新文档（纯代码优先，失败模块 LLM 修复）──
            from app.doc_pipeline import parse_document

            if v1_doc and v1_doc.get("raw_content"):
                # 有旧文档时先做文本对比，告知变化情况
                current_step = "对比文档章节"
                yield {"event": "progress", "data": json.dumps({"step": "text_diff", "message": "正在对比文档章节..."}, ensure_ascii=False)}
                text_diff = diff_sections(v1_doc["raw_content"], text)
                diff_stats = get_diff_stats(text_diff)
                yield {"event": "progress", "data": json.dumps({
                    "step": "text_diff",
                    "data": diff_stats,
                    "message": f"章节对比完成：新增 {diff_stats['added']}、修改 {diff_stats['modified']}、删除 {diff_stats['removed']}、未变更 {diff_stats['unchanged']}",
                }, ensure_ascii=False)}

            current_step = "解析文档"
            progress_messages = []

            async def _on_progress(msg: str, *, batch=None):
                progress_messages.append((msg, batch))

            yield {"event": "progress", "data": json.dumps({"step": "parse", "message": "检查文档标准度..."}, ensure_ascii=False)}
            parse_result = await parse_document(text, llm_cfg=doc_llm_cfg, on_progress=_on_progress)
            parse_meta = parse_result.get("parse_meta", {}) if isinstance(parse_result, dict) else {}

            for item in progress_messages:
                msg, batch = item if isinstance(item, tuple) else (item, None)
                payload = {"step": "parse", "message": msg}
                if batch is not None:
                    payload["batch"] = batch
                yield {"event": "progress", "data": json.dumps(payload, ensure_ascii=False)}

            v2_config = parse_result.get("data", parse_result)

            current_step = "对比资源差异"
            yield {"event": "progress", "data": json.dumps({"step": "对比资源差异..."}, ensure_ascii=False)}

            # 6. 加载 V1 配置（从应用当前 config_preview）
            v1_config: dict = {}
            if current_config_str:
                try:
                    loaded = loads_if_str(current_config_str)
                    v1_config = loaded.get("data", loaded)
                except Exception:
                    pass

            # 7. 资源级差异对比（用于前端展示，会自动完成编码继承）
            resource_diff = compute_config_diff(v1_config, v2_config)
            # 使用编码继承后的配置，确保 V1 的 code 被保留
            if resource_diff.normalized_new_config:
                v2_config = resource_diff.normalized_new_config
            resource_diff_dict = resource_diff.to_dict()

            # 8. 语义对比（用于生成可勾选 actions）
            diff = semantic_diff(v1_config, v2_config)

            # 9. 生成 patch actions
            actions = diff_to_actions(diff, v2_config)

            # 10. 生成摘要
            summary = resource_diff.summary or f"文档 V{new_version} 资源变更分析完成"

            current_step = "保存版本记录"
            yield {"event": "progress", "data": json.dumps({"step": "保存版本记录..."}, ensure_ascii=False)}

            # 11. 创建 DocumentVersion + ChangePlan
            async with AsyncSessionLocal() as session:
                app_result = await session.execute(
                    select(Application).where(Application.id == app_id_val)
                )
                app_obj = app_result.scalar_one()
                rendered_doc = _render_doc_content_from_config(
                    app_obj.app_name or v2_config.get("appName", ""),
                    app_obj.app_code or v2_config.get("appCode", ""),
                    v2_config,
                )
                config_json = _dump_parsed_config(v2_config)

                doc_ver = DocumentVersion(
                    application_id=app_id_val,
                    version=new_version,
                    filename=fname,
                    content_hash=hashlib.sha256(config_json.encode()).hexdigest(),
                    raw_content=rendered_doc,
                    structure_index=json.dumps(structure_index, ensure_ascii=False),
                    parsed_config=config_json,
                    parent_version=max_ver if max_ver > 0 else None,
                    summary=summary,
                )
                session.add(doc_ver)
                await session.flush()

                change_plan = ChangePlan(
                    application_id=app_id_val,
                    conversation_id=conversation_id,
                    from_version=max_ver,
                    to_version=new_version,
                    diff_summary=json.dumps(resource_diff_dict, ensure_ascii=False),
                    actions=json.dumps(actions, ensure_ascii=False),
                    status="pending",
                )
                session.add(change_plan)

                # 更新应用：文档版本 + 配置 + 状态
                app_obj.current_doc_version = new_version
                # 关键：用 V2 配置更新 config_preview（保留原始 appName）
                if app_obj.app_name:
                    v2_config["appName"] = app_obj.app_name
                app_obj.config_preview = _dump_preview_config(v2_config)
                # 上传了更新文档且生成了变更计划，但还未执行更新，进入“更新中”状态。
                if app_obj.apaas_app_id or app_obj.status in ("completed", "updating"):
                    app_obj.status = "updating"
                else:
                    app_obj.status = "draft"
                # 在 generation_state 中记录配置版本变更
                if app_obj.generation_state:
                    try:
                        from datetime import datetime as dt
                        gs = json.loads(app_obj.generation_state)
                        gs["config_version"] = new_version
                        gs["config_updated_at"] = dt.utcnow().isoformat()
                        app_obj.generation_state = json.dumps(gs, ensure_ascii=False)
                    except Exception:
                        pass

                await session.commit()
                await session.refresh(change_plan)

                yield {
                    "event": "done",
                    "data": json.dumps({
                        "version": new_version,
                        "from_version": max_ver,
                        "to_version": new_version,
                        "summary": summary,
                        "diff": resource_diff_dict,
                        "semantic_diff": diff,
                        "actions": actions,
                        "change_plan_id": change_plan.id,
                        "is_first_version": max_ver == 0,
                        "parsed_config": v2_config,
                        "rendered_doc": rendered_doc,
                        "parse_meta": parse_meta,
                    }, ensure_ascii=False),
                }

        except Exception as e:
            logger.error(f"文档版本上传失败: {e}", exc_info=True)
            detail = str(e).strip() or repr(e).strip() or e.__class__.__name__
            yield {
                "event": "error",
                "data": json.dumps({
                    "message": f"处理失败（步骤：{current_step}）：{detail}",
                    "step": current_step,
                    "error_type": e.__class__.__name__,
                }, ensure_ascii=False)
            }

    return EventSourceResponse(event_generator())


@router.get("/{app_id}/change-plans/{plan_id}")
async def get_change_plan(
    app_id: int,
    plan_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """获取变更计划详情"""
    # 验证应用权限
    result = await db.execute(
        select(Application).where(Application.id == app_id, Application.tenant_id == ctx.tenant_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    await check_resource_permission(ctx, db, app, "application", Action.VIEW)

    result = await db.execute(
        select(ChangePlan).where(ChangePlan.id == plan_id, ChangePlan.application_id == app_id)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="变更计划不存在")

    return {
        "id": plan.id,
        "application_id": plan.application_id,
        "conversation_id": plan.conversation_id,
        "from_version": plan.from_version,
        "to_version": plan.to_version,
        "diff_summary": loads_if_str(plan.diff_summary),
        "actions": loads_if_str(plan.actions),
        "status": plan.status,
        "created_at": str(plan.created_at) if plan.created_at else None,
        "executed_at": str(plan.executed_at) if plan.executed_at else None,
    }


@router.put("/{app_id}/change-plans/{plan_id}/selections")
async def update_change_plan_selections(
    app_id: int,
    plan_id: int,
    body: SelectionsUpdate,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """更新变更计划中各 action 的勾选状态"""
    result = await db.execute(
        select(Application).where(Application.id == app_id, Application.tenant_id == ctx.tenant_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    await check_resource_permission(ctx, db, app, "application", Action.EDIT)

    result = await db.execute(
        select(ChangePlan).where(ChangePlan.id == plan_id, ChangePlan.application_id == app_id)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="变更计划不存在")
    if plan.status != "pending":
        raise HTTPException(status_code=400, detail=f"变更计划状态为 {plan.status}，不能修改")

    actions = loads_if_str(plan.actions)
    for action in actions:
        aid = action.get("id")
        if aid and aid in body.selections:
            action["selected"] = body.selections[aid]

    plan.actions = json.dumps(actions, ensure_ascii=False)
    await db.commit()
    return {"ok": True, "actions": actions}


@router.post("/{app_id}/change-plans/{plan_id}/execute")
async def execute_change_plan(
    app_id: int,
    plan_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """执行变更计划，将选中的 actions 应用到 config_preview 并同步到得帆云平台（SSE 流式返回进度）"""
    result = await db.execute(
        select(Application).where(Application.id == app_id, Application.tenant_id == ctx.tenant_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    await check_resource_permission(ctx, db, app, "application", Action.EDIT)

    result = await db.execute(
        select(ChangePlan).where(ChangePlan.id == plan_id, ChangePlan.application_id == app_id)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="变更计划不存在")
    if plan.status not in ("pending", "confirmed"):
        raise HTTPException(status_code=400, detail=f"变更计划状态为 {plan.status}，不能执行")

    apaas_app_id = app.apaas_app_id
    app_name = app.app_name
    apaas_token = None
    apaas_base_url = None
    apaas_tenant_id = None
    platform_client_error = None

    try:
        from app.routes.incremental_update import _get_platform_client_for_app
        platform_client = await _get_platform_client_for_app(app, ctx.user, db)
        apaas_token = getattr(platform_client, "token", None)
        apaas_base_url = getattr(platform_client, "base_url", None)
        apaas_tenant_id = getattr(platform_client, "tenant_id", None)
    except Exception as e:
        platform_client_error = str(e)
        logger.warning(f"执行变更计划时获取平台连接失败: {e}")

    app_id_val = app.id
    current_config_str = app.config_preview
    plan_id_val = plan.id
    actions_str = plan.actions
    plan_from_version = plan.from_version
    plan_to_version = plan.to_version

    async def event_generator():
        from app.database import AsyncSessionLocal
        from app.doc_differ import apply_actions_to_config
        from app.apaas_client import APaaSClient
        from app.config_diff import compute_config_diff
        from app.incremental_executor import IncrementalExecutor, fetch_remote_data

        try:
            yield {"event": "progress", "data": json.dumps({"step": "加载当前配置..."}, ensure_ascii=False)}

            # 加载基础配置：优先使用 from_version 的 parsed_config（避免 config_preview 已被更新为 V2 导致 apply_actions 重复）
            current_config: dict = {}
            async with AsyncSessionLocal() as session:
                from_doc = await session.execute(
                    select(DocumentVersion).where(
                        DocumentVersion.application_id == app_id_val,
                        DocumentVersion.version == plan_from_version
                    )
                )
                from_doc_obj = from_doc.scalar_one_or_none()
                if from_doc_obj and from_doc_obj.parsed_config:
                    try:
                        current_config = loads_if_str(from_doc_obj.parsed_config)
                    except Exception:
                        pass

            # 回退：如果没有找到 from_version 的配置，使用 config_preview
            if not current_config and current_config_str:
                try:
                    loaded = loads_if_str(current_config_str)
                    current_config = loaded.get("data", loaded)
                except Exception:
                    pass

            actions = loads_if_str(actions_str)
            selected = [a for a in actions if a.get("selected", True)]

            yield {"event": "progress", "data": json.dumps({"step": f"应用 {len(selected)} 项变更..."}, ensure_ascii=False)}

            # 应用 patch 得到 new_config（基于 from_version 的配置）
            new_config = apply_actions_to_config(current_config, actions)

            # 判断是否需要同步到平台
            can_sync = apaas_token and apaas_base_url and apaas_app_id
            sync_result = None
            sync_errors = []

            if can_sync:
                yield {"event": "progress", "data": json.dumps({"step": "同步到得帆云平台..."}, ensure_ascii=False)}
                try:
                    # 创建 APaaSClient
                    client = APaaSClient(
                        base_url=apaas_base_url,
                        token=apaas_token,
                        tenant_id=apaas_tenant_id
                    )

                    # 获取远程数据
                    yield {"event": "progress", "data": json.dumps({"step": "获取平台现有资源..."}, ensure_ascii=False)}
                    remote_data = await fetch_remote_data(client, apaas_app_id)

                    # 计算差异（会自动完成编码继承）
                    yield {"event": "progress", "data": json.dumps({"step": "计算资源变更差异..."}, ensure_ascii=False)}
                    diff = compute_config_diff(current_config, new_config, remote_data)
                    # 使用编码继承后的配置，确保 V1 的 code 被保留
                    if diff.normalized_new_config:
                        new_config = diff.normalized_new_config

                    if diff.has_changes:
                        # 创建执行器并执行
                        executor = IncrementalExecutor(
                            client,
                            apaas_app_id,
                            app_name,
                            target_config=new_config,
                        )

                        # 流式执行差异
                        async for progress in executor.execute_diff_stream(diff):
                            if progress.get("type") == "complete":
                                sync_result = progress.get("result", {})
                                if not sync_result.get("success", True):
                                    sync_errors.extend(sync_result.get("errors", []) or ["平台同步失败"])
                            elif progress.get("type") == "error":
                                sync_errors.append(progress.get("message", "未知错误"))
                            else:
                                # 转发执行进度
                                step_msg = progress.get("step", "")
                                yield {"event": "progress", "data": json.dumps({"step": f"平台同步: {step_msg}"}, ensure_ascii=False)}
                    else:
                        logger.info("无平台资源变更需要同步")
                        sync_result = {"message": "无变更需要同步"}

                except Exception as e:
                    logger.warning(f"平台同步失败: {e}", exc_info=True)
                    sync_errors.append(str(e))
            else:
                if apaas_app_id and (not apaas_token or not apaas_base_url):
                    missing_parts = []
                    if not apaas_token:
                        missing_parts.append("平台登录凭证")
                    if not apaas_base_url:
                        missing_parts.append("平台地址")
                    detail = f"缺少{ '、'.join(missing_parts) }，无法同步到平台"
                    if platform_client_error:
                        detail = f"{detail}（{platform_client_error}）"
                    sync_errors.append(detail)
                elif not apaas_app_id:
                    sync_errors.append("应用尚未关联平台应用，无法执行平台更新")

            if sync_errors:
                detail = "；".join([str(err) for err in sync_errors if err]) or "平台同步失败"
                yield {
                    "event": "error",
                    "data": json.dumps({
                        "message": f"平台执行失败：{detail}",
                        "sync_errors": sync_errors,
                        "sync_result": sync_result,
                    }, ensure_ascii=False),
                }
                return

            yield {"event": "progress", "data": json.dumps({"step": "保存本地配置..."}, ensure_ascii=False)}

            # 保存本地配置
            async with AsyncSessionLocal() as session:
                app_result = await session.execute(
                    select(Application).where(Application.id == app_id_val)
                )
                app_obj = app_result.scalar_one()
                app_obj.config_preview = _dump_preview_config(new_config)

                plan_result = await session.execute(
                    select(ChangePlan).where(ChangePlan.id == plan_id_val)
                )
                plan_obj = plan_result.scalar_one()
                plan_obj.status = "completed"
                plan_obj.executed_at = datetime.utcnow()

                # 更新应用状态为已部署
                app_result = await session.execute(
                    select(Application).where(Application.id == app_id)
                )
                app_obj = app_result.scalar_one()
                app_obj.status = "completed"

                await session.commit()

            # 构建响应数据
            response_data = {
                "config": new_config,
                "applied_count": len(selected),
                "total_count": len(actions),
                "platform_synced": can_sync and not sync_errors,
            }
            if sync_result:
                response_data["sync_result"] = sync_result
            if sync_errors:
                response_data["sync_errors"] = sync_errors

            yield {
                "event": "done",
                "data": json.dumps(response_data, ensure_ascii=False),
            }

        except Exception as e:
            logger.error(f"变更计划执行失败: {e}", exc_info=True)
            yield {"event": "error", "data": json.dumps({"message": f"执行失败: {str(e)}"}, ensure_ascii=False)}

    return EventSourceResponse(event_generator())


@router.get("/{app_id}/doc-versions")
async def list_doc_versions(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """获取应用的文档版本历史"""
    result = await db.execute(
        select(Application).where(Application.id == app_id, Application.tenant_id == ctx.tenant_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    await check_resource_permission(ctx, db, app, "application", Action.VIEW)

    result = await db.execute(
        select(DocumentVersion)
        .where(DocumentVersion.application_id == app_id)
        .order_by(desc(DocumentVersion.version))
    )
    versions = result.scalars().all()

    # 同时加载关联的 change plans
    result = await db.execute(
        select(ChangePlan)
        .where(ChangePlan.application_id == app_id)
        .order_by(desc(ChangePlan.created_at))
    )
    plans = result.scalars().all()
    plans_by_to_version = {}
    for p in plans:
        plans_by_to_version.setdefault(p.to_version, []).append(p)

    items = []
    for v in versions:
        parsed_config = await _ensure_doc_version_parsed_config(db, v)
        rendered_content = await _ensure_doc_version_rendered_content(db, app, v)
        related_plans = plans_by_to_version.get(v.version, [])
        items.append({
            "id": v.id,
            "version": v.version,
            "filename": v.filename,
            "content_hash": v.content_hash,
            "raw_content": rendered_content,
            "parsed_config": parsed_config,
            "summary": v.summary,
            "structure_index": json.loads(v.structure_index) if v.structure_index else None,
            "created_at": str(v.created_at) if v.created_at else None,
            "change_plans": [
                {
                    "id": p.id,
                    "from_version": p.from_version,
                    "to_version": p.to_version,
                    "status": p.status,
                    "created_at": str(p.created_at) if p.created_at else None,
                }
                for p in related_plans
            ],
        })

    await db.commit()

    return {
        "current_version": app.current_doc_version,
        "versions": items,
    }


@router.delete("/{app_id}/doc-versions/{version_id}")
async def delete_doc_version(
    app_id: int,
    version_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """删除指定文档版本，并同步应用当前版本指针。"""
    result = await db.execute(
        select(Application).where(Application.id == app_id, Application.tenant_id == ctx.tenant_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    await check_resource_permission(ctx, db, app, "application", Action.EDIT)

    result = await db.execute(
        select(DocumentVersion).where(
            DocumentVersion.id == version_id,
            DocumentVersion.application_id == app_id,
        )
    )
    doc_version = result.scalar_one_or_none()
    if not doc_version:
        raise HTTPException(status_code=404, detail="文档版本不存在")

    deleted_version_no = doc_version.version

    await db.execute(
        delete(ChangePlan).where(
            ChangePlan.application_id == app_id,
            (ChangePlan.to_version == deleted_version_no) | (ChangePlan.from_version == deleted_version_no),
        )
    )
    await db.delete(doc_version)
    await db.flush()

    result = await db.execute(
        select(DocumentVersion)
        .where(DocumentVersion.application_id == app_id)
        .order_by(desc(DocumentVersion.version))
    )
    remaining_versions = result.scalars().all()

    latest = remaining_versions[0] if remaining_versions else None
    app.current_doc_version = latest.version if latest else None
    if latest and latest.parsed_config:
        try:
            parsed = loads_if_str(latest.parsed_config)
            app.config_preview = _dump_preview_config(parsed)
        except Exception:
            logger.warning("删除文档版本后同步 config_preview 失败", exc_info=True)
            app.config_preview = None
    else:
        app.config_preview = None

    await db.commit()
    return {
        "ok": True,
        "deleted_version": deleted_version_no,
        "current_version": app.current_doc_version,
    }


@router.get("/doc-versions-by-conversation/{conversation_id}")
async def list_doc_versions_by_conversation(
    conversation_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """通过 conversation_id 获取文档版本（在 Application 创建之前使用）"""
    from app.models import Conversation
    # 验证对话属于当前用户/租户
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == ctx.tenant_id,
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")

    result = await db.execute(
        select(DocumentVersion)
        .where(DocumentVersion.conversation_id == conversation_id)
        .order_by(desc(DocumentVersion.version))
    )
    versions = result.scalars().all()

    items = []
    for v in versions:
        parsed_config = await _ensure_doc_version_parsed_config(db, v)
        rendered_content = await _ensure_doc_version_rendered_content(db, None, v)
        items.append({
            "id": v.id,
            "version": v.version,
            "filename": v.filename,
            "content_hash": v.content_hash,
            "raw_content": rendered_content,
            "parsed_config": parsed_config,
            "summary": v.summary,
            "structure_index": json.loads(v.structure_index) if v.structure_index else None,
            "created_at": str(v.created_at) if v.created_at else None,
        })

    await db.commit()

    return {
        "versions": items,
    }


# ── 获取单个应用信息 ──

@router.get("/{app_id}")
async def get_application(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """获取单个应用详情（包含平台链接）"""
    result = await db.execute(
        select(Application).where(Application.id == app_id, Application.tenant_id == ctx.tenant_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")

    # 获取关联的平台环境
    env_base_url = None
    env_tenant_id = None
    if app.platform_env_id:
        env_result = await db.execute(select(PlatformEnv).where(PlatformEnv.id == app.platform_env_id))
        env = env_result.scalar_one_or_none()
        if env:
            env_base_url = env.base_url
            env_tenant_id = env.platform_tenant_id

    apaas_url = None
    if app.apaas_app_id:
        apaas_url = _build_apaas_url(str(app.apaas_app_id), env_base_url, env_tenant_id)

    return {
        "id": app.id,
        "app_name": app.app_name,
        "app_code": app.app_code,
        "status": app.status,
        "apaas_app_id": app.apaas_app_id,
        "apaas_url": apaas_url,
        "platform_env_id": app.platform_env_id,
        "created_at": str(app.created_at) if app.created_at else None,
    }


# ── API 调用日志 ──

@router.get("/{app_id}/api-logs")
async def list_api_logs(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    step_key: Optional[str] = Query(None),
    success: Optional[bool] = Query(None),
):
    """查询应用的平台 API 调用日志（分页）"""
    # 验证应用归属
    result = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")

    await check_resource_permission(ctx, db, app, "application", Action.VIEW)

    # 构建查询
    query = select(ApiCallLog).where(ApiCallLog.application_id == app_id)
    count_query = select(sa_func.count()).select_from(ApiCallLog).where(ApiCallLog.application_id == app_id)

    if step_key:
        query = query.where(ApiCallLog.step_key == step_key)
        count_query = count_query.where(ApiCallLog.step_key == step_key)
    if success is not None:
        query = query.where(ApiCallLog.success == success)
        count_query = count_query.where(ApiCallLog.success == success)

    # 总数
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # 分页查询
    query = query.order_by(desc(ApiCallLog.created_at)).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    logs = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": log.id,
                "step_key": log.step_key,
                "method": log.method,
                "url": log.url,
                "request_body": log.request_body,
                "response_status": log.response_status,
                "response_body": log.response_body,
                "success": log.success,
                "error_message": log.error_message,
                "elapsed_ms": log.elapsed_ms,
                "created_at": str(log.created_at) if log.created_at else None,
            }
            for log in logs
        ],
    }


# ── AnalysisResult → AppConfig 直接转换（无 LLM） ──────────────────────────


class ConvertConfigRequest(BaseModel):
    doc_result: dict


@router.post("/convert-config")
async def convert_config(
    body: ConvertConfigRequest,
    auth: AuthContext = Depends(get_auth_context),
):
    """
    Convert a requirements AnalysisResult JSON directly to AppConfig format.
    Pure Python transformation — no LLM calls, no markdown roundtrip.
    """
    try:
        config = convert_analysis_to_app_config(body.doc_result)
        return {"config": config}
    except Exception as e:
        logger.error(f"Config conversion failed: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"配置转换失败: {str(e)}")
