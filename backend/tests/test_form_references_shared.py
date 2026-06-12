"""共享表单引用解析 (operations.form_references) 单测。

收敛前 generator_v2 与 step_executor 两份实现双向漂移:
  - _resolve_component_reference: gen 侧多 dataSelectorConfig 分支
  - _resolve_target_form_result: step 侧多 code/formName/form_name/name 候选键
收敛取并集, 这里锁定并集后两路径都应具备的行为。
"""
from app.operations.form_references import (
    _resolve_component_reference,
    _resolve_target_form_result,
)


def test_component_reference_resolves_data_selector_config():
    """gen 侧并入的 dataSelectorConfig 分支: 数据选择引用要能解析出目标模型/字段。"""
    comp_def = {
        "dataSelectorConfig": {"otherModelCode": "customer", "otherFieldCode": "name"},
    }
    form_map = {"customer": {"modelCode": "customer_platform"}}

    model_code, field, origin = _resolve_component_reference(comp_def, form_map)

    assert model_code == "customer_platform"  # 经 form_map 解析成平台 modelCode
    assert field == "name"
    assert origin == ""


def test_component_reference_association_config_priority():
    """formAssociationConfig 优先于 dataSelectorConfig。"""
    comp_def = {
        "formAssociationConfig": {
            "targetModelCode": "order", "targetFieldCode": "no", "originFieldCode": "order_ref",
        },
        "dataSelectorConfig": {"otherModelCode": "customer", "otherFieldCode": "name"},
    }
    model_code, field, origin = _resolve_component_reference(comp_def, {})

    assert (model_code, field, origin) == ("order", "no", "order_ref")


def test_target_form_result_matches_via_step_extra_candidate_keys():
    """step 侧并入的候选键(formName/name 等): 仅靠表单名也能定位到目标 form_result。"""
    comp_def = {"formName": "客户表"}
    form_map = {"客户表": {"formName": "客户表", "modelCode": "customer"}}
    form_results = [
        {"formId": "f1", "formName": "客户表", "modelCode": "customer"},
        {"formId": "f2", "formName": "订单表", "modelCode": "order"},
    ]

    result = _resolve_target_form_result(comp_def, form_map, form_results, "customer")

    assert result["formId"] == "f1"


def test_target_form_result_falls_back_to_target_model_code():
    """所有候选键都不中时, 按 target_model_code 在 form_results 里兜底匹配。"""
    comp_def = {}
    form_results = [{"formId": "f9", "modelCode": "inventory"}]

    result = _resolve_target_form_result(comp_def, {}, form_results, "inventory")

    assert result["formId"] == "f9"


def test_target_form_result_returns_none_when_unresolvable():
    assert _resolve_target_form_result({}, {}, [{"formId": "f", "modelCode": "x"}], "y") is None
