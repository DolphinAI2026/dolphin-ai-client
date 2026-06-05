"""回归: 解析后「下拉↔字典」调和兜底 —— 治大文档分块解析丢失下拉字典引用。

根因(2026-06-05 app5 易景QMS 实测): 54K 文档走 _parse_chunked, 字典在某分块定义、
下拉字段在另一分块生成, 跨块无共享字典注册表 → 下拉组件既无 dict 引用、也无内联选项
(选项全在孤儿字典里), 88 个下拉 0 个绑上 → apaas 默认 选项1/2/3。

reconcile_dropdown_dicts: ①确定性 label==字典名 直连; ②剩下的交给 relink_fn(LLM 语义匹配,
可注入/测试用 stub); ③仍连不上的列进 unlinked 让上层标记。详见
docs/research-0to1-dropdown-dict-rootcause-2026-06-05.md。
"""
import app.ai_doc_parser as p


def _app5_like():
    """模拟分块解析产物: 下拉组件无 dict 引用, 字典已定义(孤儿)。"""
    return {
        "dicts": [
            {"code": "qms_standard_type_", "name": "标准类型",
             "options": [{"label": "国标", "value": "gb"}, {"label": "行标", "value": "hb"}]},
            {"code": "qms_doc_status_", "name": "单据状态",
             "options": [{"label": "草稿", "value": "draft"}]},
        ],
        "models": [
            {"code": "qms_inn_standard_file_", "name": "内部标准", "fields": [
                {"code": "standard_type", "name": "标准类型", "type": "单行输入"},
                {"code": "standard_category", "name": "标准分类", "type": "单行输入"},
            ]},
        ],
        "forms": [
            {"code": "f_std", "name": "标准档案", "components": [
                {"label": "标准类型", "code": "standard_type",
                 "componentType": "FORM_SELECT_INPUT_SINGLE",
                 "modelField": "qms_inn_standard_file_.standard_type"},
                {"label": "标准分类", "code": "standard_category",
                 "componentType": "FORM_SELECT_INPUT_SINGLE",
                 "modelField": "qms_inn_standard_file_.standard_category"},
            ]},
        ],
    }


def test_find_unlinked_dropdowns_detects_orphans():
    data = _app5_like()
    unlinked = p.find_unlinked_dropdown_components(data)
    labels = {u["label"] for u in unlinked}
    assert labels == {"标准类型", "标准分类"}, f"应检出 2 个无字典下拉, got {labels}"


def test_reconcile_links_by_exact_name_match():
    """确定性: 组件 label 精确等于某字典名 → 直接连上(不需 LLM)。"""
    data = _app5_like()
    res = p.reconcile_dropdown_dicts(data)  # relink_fn=None → 只做确定性
    comps = {c["label"]: c for c in data["forms"][0]["components"]}
    # 「标准类型」label==字典名 → 连上 qms_standard_type_
    assert comps["标准类型"].get("dict") == "qms_standard_type_"
    assert comps["标准类型"].get("dictCode") == "qms_standard_type_"
    # 「标准分类」无字典名匹配 → 仍未连, 列进 unlinked
    assert comps["标准分类"].get("dict") in (None, "")
    assert any(u["label"] == "标准分类" for u in res["unlinked"])
    assert res["linked_by_name"] == 1


def test_reconcile_uses_relink_fn_for_residual():
    """剩下连不上的交给 relink_fn(LLM) 语义匹配; 这里用 stub 返回映射。"""
    data = _app5_like()

    def stub_relink(unlinked, dicts):
        # 模拟 LLM: 把「标准分类」语义连到「标准类型」字典
        return {u["key"]: "qms_standard_type_" for u in unlinked if u["label"] == "标准分类"}

    res = p.reconcile_dropdown_dicts(data, relink_fn=stub_relink)
    comps = {c["label"]: c for c in data["forms"][0]["components"]}
    assert comps["标准分类"].get("dict") == "qms_standard_type_"  # relink 连上
    assert comps["标准类型"].get("dict") == "qms_standard_type_"  # name 连上
    assert res["linked_by_name"] == 1 and res["linked_by_relink"] == 1
    assert res["unlinked"] == []


def test_reconcile_noop_when_no_dicts_defined():
    """没有任何字典定义时不报错, 全部列 unlinked(交给上层标记/不阻断)。"""
    data = _app5_like()
    data["dicts"] = []
    res = p.reconcile_dropdown_dicts(data)
    assert res["linked_by_name"] == 0
    assert len(res["unlinked"]) == 2


def test_downgrade_unbindable_dropdowns_to_text():
    """决策 A: 连不上字典的下拉 → 降级成单行输入(消除空 选项1/2/3),已连上的保持下拉。"""
    data = _app5_like()
    p.reconcile_dropdown_dicts(data)  # 标准类型 name-match 连上; 标准分类 连不上
    downgraded = p.downgrade_unbindable_dropdowns(data)
    comps = {c["label"]: c for c in data["forms"][0]["components"]}
    # 连上的保持下拉
    assert comps["标准类型"]["componentType"] == "FORM_SELECT_INPUT_SINGLE"
    assert comps["标准类型"]["dict"] == "qms_standard_type_"
    # 连不上的降级成单行输入 + 清 dict
    assert comps["标准分类"]["componentType"] == "FORM_TEXT_INPUT"
    assert comps["标准分类"].get("dict") in (None, "")
    assert [d["label"] for d in downgraded] == ["标准分类"]
    # 降级后再找无字典下拉应为空(没有空下拉残留)
    assert p.find_unlinked_dropdown_components(data) == []


def test_downgrade_when_no_dicts_at_all():
    """压根没生成字典时, 所有下拉都降级成单行输入(不留空下拉)。"""
    data = _app5_like()
    data["dicts"] = []
    downgraded = p.downgrade_unbindable_dropdowns(data)
    types = {c["label"]: c["componentType"] for c in data["forms"][0]["components"]}
    assert types == {"标准类型": "FORM_TEXT_INPUT", "标准分类": "FORM_TEXT_INPUT"}
    assert len(downgraded) == 2


def test_reconcile_skips_already_bound_dropdown():
    """已带可解析 dict 的下拉不动它。"""
    data = _app5_like()
    data["forms"][0]["components"][0]["dict"] = "qms_doc_status_"  # 标准类型 已绑(故意绑到别的)
    res = p.reconcile_dropdown_dicts(data)
    comps = {c["label"]: c for c in data["forms"][0]["components"]}
    assert comps["标准类型"]["dict"] == "qms_doc_status_"  # 没被覆盖
    assert res["linked_by_name"] == 0  # 已绑的不计入
