"""MCP tools for updating aPaaS form components."""
from __future__ import annotations

import copy
import json
from typing import Any

# ─── 表单单组件 update ─────────────────────────────────────────────────────
# 微调单个字段的 label / required / placeholder / defaultValue / 选项之类，
# 不用走 SPEC 文档流。底层走 query_form_config → 改 → save_form_config 全量回写。

# 常用 updates 字段（白名单提示给 LLM，但不强制 — apaas 组件 schema 字段还有不少）
_FORM_COMPONENT_COMMON_FIELDS = (
    "label", "required", "placeholder", "defaultValue",
    "chooseOptions", "dictionaryChooseOptions", "multicolor",
    "readOnly", "readonly", "hidden", "description", "tooltip",
    "minValue", "maxValue", "maxLength",
    "width", "mobileWidth", "onlyCreateEdit", "uniqueCheck", "saveWithHidden",
    "validatorStatus", "validatorList", "documentNumRules",
    "source", "chooseType", "dictionaryMulticolorStatus", "customComponentConfig",
)

_FORM_COMPONENT_WIDTH_VALUES = {3, 4, 6, 8, 9, 12}
_FORM_COMPONENT_MOBILE_WIDTH_VALUES = {6, 12}
_FORM_COMPONENT_SENSITIVE_KEYS = ("authorization", "token", "secret", "apikey", "api_key", "password")


def _redact_component_value(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if any(s in key_text for s in _FORM_COMPONENT_SENSITIVE_KEYS):
                out[key] = "***"
            else:
                out[key] = _redact_component_value(item)
        return out
    if isinstance(value, list):
        return [_redact_component_value(item) for item in value]
    return value


def _form_components_from_config(form_config: dict) -> list:
    detail_page = form_config.get("detailPage") or {}
    components = detail_page.get("formComponents") or form_config.get("formComponents") or []
    if not isinstance(components, list):
        return []
    return components


def _component_identifier_summary(
    *,
    component_label: str = "",
    component_uuid: str = "",
    bo_code: str = "",
) -> dict[str, str]:
    return {
        "component_label": component_label.strip(),
        "component_uuid": component_uuid.strip(),
        "bo_code": bo_code.strip(),
    }


def _find_form_component(
    components: list,
    *,
    component_label: str = "",
    component_uuid: str = "",
    bo_code: str = "",
) -> tuple[dict, str]:
    """Find a form component with stable identifiers. Priority: uuid > boCode > label."""
    uuid_clean = component_uuid.strip()
    bo_code_clean = bo_code.strip()
    label_clean = component_label.strip()

    if not (uuid_clean or bo_code_clean or label_clean):
        raise ValueError("组件定位失败：component_uuid / bo_code / component_label 至少传一个")

    if uuid_clean:
        for component in components:
            if isinstance(component, dict) and str(component.get("uuid") or component.get("id") or "").strip() == uuid_clean:
                return component, "uuid"

    if bo_code_clean:
        for component in components:
            if not isinstance(component, dict):
                continue
            candidates = {
                str(component.get("boCode") or "").strip(),
                str(component.get("modelField") or "").strip(),
            }
            if bo_code_clean in candidates:
                return component, "bo_code"

    if label_clean:
        for component in components:
            if isinstance(component, dict) and str(component.get("label") or component.get("name") or "").strip() == label_clean:
                return component, "label"

    raise ValueError(
        "未找到表单组件："
        + json.dumps(
            _component_identifier_summary(
                component_label=component_label,
                component_uuid=component_uuid,
                bo_code=bo_code,
            ),
            ensure_ascii=False,
        )
    )


def _component_snapshot(component: dict, *, include_raw: bool = False) -> dict:
    snapshot = {
        "uuid": str(component.get("uuid") or component.get("id") or ""),
        "label": str(component.get("label") or component.get("name") or ""),
        "component_type": str(component.get("componentType") or ""),
        "bo_code": str(component.get("boCode") or ""),
        "model_field": str(component.get("modelField") or ""),
        "required": bool(component.get("required", False)),
        "hidden": bool(component.get("hidden", False)),
        "read_only": bool(component.get("readOnly", component.get("readonly", False))),
        "only_create_edit": bool(component.get("onlyCreateEdit", False)),
        "unique_check": bool(component.get("uniqueCheck", False)),
        "save_with_hidden": bool(component.get("saveWithHidden", False)),
        "width": component.get("width"),
        "mobile_width": component.get("mobileWidth"),
        "placeholder": component.get("placeholder"),
        "default_value": component.get("defaultValue"),
        "title_description": component.get("titleDescription"),
        "validator_status": component.get("validatorStatus"),
        "validator_list": _redact_component_value(component.get("validatorList") or []),
        "document_num_rules": _redact_component_value(component.get("documentNumRules") or []),
        "source": _redact_component_value(component.get("source") or {}),
        "choose_type": component.get("chooseType"),
        "choose_options_raw": _redact_component_value(component.get("chooseOptions") or []),
        "dictionary_choose_options_raw": _redact_component_value(component.get("dictionaryChooseOptions") or []),
        "custom_component_config": _redact_component_value(component.get("customComponentConfig") or {}),
    }
    if include_raw:
        snapshot["raw_component"] = _redact_component_value(component)
    return snapshot


def _component_diff(before: dict, after: dict) -> dict:
    fields = set(before.keys()) | set(after.keys())
    diff = {}
    for field in sorted(fields):
        before_value = before.get(field)
        after_value = after.get(field)
        if before_value != after_value:
            diff[field] = {
                "before": _redact_component_value(before_value),
                "after": _redact_component_value(after_value),
            }
    return diff


def _prepare_form_component_updates(component: dict, updates: dict) -> dict:
    prepared = copy.deepcopy(updates)
    merge_custom_config = prepared.pop("__merge_customComponentConfig__", None)
    if isinstance(merge_custom_config, dict):
        current = component.get("customComponentConfig")
        if not isinstance(current, dict):
            current = {}
        prepared["customComponentConfig"] = {
            **copy.deepcopy(current),
            **copy.deepcopy(merge_custom_config),
        }
    return prepared


def _apply_form_component_updates(
    form_config: dict,
    updates: dict,
    *,
    component_label: str = "",
    component_uuid: str = "",
    bo_code: str = "",
    validate_default_value: bool = False,
    expected_component_types: set[str] | None = None,
) -> dict:
    if not isinstance(updates, dict) or not updates:
        raise ValueError("updates 必须是非空 dict")

    components = _form_components_from_config(form_config)
    if not components:
        raise ValueError("表单配置里没有 detailPage.formComponents")

    component, match_by = _find_form_component(
        components,
        component_label=component_label,
        component_uuid=component_uuid,
        bo_code=bo_code,
    )
    component_type = str(component.get("componentType") or "")
    if expected_component_types and component_type not in expected_component_types:
        raise ValueError(
            f"组件类型不匹配：当前 componentType={component_type}，"
            f"期望 {sorted(expected_component_types)}"
        )

    prepared_updates = _prepare_form_component_updates(component, updates)
    if validate_default_value and "defaultValue" in prepared_updates:
        _validate_component_default_value(component, prepared_updates.get("defaultValue"))

    before = copy.deepcopy(component)
    component.update(prepared_updates)
    after = copy.deepcopy(component)
    return {
        "component": component,
        "before": before,
        "after": after,
        "diff": _component_diff(before, after),
        "match_by": match_by,
    }


def _component_option_value_set(component: dict) -> set[str]:
    options = component.get("dictionaryChooseOptions") or component.get("chooseOptions") or []
    values: set[str] = set()
    for option in options:
        if not isinstance(option, dict):
            if option is not None:
                values.add(str(option))
            continue
        for key in ("id", "value", "code"):
            value = option.get(key)
            if value is not None and str(value).strip():
                values.add(str(value).strip())
    return values


def _validate_component_default_value(component: dict, default_value: Any) -> None:
    if default_value in (None, ""):
        return

    option_values = _component_option_value_set(component)
    if not option_values:
        return

    default_values = default_value if isinstance(default_value, list) else [default_value]
    missing = [str(value) for value in default_values if str(value) not in option_values]
    if missing:
        raise ValueError(f"默认值 {missing} 不在组件选项里，可用值：{sorted(option_values)}")


def _normalize_select_component_options(options: list) -> list[dict]:
    if not isinstance(options, list) or not options:
        raise ValueError("options 必须是非空 list")

    normalized = []
    for index, option in enumerate(options):
        if isinstance(option, dict):
            option_id = str(option.get("id") or option.get("value") or option.get("code") or "").strip()
            label = str(option.get("label") or option.get("name") or option.get("text") or option_id).strip()
            if not option_id:
                option_id = label
            if not label:
                label = option_id
            if not option_id:
                raise ValueError(f"options[{index}] 缺 id/value/code/label")
            display_order = option.get("displayOrder")
            if display_order is None:
                display_order = index
            normalized.append({
                "id": option_id,
                "value": option_id,
                "code": option_id,
                "label": label,
                "name": label,
                "color": str(option.get("color") or ""),
                "displayOrder": int(display_order),
                "labelI18nAssociated": bool(option.get("labelI18nAssociated", False)),
            })
        elif isinstance(option, (str, int, float)):
            option_id = str(option).strip()
            if not option_id:
                raise ValueError(f"options[{index}] 为空")
            normalized.append({
                "id": option_id,
                "value": option_id,
                "code": option_id,
                "label": option_id,
                "name": option_id,
                "color": "",
                "displayOrder": index,
                "labelI18nAssociated": False,
            })
        else:
            raise ValueError(f"options[{index}] 必须是 dict / string / number")
    return normalized


def _build_component_behavior_updates(
    *,
    required: bool | None = None,
    hidden: bool | None = None,
    read_only: bool | None = None,
    only_create_edit: bool | None = None,
    unique_check: bool | None = None,
    save_with_hidden: bool | None = None,
    width: int | None = None,
    mobile_width: int | None = None,
    placeholder: str | None = None,
    title_description: str | None = None,
) -> dict:
    updates: dict[str, Any] = {}
    if required is not None:
        updates["required"] = bool(required)
    if hidden is not None:
        updates["hidden"] = bool(hidden)
    if read_only is not None:
        updates["readOnly"] = bool(read_only)
    if only_create_edit is not None:
        updates["onlyCreateEdit"] = bool(only_create_edit)
    if unique_check is not None:
        updates["uniqueCheck"] = bool(unique_check)
    if save_with_hidden is not None:
        updates["saveWithHidden"] = bool(save_with_hidden)
    if width is not None:
        if int(width) not in _FORM_COMPONENT_WIDTH_VALUES:
            raise ValueError(f"width 只能是 {sorted(_FORM_COMPONENT_WIDTH_VALUES)}")
        updates["width"] = int(width)
    if mobile_width is not None:
        if int(mobile_width) not in _FORM_COMPONENT_MOBILE_WIDTH_VALUES:
            raise ValueError(f"mobile_width 只能是 {sorted(_FORM_COMPONENT_MOBILE_WIDTH_VALUES)}")
        updates["mobileWidth"] = int(mobile_width)
    if placeholder is not None:
        updates["placeholder"] = str(placeholder)
    if title_description is not None:
        updates["titleDescription"] = str(title_description)
    return updates

def register(mcp, with_client):
    async def _save_form_component_updates(
        *,
        env_id: int,
        apaas_app_id: str,
        form_id: str,
        updates: dict,
        component_label: str = "",
        component_uuid: str = "",
        bo_code: str = "",
        op: str = "改表单组件",
        validate_default_value: bool = False,
        expected_component_types: set[str] | None = None,
        warnings: list[str] | None = None,
    ) -> dict:
        app_id_clean = apaas_app_id.strip()
        form_id_clean = form_id.strip()
        identifiers = _component_identifier_summary(
            component_label=component_label,
            component_uuid=component_uuid,
            bo_code=bo_code,
        )
        if not (app_id_clean and form_id_clean):
            return {"ok": False, "error_code": "INVALID_PARAMS", "message": "apaas_app_id+form_id 都必填"}
        if not any(identifiers.values()):
            return {
                "ok": False,
                "error_code": "INVALID_PARAMS",
                "message": "component_uuid / bo_code / component_label 至少传一个",
            }
        if not isinstance(updates, dict) or not updates:
            return {"ok": False, "error_code": "INVALID_UPDATES", "message": "updates 必须是非空 dict"}

        async def _run(client):
            form_config = await client.query_form_config(app_id_clean, form_id_clean)
            try:
                patch = _apply_form_component_updates(
                    form_config,
                    updates,
                    component_label=component_label,
                    component_uuid=component_uuid,
                    bo_code=bo_code,
                    validate_default_value=validate_default_value,
                    expected_component_types=expected_component_types,
                )
            except ValueError as exc:
                message = str(exc)
                return {
                    "ok": False,
                    "error_code": "COMPONENT_NOT_FOUND" if "未找到" in message else "INVALID_COMPONENT_UPDATE",
                    "message": message,
                    **identifiers,
                }

            diff = patch["diff"]
            if not diff:
                component = patch["component"]
                component_label_resolved = str(component.get("label") or component_label or "")
                return {
                    "ok": True,
                    "changed": False,
                    "form_id": form_id_clean,
                    "matched_by": patch["match_by"],
                    **identifiers,
                    "resolved_component": _component_snapshot(component),
                    "updated_fields": [],
                    "diff": {},
                    "warnings": warnings or [],
                    "message": f"组件「{component_label_resolved or component_uuid or bo_code}」无需更新",
                }
            await client.save_form_config(app_id_clean, form_config)
            saved_config = await client.query_form_config(app_id_clean, form_id_clean)

            after_component = patch["component"]
            after_uuid = str(after_component.get("uuid") or after_component.get("id") or component_uuid or "")
            after_bo_code = str(after_component.get("boCode") or after_component.get("modelField") or bo_code or "")
            after_label = str(after_component.get("label") or component_label or "")
            try:
                saved_component, _ = _find_form_component(
                    _form_components_from_config(saved_config),
                    component_uuid=after_uuid,
                    bo_code=after_bo_code,
                    component_label=after_label,
                )
            except ValueError:
                saved_component = after_component

            return {
                "ok": True,
                "form_id": form_id_clean,
                "matched_by": patch["match_by"],
                **identifiers,
                "resolved_component": _component_snapshot(saved_component),
                "updated_fields": list(diff.keys()),
                "diff": diff,
                "warnings": warnings or [],
                "message": f"组件「{after_label or after_uuid or after_bo_code}」已更新 {len(diff)} 个字段（实时生效）",
            }

        ok, raw = await with_client(env_id, op, _run)
        if not ok:
            return raw
        return raw


    @mcp.tool()
    async def update_apaas_form_component(
        env_id: int,
        apaas_app_id: str,
        form_id: str,
        component_label: str,
        updates: dict,
    ) -> dict:
        """微调表单中某个组件的属性（按 label 精确匹配，单组件 update）。

        底层：query_form_config → 找 label == component_label 的组件 → updates dict
        merge 进去 → save_form_config 全量回写。

        component_label 必须**精确匹配**组件当前的 label（区分大小写、空格敏感）；
        匹配不上会 NOT_FOUND，不模糊匹配。

        常用 updates 字段：
          - label: 改组件标题（"申请人" → "提单人"）
          - required: bool，是否必填
          - placeholder: str，占位提示
          - defaultValue: 默认值
          - readonly: bool
          - hidden: bool（隐藏字段，apaas 运行时不显示）
          - description / tooltip: 提示文案
          - chooseOptions: list，单选/多选/复选框选项
          - dictionaryChooseOptions: list，字典选项（{value, label, code}）
          - multicolor: bool，字典选项是否多色
          - maxLength / minValue / maxValue: 输入限制

        注意：
          - componentType（组件类型）一般不要改 — 改了往往导致数据迁移问题
          - modelField（绑定的模型字段 code）也别动 — 跟模型 field 强关联
          - 不需要 republish，apaas 平台实时生效
        """
        if not (apaas_app_id.strip() and form_id.strip() and component_label.strip()):
            return {
                "ok": False, "error_code": "INVALID_PARAMS",
                "message": "apaas_app_id+form_id+component_label 都必填",
            }
        if not isinstance(updates, dict) or not updates:
            return {
                "ok": False, "error_code": "INVALID_UPDATES",
                "message": "updates 必须是非空 dict",
            }

        # 软提示：updates 里如果有不常见字段，提醒 LLM
        unknown_fields = [k for k in updates.keys() if k not in _FORM_COMPONENT_COMMON_FIELDS]
        result = await _save_form_component_updates(
            env_id=env_id,
            apaas_app_id=apaas_app_id,
            form_id=form_id,
            component_label=component_label,
            updates=updates,
            op="改表单组件",
        )
        if unknown_fields:
            result["warning"] = (
                f"updates 里有 {len(unknown_fields)} 个非常见字段：{unknown_fields}；"
                f"已传给 apaas 但不保证生效，常见字段见 docstring"
            )
        return result


    @mcp.tool()
    async def set_apaas_form_component_default(
        env_id: int,
        apaas_app_id: str,
        form_id: str,
        default_value: Any = None,
        component_label: str = "",
        component_uuid: str = "",
        bo_code: str = "",
        clear: bool = False,
    ) -> dict:
        """设置表单组件默认值。下拉/单选类字段会校验默认值必须存在于当前选项里。"""
        if default_value is None and not clear:
            return {
                "ok": False,
                "error_code": "INVALID_DEFAULT_VALUE",
                "message": "请传 default_value；如果要清空默认值，传 clear=true",
            }
        updates = {
            "defaultValue": "" if clear else default_value,
            "staticDefaultValueI18nAssociated": False,
        }
        return await _save_form_component_updates(
            env_id=env_id,
            apaas_app_id=apaas_app_id,
            form_id=form_id,
            component_label=component_label,
            component_uuid=component_uuid,
            bo_code=bo_code,
            updates=updates,
            op="设组件默认值",
            validate_default_value=not clear,
        )


    @mcp.tool()
    async def set_apaas_form_component_behavior(
        env_id: int,
        apaas_app_id: str,
        form_id: str,
        component_label: str = "",
        component_uuid: str = "",
        bo_code: str = "",
        required: bool | None = None,
        hidden: bool | None = None,
        read_only: bool | None = None,
        only_create_edit: bool | None = None,
        unique_check: bool | None = None,
        save_with_hidden: bool | None = None,
        width: int | None = None,
        mobile_width: int | None = None,
        placeholder: str | None = None,
        title_description: str | None = None,
    ) -> dict:
        """调整组件行为：必填、隐藏、只读、宽度、占位提示、标题说明等。"""
        try:
            updates = _build_component_behavior_updates(
                required=required,
                hidden=hidden,
                read_only=read_only,
                only_create_edit=only_create_edit,
                unique_check=unique_check,
                save_with_hidden=save_with_hidden,
                width=width,
                mobile_width=mobile_width,
                placeholder=placeholder,
                title_description=title_description,
            )
        except ValueError as exc:
            return {"ok": False, "error_code": "INVALID_COMPONENT_BEHAVIOR", "message": str(exc)}
        if not updates:
            return {"ok": False, "error_code": "INVALID_UPDATES", "message": "至少传一个要调整的行为字段"}
        return await _save_form_component_updates(
            env_id=env_id,
            apaas_app_id=apaas_app_id,
            form_id=form_id,
            component_label=component_label,
            component_uuid=component_uuid,
            bo_code=bo_code,
            updates=updates,
            op="设组件行为",
        )


    @mcp.tool()
    async def set_apaas_form_component_options(
        env_id: int,
        apaas_app_id: str,
        form_id: str,
        options: list,
        component_label: str = "",
        component_uuid: str = "",
        bo_code: str = "",
        choose_type: str = "SINGLE",
        default_value: Any = None,
        multicolor: bool = True,
    ) -> dict:
        """设置选项类组件的选项列表，可同时设置默认值。"""
        try:
            normalized_options = _normalize_select_component_options(options)
        except ValueError as exc:
            return {"ok": False, "error_code": "INVALID_OPTIONS", "message": str(exc)}

        choose_type_clean = (choose_type or "SINGLE").strip().upper()
        if choose_type_clean not in {"SINGLE", "MULTI"}:
            return {"ok": False, "error_code": "INVALID_CHOOSE_TYPE", "message": "choose_type 只能是 SINGLE / MULTI"}

        temp_component = {
            "chooseOptions": normalized_options,
            "dictionaryChooseOptions": normalized_options,
        }
        try:
            if default_value is not None:
                _validate_component_default_value(temp_component, default_value)
        except ValueError as exc:
            return {"ok": False, "error_code": "INVALID_DEFAULT_VALUE", "message": str(exc)}

        updates = {
            "chooseType": choose_type_clean,
            "chooseOptions": normalized_options,
            "dictionaryChooseOptions": normalized_options,
            "multicolor": bool(multicolor),
            "dictionaryMulticolorStatus": "ENABLE" if multicolor else "DISABLE",
        }
        if default_value is not None:
            updates["defaultValue"] = default_value
            updates["staticDefaultValueI18nAssociated"] = False

        return await _save_form_component_updates(
            env_id=env_id,
            apaas_app_id=apaas_app_id,
            form_id=form_id,
            component_label=component_label,
            component_uuid=component_uuid,
            bo_code=bo_code,
            updates=updates,
            op="设组件选项",
        )


    @mcp.tool()
    async def set_apaas_form_component_document_number_rules(
        env_id: int,
        apaas_app_id: str,
        form_id: str,
        rules: list,
        component_label: str = "",
        component_uuid: str = "",
        bo_code: str = "",
    ) -> dict:
        """设置单据号组件的 documentNumRules。适用于 FORM_DOCUMENT_NUMBER。"""
        if not isinstance(rules, list) or not rules or not all(isinstance(rule, dict) for rule in rules):
            return {
                "ok": False,
                "error_code": "INVALID_DOCUMENT_NUMBER_RULES",
                "message": "rules 必须是非空 list[dict]",
            }
        return await _save_form_component_updates(
            env_id=env_id,
            apaas_app_id=apaas_app_id,
            form_id=form_id,
            component_label=component_label,
            component_uuid=component_uuid,
            bo_code=bo_code,
            updates={"documentNumRules": copy.deepcopy(rules)},
            op="设单据号规则",
            expected_component_types={"FORM_DOCUMENT_NUMBER"},
        )


    @mcp.tool()
    async def set_apaas_form_component_validation(
        env_id: int,
        apaas_app_id: str,
        form_id: str,
        component_label: str = "",
        component_uuid: str = "",
        bo_code: str = "",
        unique_check: bool | None = None,
        validator_status: bool | None = None,
        validator_list: list | None = None,
    ) -> dict:
        """设置组件校验：唯一性、validatorStatus、validatorList。"""
        updates: dict[str, Any] = {}
        if unique_check is not None:
            updates["uniqueCheck"] = bool(unique_check)
        if validator_status is not None:
            updates["validatorStatus"] = bool(validator_status)
        if validator_list is not None:
            if not isinstance(validator_list, list):
                return {"ok": False, "error_code": "INVALID_VALIDATOR_LIST", "message": "validator_list 必须是 list"}
            updates["validatorList"] = copy.deepcopy(validator_list)
        if not updates:
            return {"ok": False, "error_code": "INVALID_UPDATES", "message": "至少传 unique_check / validator_status / validator_list 之一"}
        return await _save_form_component_updates(
            env_id=env_id,
            apaas_app_id=apaas_app_id,
            form_id=form_id,
            component_label=component_label,
            component_uuid=component_uuid,
            bo_code=bo_code,
            updates=updates,
            op="设组件校验",
        )


    @mcp.tool()
    async def set_apaas_form_component_style(
        env_id: int,
        apaas_app_id: str,
        form_id: str,
        component_label: str = "",
        component_uuid: str = "",
        bo_code: str = "",
        style_type: str = "CSS",
        css: str = "",
        custom_component_config: dict | None = None,
        style_payload: dict | None = None,
    ) -> dict:
        """设置组件个性化样式。

        当前已验证普通组件存在 customComponentConfig，但平台原生「个性化样式」弹窗
        的最终保存字段仍需后续抓包确认。因此本工具保守写 customComponentConfig，
        若传 style_payload 则只按调用方显式字段写入并返回 schema warning。
        """
        updates: dict[str, Any] = {}
        warnings = [
            "STYLE_SCHEMA_UNVERIFIED: 已按 customComponentConfig/显式 style_payload 写入；"
            "平台原生个性化样式的完整字段名仍需抓包确认",
        ]

        style_config: dict[str, Any] = {}
        if custom_component_config is not None:
            if not isinstance(custom_component_config, dict):
                return {"ok": False, "error_code": "INVALID_STYLE_CONFIG", "message": "custom_component_config 必须是 dict"}
            style_config.update(copy.deepcopy(custom_component_config))
        if css:
            style_config.update({
                "styleType": (style_type or "CSS").strip().upper(),
                "styleContent": css,
            })
        if style_config:
            updates["__merge_customComponentConfig__"] = style_config

        if style_payload is not None:
            if not isinstance(style_payload, dict):
                return {"ok": False, "error_code": "INVALID_STYLE_PAYLOAD", "message": "style_payload 必须是 dict"}
            blocked = {
                "uuid", "id", "label", "componentType", "modelField", "boCode",
                "tableModelCode", "tableColumn",
            } & set(style_payload.keys())
            if blocked:
                return {
                    "ok": False,
                    "error_code": "INVALID_STYLE_PAYLOAD",
                    "message": f"style_payload 不能改组件身份/绑定字段：{sorted(blocked)}",
                }
            updates.update(copy.deepcopy(style_payload))

        if not updates:
            return {
                "ok": False,
                "error_code": "INVALID_UPDATES",
                "message": "至少传 css / custom_component_config / style_payload 之一",
            }

        return await _save_form_component_updates(
            env_id=env_id,
            apaas_app_id=apaas_app_id,
            form_id=form_id,
            component_label=component_label,
            component_uuid=component_uuid,
            bo_code=bo_code,
            updates=updates,
            op="设组件样式",
            warnings=warnings,
        )

    return {
        "update_apaas_form_component": update_apaas_form_component,
        "set_apaas_form_component_default": set_apaas_form_component_default,
        "set_apaas_form_component_behavior": set_apaas_form_component_behavior,
        "set_apaas_form_component_options": set_apaas_form_component_options,
        "set_apaas_form_component_document_number_rules": set_apaas_form_component_document_number_rules,
        "set_apaas_form_component_validation": set_apaas_form_component_validation,
        "set_apaas_form_component_style": set_apaas_form_component_style,
    }
