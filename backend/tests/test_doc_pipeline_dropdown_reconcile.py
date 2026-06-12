"""集成: doc_pipeline 在 validate 后做的「下拉↔字典」确定性调和 + 降级。

验证活管线接入点(doc_pipeline.parse_document 中 validate_full_config 之后那段):
  ① label==字典名 的下拉确定性连回字典(不调 LLM);
  ② 连不上的降级成单行输入(消除空 选项1/2/3);
  ③ 产生的修复消息带「已映射」/「已降级」前缀 → 经 _split_parse_messages 分流进
     auto_fixes 通道(透前端而非阻塞错误)。

这里直接复刻管线那段函数组合(纯确定性, 无 LLM/网络依赖), 把生成的消息喂给
_split_parse_messages, 断言全部落 auto_fixes。
"""
from app.config_postprocess import (
    reconcile_dropdown_dicts,
    downgrade_unbindable_dropdowns,
    find_unlinked_dropdown_components,
)
from app.doc_pipeline import _split_parse_messages


def _config_with_unbound_dropdowns():
    """一个含未绑字典下拉的 config: 一个 label==字典名(可连), 一个无匹配(降级)。"""
    return {
        "dicts": [
            {"code": "order_status_", "name": "订单状态",
             "options": [{"name": "草稿", "code": "draft"}, {"name": "已提交", "code": "submitted"}]},
        ],
        "models": [
            {"code": "order_", "name": "订单", "fields": [
                {"code": "status", "name": "订单状态", "type": "单行输入"},
                {"code": "priority", "name": "优先级", "type": "单行输入"},
            ]},
        ],
        "forms": [
            {"code": "f_order", "name": "订单表单", "components": [
                {"label": "订单状态", "code": "status",
                 "componentType": "FORM_SELECT_INPUT_SINGLE",
                 "modelField": "order_.status"},
                {"label": "优先级", "code": "priority",
                 "componentType": "FORM_SELECT_INPUT_SINGLE",
                 "modelField": "order_.priority"},
            ]},
        ],
    }


def _run_pipeline_reconcile(config):
    """复刻 doc_pipeline.parse_document 中 validate 后那段(确定性调和 + 降级 + 消息)。"""
    errors = []
    recon = reconcile_dropdown_dicts(config)  # relink_fn=None → 纯确定性
    if recon.get("linked_by_name"):
        errors.append(f"{recon['linked_by_name']} 个下拉组件按字典名匹配已映射回数据字典")
    for d in downgrade_unbindable_dropdowns(config):
        label = d.get("label") or d.get("model_field") or "(未命名)"
        errors.append(f"下拉组件 '{label}' 无字典可绑，已降级为单行输入")
    return errors


def test_label_match_links_and_unmatched_downgrades():
    config = _config_with_unbound_dropdowns()
    _run_pipeline_reconcile(config)

    comps = {c["label"]: c for c in config["forms"][0]["components"]}
    # label==字典名「订单状态」→ 连上 order_status_, 保持下拉
    assert comps["订单状态"]["componentType"] == "FORM_SELECT_INPUT_SINGLE"
    assert comps["订单状态"].get("dict") == "order_status_"
    # 模型字段也同步绑上 + 类型修正为下拉
    status_field = config["models"][0]["fields"][0]
    assert status_field.get("dict") == "order_status_"
    assert status_field.get("type") == "下拉单选"

    # 无字典名匹配的「优先级」→ 降级成单行输入 + 清 dict
    assert comps["优先级"]["componentType"] == "FORM_TEXT_INPUT"
    assert comps["优先级"].get("dict") in (None, "")
    priority_field = config["models"][0]["fields"][1]
    assert priority_field.get("type") == "单行输入"

    # 调和+降级后不应再有未绑下拉残留
    assert find_unlinked_dropdown_components(config) == []


def test_reconcile_messages_route_into_auto_fixes():
    config = _config_with_unbound_dropdowns()
    errors = _run_pipeline_reconcile(config)

    # 两条消息: 1 条「已映射」+ 1 条「已降级」
    assert any("已映射" in m for m in errors)
    assert any("已降级" in m for m in errors)

    # 经 _split_parse_messages: 带 _AUTO_FIX_MARKERS 的全部进 auto_fixes, 不留阻塞错误
    blocking, auto_fixes = _split_parse_messages(errors)
    assert blocking == []
    assert len(auto_fixes) == len(errors)
    assert any("已映射回数据字典" in m for m in auto_fixes)
    assert any("已降级为单行输入" in m for m in auto_fixes)
