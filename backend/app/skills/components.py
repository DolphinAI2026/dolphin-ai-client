"""aPaaS 表单组件构建器

支持所有 16 种组件类型，每种类型注册为独立的构建函数。
"""
from __future__ import annotations
import random
import re
import string
from typing import Callable, Dict, List, Optional

# 组件类型映射：预览类型 → 表单组件类型
COMPONENT_TYPE_MAP = {
    '单据号': 'FORM_DOCUMENT_NUMBER',
    '单行输入': 'FORM_TEXT_INPUT',
    '多行输入': 'FORM_TEXTAREA_INPUT',
    '手机号码': 'FORM_PHONE_INPUT',
    '电子邮箱': 'FORM_EMAIL_INPUT',
    '下拉单选': 'FORM_SELECT_INPUT_SINGLE',
    '下拉多选': 'FORM_SELECT_INPUT',
    '数据单选': 'FORM_DATA_SELECTOR_SINGLE',
    '日期时间': 'FORM_DATEPICK_INPUT',
    '金额': 'FORM_MONEY_INPUT',
    '数字': 'FORM_NUMBER_INPUT',
    '附件上传': 'FORM_FILE_UPLOAD',
    '开关': 'FORM_SWITCH_SELECT',
    '布尔': 'FORM_SWITCH_SELECT',
    '人员选择': 'FORM_PEOPLE_SELECT',
    '部门选择': 'FORM_DEPARTMENT_SELECT',
    '地理位置': 'FORM_WIDGET_LOCATION',
    '子表': 'FORM_WIDGET_SON_TABLE',
    # 新增组件类型（正确的平台组件编码）
    '单选框': 'FORM_RADIO_INPUT',
    '复选框': 'FORM_CHECKBOX_INPUT',
    '多选框': 'FORM_CHECKBOX_INPUT',
    '富文本': 'FORM_RICH_TEXT',
    '超链接': 'FORM_HYPERLINK_INPUT',
    '身份证号': 'FORM_IDCARD_INPUT',
    '证件号': 'FORM_IDCARD_INPUT',
    '地区地址': 'FORM_WIDGET_AREA',
    '数据选择': 'FORM_DATA_SELECTOR',
    '数据多选': 'FORM_DATA_SELECTOR',
    '关联表单': 'FORM_ASSOCIATION',
}

# 组件注册表：componentType → builder function
COMPONENT_REGISTRY: Dict[str, Callable] = {}


def _rand(n: int = 4) -> str:
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))


def _safe_code(code: str) -> str:
    from app.skills.platform import _RESERVED_WORDS
    c = re.sub(r'[^a-zA-Z0-9_]', '_', code)
    if c.lower() in _RESERVED_WORDS and not c.startswith("f_"):
        c = f"f_{c}"
    return c


# ── 基础组件构建器（8种简单组件共用） ──

def _build_simple(
    field: Dict,
    model_code: str,
    field_code: str,
    **_kwargs,
) -> Dict:
    """构建简单组件（无额外配置）。

    适用于: 单行输入、多行输入、数字、金额、手机号码、电子邮箱、
            日期时间、单据号、附件上传、开关、人员选择、地理位置
    """
    field_type = field.get("type", "单行输入")
    component_type = COMPONENT_TYPE_MAP.get(field_type, "FORM_TEXT_INPUT")
    return {
        "componentType": component_type,
        "label": field["name"],
        "modelField": f"{model_code}.{field_code}",
    }


# 注册所有简单组件（无需额外配置）
for _type in (
    'FORM_TEXT_INPUT', 'FORM_TEXTAREA_INPUT', 'FORM_NUMBER_INPUT',
    'FORM_MONEY_INPUT', 'FORM_PHONE_INPUT', 'FORM_EMAIL_INPUT',
    'FORM_DATEPICK_INPUT', 'FORM_DOCUMENT_NUMBER', 'FORM_FILE_UPLOAD',
    'FORM_SWITCH_SELECT', 'FORM_PEOPLE_SELECT', 'FORM_DEPARTMENT_SELECT',
    'FORM_WIDGET_LOCATION', 'FORM_WIDGET_AREA', 'FORM_HYPERLINK_INPUT',
    'FORM_RICH_TEXT', 'FORM_IDCARD_INPUT',
):
    COMPONENT_REGISTRY[_type] = _build_simple


# ── 下拉单选（字典绑定） ──

def _build_select_single(
    field: Dict,
    model_code: str,
    field_code: str,
    dicts: Optional[List[Dict]] = None,
    dict_code_map: Optional[Dict] = None,
    **_kwargs,
) -> Dict:
    """构建下拉单选组件，绑定数据字典。"""
    component: Dict = {
        "componentType": "FORM_SELECT_INPUT_SINGLE",
        "label": field["name"],
        "modelField": f"{model_code}.{field_code}",
    }

    if field.get("dict"):
        raw_dict_code = field["dict"]
        actual_dict_code = (dict_code_map or {}).get(raw_dict_code, raw_dict_code)
        dict_def = next((d for d in (dicts or []) if d.get("code") == raw_dict_code), None)
        options_list = _extract_dict_options(dict_def, raw_dict_code)
        component["dictionarySelectConfig"] = {
            "dictionaryCode": actual_dict_code,
            "dictionarySelectOptions": options_list,
        }

    return component


COMPONENT_REGISTRY['FORM_SELECT_INPUT_SINGLE'] = _build_select_single


# ── 下拉多选（字典绑定） ──

def _build_select_multi(
    field: Dict,
    model_code: str,
    field_code: str,
    dicts: Optional[List[Dict]] = None,
    dict_code_map: Optional[Dict] = None,
    **_kwargs,
) -> Dict:
    """构建下拉多选组件，绑定数据字典。"""
    component: Dict = {
        "componentType": "FORM_SELECT_INPUT",
        "label": field["name"],
        "modelField": f"{model_code}.{field_code}",
    }

    if field.get("dict"):
        raw_dict_code = field["dict"]
        actual_dict_code = (dict_code_map or {}).get(raw_dict_code, raw_dict_code)
        dict_def = next((d for d in (dicts or []) if d.get("code") == raw_dict_code), None)
        options_list = _extract_dict_options(dict_def, raw_dict_code)
        component["dictionarySelectConfig"] = {
            "dictionaryCode": actual_dict_code,
            "dictionarySelectOptions": options_list,
        }

    return component


COMPONENT_REGISTRY['FORM_SELECT_INPUT'] = _build_select_multi


# ── 数据单选（关联模型） ──

def _build_data_selector(
    field: Dict,
    model_code: str,
    field_code: str,
    code_map: Optional[Dict] = None,
    **_kwargs,
) -> Dict:
    """构建数据选择器组件，关联其他模型。"""
    component: Dict = {
        "componentType": "FORM_DATA_SELECTOR_SINGLE",
        "label": field["name"],
        "modelField": f"{model_code}.{field_code}",
    }

    ref = field.get("ref")
    if ref:
        if isinstance(ref, dict):
            ref_model = ref.get("model", "")
            ref_field = ref.get("field", "")
        else:
            ref_model = str(ref)
            ref_field = ""
        resolved_model = (code_map or {}).get(ref_model, ref_model)
        component["dataSelectorConfig"] = {
            "type": "LOV_CHOOSE",
            "otherModelCode": resolved_model,
            "otherFieldCode": ref_field,
        }

    return component


COMPONENT_REGISTRY['FORM_DATA_SELECTOR_SINGLE'] = _build_data_selector


# ── 单选框（字典绑定） ──

def _build_radio(
    field: Dict,
    model_code: str,
    field_code: str,
    dicts: Optional[List[Dict]] = None,
    dict_code_map: Optional[Dict] = None,
    **_kwargs,
) -> Dict:
    """构建单选框组件，绑定数据字典。"""
    component: Dict = {
        "componentType": "FORM_RADIO_INPUT",
        "label": field["name"],
        "modelField": f"{model_code}.{field_code}",
    }
    if field.get("dict"):
        raw_dict_code = field["dict"]
        actual_dict_code = (dict_code_map or {}).get(raw_dict_code, raw_dict_code)
        dict_def = next((d for d in (dicts or []) if d.get("code") == raw_dict_code), None)
        options_list = _extract_dict_options(dict_def, raw_dict_code)
        component["dictionarySelectConfig"] = {
            "dictionaryCode": actual_dict_code,
            "dictionarySelectOptions": options_list,
        }
    return component


COMPONENT_REGISTRY['FORM_RADIO_INPUT'] = _build_radio


# ── 复选框（字典绑定） ──

def _build_checkbox(
    field: Dict,
    model_code: str,
    field_code: str,
    dicts: Optional[List[Dict]] = None,
    dict_code_map: Optional[Dict] = None,
    **_kwargs,
) -> Dict:
    """构建复选框组件，绑定数据字典。"""
    component: Dict = {
        "componentType": "FORM_CHECKBOX_INPUT",
        "label": field["name"],
        "modelField": f"{model_code}.{field_code}",
    }
    if field.get("dict"):
        raw_dict_code = field["dict"]
        actual_dict_code = (dict_code_map or {}).get(raw_dict_code, raw_dict_code)
        dict_def = next((d for d in (dicts or []) if d.get("code") == raw_dict_code), None)
        options_list = _extract_dict_options(dict_def, raw_dict_code)
        component["dictionarySelectConfig"] = {
            "dictionaryCode": actual_dict_code,
            "dictionarySelectOptions": options_list,
        }
    return component


COMPONENT_REGISTRY['FORM_CHECKBOX_INPUT'] = _build_checkbox


# ── 数据选择（多选，关联模型） ──

def _build_data_selector_multi(
    field: Dict,
    model_code: str,
    field_code: str,
    code_map: Optional[Dict] = None,
    **_kwargs,
) -> Dict:
    """构建数据选择器组件（多选），关联其他模型。"""
    component: Dict = {
        "componentType": "FORM_DATA_SELECTOR",
        "label": field["name"],
        "modelField": f"{model_code}.{field_code}",
    }
    ref = field.get("ref")
    if ref:
        if isinstance(ref, dict):
            ref_model = ref.get("model", "")
            ref_field = ref.get("field", "")
        else:
            ref_model = str(ref)
            ref_field = ""
        resolved_model = (code_map or {}).get(ref_model, ref_model)
        component["dataSelectorConfig"] = {
            "type": "LOV_CHOOSE",
            "otherModelCode": resolved_model,
            "otherFieldCode": ref_field,
        }
    return component


COMPONENT_REGISTRY['FORM_DATA_SELECTOR'] = _build_data_selector_multi


# ── 关联表单 ──

def _build_association(
    field: Dict,
    model_code: str,
    field_code: str,
    code_map: Optional[Dict] = None,
    **_kwargs,
) -> Dict:
    """构建关联表单组件。"""
    component: Dict = {
        "componentType": "FORM_ASSOCIATION",
        "label": field["name"],
    }
    ref = field.get("ref")
    if ref and isinstance(ref, dict):
        origin_field = ref.get("field", field_code)
        target_model = ref.get("model", "")
        target_field = ref.get("target_field", "")
        resolved_model = (code_map or {}).get(target_model, target_model)
        component["formAssociationConfig"] = {
            "originFieldCode": origin_field,
            "targetModelCode": resolved_model,
            "targetFieldCode": target_field,
        }
    return component


COMPONENT_REGISTRY['FORM_ASSOCIATION'] = _build_association


# ── 子表 ──

def _build_son_table(
    field: Dict,
    model_code: str,
    field_code: str,
    code_map: Optional[Dict] = None,
    dicts: Optional[List[Dict]] = None,
    dict_code_map: Optional[Dict] = None,
    sent_by_code: Optional[Dict] = None,
    **_kwargs,
) -> Dict:
    """构建子表组件。"""
    base_code = model_code.rsplit('_', 1)[0] if '_' in model_code else model_code
    sub_code = field.get("sub_code") or f"{base_code}_sub"
    sub_model_code = (code_map or {}).get(sub_code, sub_code)

    # 获取子表 sent_fields
    sub_sm = (sent_by_code or {}).get(sub_model_code, {})
    sub_sent_fields = sub_sm.get("fields", [])

    sub_cols = []
    for si, sf in enumerate(field.get("sub_fields", [])):
        if si < len(sub_sent_fields):
            sf_code = sub_sent_fields[si]["fieldCode"]
        else:
            sf_code = _safe_code(sf.get("code") or f"sf{si}_{_rand()}")
        sub_comp = build_component(
            sf, sub_model_code, sf_code,
            dicts=dicts, code_map=code_map, dict_code_map=dict_code_map,
        )
        sub_cols.append(sub_comp)

    return {
        "componentType": "FORM_WIDGET_SON_TABLE",
        "label": field["name"],
        "tableColumn": sub_cols,
    }


COMPONENT_REGISTRY['FORM_WIDGET_SON_TABLE'] = _build_son_table


# ── 辅助函数 ──

def _extract_dict_options(dict_def: Optional[Dict], raw_dict_code: str) -> List[Dict]:
    """从字典定义中提取选项列表。"""
    options_list = []
    if dict_def:
        for i, opt in enumerate(dict_def.get("options", [])):
            if isinstance(opt, str):
                options_list.append({"id": f"{raw_dict_code}_{i+1}", "label": opt})
            elif isinstance(opt, dict):
                options_list.append({
                    "id": opt.get("code", opt.get("id", f"{raw_dict_code}_{i+1}")),
                    "label": opt.get("name", opt.get("label", str(opt))),
                })
    return options_list


# ── 通用入口 ──

def build_component(
    field: Dict,
    model_code: str,
    field_code: str,
    dicts: Optional[List[Dict]] = None,
    code_map: Optional[Dict] = None,
    dict_code_map: Optional[Dict] = None,
    sent_by_code: Optional[Dict] = None,
) -> Dict:
    """通用组件构建入口。

    根据 field["type"] 自动选择对应的构建函数。

    Args:
        field: 预览格式字段定义 {"name", "type", "dict", "ref", "sub_fields", ...}
        model_code: 带后缀的模型编码
        field_code: 字段编码
        dicts: 字典定义列表（下拉组件需要）
        code_map: 模型编码映射（数据选择器和子表需要）
        dict_code_map: 字典编码映射（下拉组件需要）
        sent_by_code: 已发送模型的 fields 索引（子表需要）

    Returns:
        表单组件配置 dict
    """
    field_type = field.get("type", "单行输入")
    component_type = COMPONENT_TYPE_MAP.get(field_type, "FORM_TEXT_INPUT")
    builder = COMPONENT_REGISTRY.get(component_type, _build_simple)

    return builder(
        field=field,
        model_code=model_code,
        field_code=field_code,
        dicts=dicts,
        code_map=code_map,
        dict_code_map=dict_code_map,
        sent_by_code=sent_by_code,
    )


# ── 表单配置构建 ──

def build_form_config(
    models: List[Dict],
    dicts: List[Dict],
    model_results: Optional[list] = None,
    model_payload: Optional[Dict] = None,
    code_map: Optional[Dict] = None,
    dict_code_map: Optional[Dict] = None,
) -> List[Dict]:
    """构建完整的 formConfig 请求体。

    这是 create_form Skill 的核心逻辑，将预览格式的模型定义
    转换为 /common/resource/formConfig API 的请求体。

    Args:
        models: 预览格式模型列表
        dicts: 预览格式字典列表
        model_results: create_models 返回的结果
        model_payload: create_models 使用的 payload
        code_map: 模型编码映射
        dict_code_map: 字典编码映射

    Returns:
        formConfig 请求体列表
    """
    sent_models = (model_payload or {}).get("dataModels", [])
    _code_map = code_map or {}

    # 构建索引
    sent_by_code = {sm.get("modelCode", ""): sm for sm in sent_models}
    result_by_code = {}
    if model_results:
        for mr in model_results:
            if isinstance(mr, dict):
                result_by_code[mr.get("modelCode", "")] = mr

    configs = []

    for m in models:
        base_code = m.get("code") or "model"
        model_code = _code_map.get(base_code, base_code)

        sm = sent_by_code.get(model_code, {})
        mr = result_by_code.get(model_code, {})
        actual_code = mr.get("modelCode") or sm.get("modelCode") or model_code

        form_code = f"form_{_rand(6)}"
        sent_fields = sm.get("fields", [])

        form_components = []
        query_conditions = []
        query_list = []
        all_model_codes = [actual_code]
        listable_count = 0

        for fi, f in enumerate(m.get("fields", [])):
            field_type = f.get("type", "单行输入")

            # 子表
            if field_type == '子表' and f.get("sub_fields"):
                sub_code = f.get("sub_code") or f"{base_code}_sub"
                sub_model_code = _code_map.get(sub_code, sub_code)
                all_model_codes.append(sub_model_code)

                component = build_component(
                    f, model_code, "",
                    dicts=dicts, code_map=_code_map,
                    dict_code_map=dict_code_map, sent_by_code=sent_by_code,
                )
                form_components.append(component)
                continue

            # 普通字段
            if fi < len(sent_fields):
                field_code = sent_fields[fi]["fieldCode"]
            else:
                field_code = f.get("code") or f"field_{fi}_{_rand()}"

            component = build_component(
                f, actual_code, field_code,
                dicts=dicts, code_map=_code_map, dict_code_map=dict_code_map,
            )
            form_components.append(component)

            # 列表页
            if listable_count < 6 and field_type not in ('附件上传', '多行输入', '子表'):
                model_field = f"{actual_code}.{field_code}"
                if listable_count < 4:
                    query_conditions.append(model_field)
                query_list.append(model_field)
                listable_count += 1

        configs.append({
            "formName": m["name"],
            "formCode": form_code,
            "allModelCodes": all_model_codes,
            "formComponents": form_components,
            "listPageView": {
                "queryConditions": query_conditions,
                "queryList": query_list,
            },
        })

    return configs
