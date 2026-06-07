"""回归: 下拉组件绑字典时, 必须优先用组件自带的权威 dict 引用(comp.dict/dictCode),
而不是只靠"字典名 == 组件 label"的脆弱兜底。

根因(2026-06-05 app10 电池护照系统实测坐实): 字段「化学体系」(chemistry_code) 在生成的
表单组件里明明带 dictCode='dict_chemistry', 但 _bind_dict_on_component 只按 label 在
label_dict 里查 —— 而平台字典名是「电池化学体系」≠ 组件 label「化学体系」, 名字没对上 →
下拉 source=None、绑不上。同表单 电池类型/生命周期阶段/护照状态 因字典名恰好 == label 才侥幸绑上。
"""
import app.generator_v2 as g2


def test_bind_uses_component_dictcode_when_dict_name_differs_from_label():
    """组件自带 dictCode 时, 即使字典名与 label 不同也要绑上(本 bug 的核心)。"""
    comp = {
        "componentType": "FORM_SELECT_INPUT_SINGLE",
        "label": "化学体系",
        "dict": "dict_chemistry",
        "dictCode": "dict_chemistry",
    }
    # label_dict 只含"字典名 -> code"的兜底映射, 且字典名「电池化学体系」!= label「化学体系」
    label_dict = {"电池化学体系": "dict_chemistry"}
    dict_id_map = {"dict_chemistry": "ID_CHEM"}
    dict_options_map = {"dict_chemistry": [{"valueCode": "lfp", "valueName": "磷酸铁锂"}]}

    ok = g2._bind_dict_on_component(comp, label_dict, dict_id_map, dict_options_map)

    assert ok is True, "组件带 dictCode 时必须绑上, 不该因 label!=字典名 而漏绑"
    assert comp["source"] == {"type": "DICTIONARY_TYPE", "id": "ID_CHEM"}
    assert comp["componentType"] == "FORM_SELECT_INPUT"
    assert len(comp["chooseOptions"]) == 1
    assert comp["dictionarySelectConfig"]["dictionaryCode"] == "dict_chemistry"


def test_bind_translates_spec_dictcode_via_dict_codes():
    """spec dict code 与平台 dictionaryCode 不同时(带租户后缀), 用 dict_codes 翻译。"""
    comp = {
        "componentType": "FORM_SELECT_INPUT_SINGLE",
        "label": "化学体系",
        "dictCode": "dict_chemistry",
    }
    dict_codes = {"dict_chemistry": "dict_chemistry_t57"}
    label_dict: dict = {}
    dict_id_map = {"dict_chemistry_t57": "IDX"}
    dict_options_map = {"dict_chemistry_t57": []}

    ok = g2._bind_dict_on_component(comp, label_dict, dict_id_map, dict_options_map, dict_codes)

    assert ok is True
    assert comp["source"]["id"] == "IDX"


def test_bind_falls_back_to_label_when_no_dict_ref():
    """组件没自带 dict 引用时, 保留原"字典名 == label"兜底行为(不回归)。"""
    comp = {"componentType": "FORM_SELECT_INPUT_SINGLE", "label": "护照状态"}
    label_dict = {"护照状态": "dict_passport_status"}
    dict_id_map = {"dict_passport_status": "ID5"}
    dict_options_map = {"dict_passport_status": []}

    ok = g2._bind_dict_on_component(comp, label_dict, dict_id_map, dict_options_map)

    assert ok is True
    assert comp["source"]["id"] == "ID5"


def test_bind_returns_false_when_no_dict_resolvable():
    """既无组件 dict 引用、label 也对不上任何字典 -> 不绑(返回 False)。"""
    comp = {"componentType": "FORM_SELECT_INPUT_SINGLE", "label": "未知字段"}
    ok = g2._bind_dict_on_component(comp, {}, {}, {})
    assert ok is False


def test_collect_spec_component_dict_map_by_label():
    """真实路径: 平台 save 剥掉组件 dictCode 后, 回写绑定只能从 spec 表单组件取 dict 引用,
    映射键是组件 label(== 平台组件 label), 而非平台字典名 —— 这正是「化学体系」漏绑的修复点。"""
    form_results = [
        {
            "formId": "f1",
            "formComponents": [
                {"label": "电池类型", "code": "battery_type",
                 "componentType": "FORM_SELECT_INPUT_SINGLE", "dictCode": "dict_battery_type"},
                {"label": "化学体系", "code": "chemistry_code",
                 "componentType": "FORM_SELECT_INPUT_SINGLE", "dict": "dict_chemistry"},
                {"label": "电池重量", "code": "battery_weight", "componentType": "FORM_NUMBER_INPUT"},
                # 子表内下拉
                {"componentType": "FORM_WIDGET_SON_TABLE", "tableColumn": [
                    {"label": "维修类型", "code": "maint_type",
                     "componentType": "FORM_SELECT_INPUT_SINGLE", "dictCode": "dict_maintenance_type"},
                ]},
            ],
        }
    ]
    dict_codes = {"dict_chemistry": "dict_chemistry"}  # 平台 code == spec code(本环境恒等)
    m = g2._collect_spec_component_dict_map(form_results, dict_codes)

    assert m["化学体系"] == "dict_chemistry"        # 核心: label 键, 与字典名「电池化学体系」无关
    assert m["电池类型"] == "dict_battery_type"
    assert m["维修类型"] == "dict_maintenance_type"  # 子表列也覆盖
    assert "电池重量" not in m                        # 非下拉、无 dict 引用 -> 不收


def test_bind_uses_model_field_before_duplicate_label_fallback():
    """多个表单都有「状态」时, 优先按 modelField 命中, 不被全局 label 映射错绑。"""
    comp = {
        "componentType": "FORM_SELECT_INPUT_SINGLE",
        "label": "状态",
        "modelField": "customer.status",
    }
    dict_lookup = {
        "状态": "order_status",
        "customer.status": "customer_status",
    }
    dict_id_map = {
        "customer_status": "ID_CUSTOMER_STATUS",
        "order_status": "ID_ORDER_STATUS",
    }
    dict_options_map = {
        "customer_status": [{"valueCode": "active", "valueName": "活跃"}],
        "order_status": [{"valueCode": "paid", "valueName": "已支付"}],
    }

    ok = g2._bind_dict_on_component(comp, dict_lookup, dict_id_map, dict_options_map)

    assert ok is True
    assert comp["source"] == {"type": "DICTIONARY_TYPE", "id": "ID_CUSTOMER_STATUS"}
    assert comp["chooseOptions"][0]["label"] == "活跃"
    assert comp["dictionarySelectConfig"]["dictionaryCode"] == "customer_status"


def test_collect_spec_component_dict_map_records_precise_keys_for_duplicate_labels():
    form_results = [{
        "formId": "f1",
        "formComponents": [
            {"label": "状态", "modelField": "customer.status",
             "componentType": "FORM_SELECT_INPUT_SINGLE", "dictCode": "customer_status"},
            {"label": "状态", "modelField": "order.status",
             "componentType": "FORM_SELECT_INPUT_SINGLE", "dictCode": "order_status"},
        ],
    }]

    lookup = g2._collect_spec_component_dict_map(form_results, {})

    assert lookup["customer.status"] == "customer_status"
    assert lookup["order.status"] == "order_status"
    assert lookup["状态"] == "order_status"  # label 仍保留为兜底, 精确键负责避免错绑


def test_build_form_components_preserves_dict_ref_for_create_payload():
    """第 12 步创建表单 payload 必须保留 dictCode, 才能在 create 前直接绑定。"""
    form = {
        "components": [{
            "componentType": "FORM_SELECT_INPUT_SINGLE",
            "label": "客户状态",
            "modelField": "customer.status",
            "dictCode": "customer_status",
        }],
    }

    components, _, _ = g2._build_form_components_from_definition(
        form,
        default_model_code="customer_platform",
        model_lookup={"customer": {"code": "customer_platform"}},
    )

    assert components[0]["modelField"] == "customer_platform.status"
    assert components[0]["dictCode"] == "customer_status"
    assert components[0]["dict"] == "customer_status"


def test_collect_label_dict_map_uses_platform_model_field_from_model_info():
    """第 12 步直接绑定时, lookup 要能用平台实际 modelField 命中字典。"""
    models = [{
        "name": "客户",
        "code": "customer",
        "fields": [{
            "name": "状态",
            "code": "status",
            "type": "下拉单选",
            "dict": "customer_status",
        }],
    }]
    model_info = {
        0: {"name": "客户", "code": "customer_platform", "fields": {"状态": "status_platform"}},
    }

    lookup = g2._collect_label_dict_map(models, {"customer_status": "customer_status_platform"}, model_info)

    assert lookup["customer_platform.status_platform"] == "customer_status_platform"
    assert lookup["customer.status"] == "customer_status_platform"


def test_bind_component_tree_populates_complete_schema_before_create_form():
    components = [{
        "componentType": "FORM_SELECT_INPUT_SINGLE",
        "label": "客户状态",
        "modelField": "customer_platform.status_platform",
    }]
    dict_lookup = {"customer_platform.status_platform": "customer_status"}
    dict_id_map = {"customer_status": "DICT_ID"}
    dict_options_map = {"customer_status": [{"valueCode": "active", "valueName": "活跃"}]}

    bound = g2._bind_dicts_on_component_tree(components, dict_lookup, dict_id_map, dict_options_map, {})

    assert bound == 1
    assert components[0]["source"] == {"type": "DICTIONARY_TYPE", "id": "DICT_ID"}
    assert components[0]["chooseOptions"][0]["label"] == "活跃"
    assert components[0]["dictionarySelectConfig"]["dictionaryCode"] == "customer_status"
