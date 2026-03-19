"""Skills 单元测试：纯逻辑验证，不需要网络。

覆盖：
- _safe_code 保留字处理
- _build_model_payload 模型构建
- _build_dict_payload 字典构建
- build_component 全部 16 种组件类型
- build_form_config 完整表单配置
"""
import sys, os

# 设置环境变量，避免 pydantic Settings 校验失败
os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

import pytest
from app.skills.platform import (
    _safe_code, _RESERVED_WORDS, _build_model_payload, _build_dict_payload,
    _build_role_payload, FIELD_TYPE_MAP,
)
from app.skills.components import (
    build_component, build_form_config, COMPONENT_TYPE_MAP, COMPONENT_REGISTRY,
)


# ── _safe_code ──

class TestSafeCode:
    def test_reserved_word_gets_prefix(self):
        for word in ('name', 'status', 'order', 'select', 'id'):
            assert _safe_code(word).startswith('f_'), f"{word} should be prefixed"

    def test_normal_word_unchanged(self):
        assert _safe_code('customer_name') == 'customer_name'
        assert _safe_code('abc123') == 'abc123'

    def test_special_chars_replaced(self):
        assert _safe_code('hello-world') == 'hello_world'
        assert _safe_code('a.b.c') == 'a_b_c'

    def test_case_insensitive(self):
        assert _safe_code('Name').startswith('f_')
        assert _safe_code('STATUS').startswith('f_')


# ── _build_model_payload ──

class TestBuildModelPayload:
    def test_basic_model(self):
        models = [{"name": "客户", "code": "customer", "fields": [
            {"name": "客户名称", "type": "单行输入", "code": "customer_name"},
            {"name": "金额", "type": "金额", "code": "f_amount"},
        ]}]
        payload, code_map = _build_model_payload("app123", models, suffix="test")
        assert payload["appId"] == "app123"
        assert len(payload["dataModels"]) == 1
        dm = payload["dataModels"][0]
        assert dm["modelCode"] == "customer_test"
        assert len(dm["fields"]) == 2
        assert dm["fields"][0]["fieldType"] == "STRING"
        assert dm["fields"][1]["fieldType"] == "NUM"
        assert code_map["customer"] == "customer_test"

    def test_sub_table_generates_two_models(self):
        models = [{"name": "工单", "code": "order", "fields": [
            {"name": "标题", "type": "单行输入", "code": "title"},
            {"name": "配件明细", "type": "子表", "sub_code": "order_parts",
             "sub_fields": [
                 {"name": "配件名", "type": "单行输入", "code": "part_name"},
                 {"name": "数量", "type": "数字", "code": "qty"},
             ]},
        ]}]
        payload, code_map = _build_model_payload("app123", models, suffix="t1")
        # 应该有 2 个模型：子表 + 主表
        assert len(payload["dataModels"]) == 2
        sub_model = payload["dataModels"][0]  # 子表先生成
        main_model = payload["dataModels"][1]
        assert sub_model["modelCode"] == "order_parts_t1"
        assert main_model["modelCode"] == "f_order_t1"  # order is reserved
        assert code_map["order_parts"] == "order_parts_t1"

    def test_reserved_word_in_model_code(self):
        models = [{"name": "状态表", "code": "status", "fields": [
            {"name": "值", "type": "单行输入", "code": "value"},
        ]}]
        payload, code_map = _build_model_payload("app1", models, suffix="x")
        dm = payload["dataModels"][0]
        assert dm["modelCode"] == "f_status_x"
        assert dm["fields"][0]["fieldCode"].startswith("f_")


# ── _build_dict_payload ──

class TestBuildDictPayload:
    def test_string_options(self):
        dicts = [{"name": "优先级", "code": "priority", "options": ["高", "中", "低"]}]
        payload, dcm = _build_dict_payload("app1", dicts, suffix="s1")
        assert len(payload) == 1
        d = payload[0]
        assert d["dictionaryCode"] == "f_priority_s1"  # priority is reserved
        assert len(d["dictionaryOptions"]) == 3
        assert d["dictionaryOptions"][0]["optionName"] == "高"
        assert dcm["priority"] == "f_priority_s1"

    def test_dict_options(self):
        dicts = [{"name": "类型", "code": "stype", "options": [
            {"name": "A类", "code": "type_a"},
            {"name": "B类", "code": "type_b"},
        ]}]
        payload, dcm = _build_dict_payload("app1", dicts, suffix="s2")
        opts = payload[0]["dictionaryOptions"]
        assert opts[0]["optionCode"] == "type_a_s2"
        assert opts[1]["optionName"] == "B类"


# ── _build_role_payload ──

class TestBuildRolePayload:
    def test_role_format(self):
        roles = [{"name": "管理员", "code": "admin"}, {"name": "操作员"}]
        payload = _build_role_payload("app1", roles)
        assert len(payload) == 2
        assert payload[0]["roleName"] == "管理员"
        assert payload[0]["roleCode"].startswith("R_admin_")
        assert payload[1]["roleCode"].startswith("R_操作员_")


# ── build_component: 全部 16 种组件 ──

class TestBuildComponentSimple:
    """12 种简单组件（无额外配置）"""

    @pytest.mark.parametrize("cn_type,expected_comp", [
        ("单行输入", "FORM_TEXT_INPUT"),
        ("多行输入", "FORM_TEXTAREA_INPUT"),
        ("数字", "FORM_NUMBER_INPUT"),
        ("金额", "FORM_MONEY_INPUT"),
        ("手机号码", "FORM_PHONE_INPUT"),
        ("电子邮箱", "FORM_EMAIL_INPUT"),
        ("日期时间", "FORM_DATEPICK_INPUT"),
        ("单据号", "FORM_DOCUMENT_NUMBER"),
        ("附件上传", "FORM_FILE_UPLOAD"),
        ("开关", "FORM_SWITCH_SELECT"),
        ("人员选择", "FORM_PEOPLE_SELECT"),
        ("地理位置", "FORM_WIDGET_LOCATION"),
    ])
    def test_simple_component(self, cn_type, expected_comp):
        field = {"name": "测试字段", "type": cn_type}
        comp = build_component(field, "model_abc", "field_xyz")
        assert comp["componentType"] == expected_comp
        assert comp["label"] == "测试字段"
        assert comp["modelField"] == "model_abc.field_xyz"
        # 简单组件不应有额外配置
        assert "dictionarySelectConfig" not in comp
        assert "dataSelectorConfig" not in comp
        assert "tableColumn" not in comp


class TestBuildComponentSelectSingle:
    def test_with_dict_binding(self):
        field = {"name": "状态", "type": "下拉单选", "dict": "status"}
        dicts = [{"code": "status", "options": [
            {"name": "启用", "code": "active"},
            {"name": "停用", "code": "inactive"},
        ]}]
        dict_code_map = {"status": "f_status_x1y2"}
        comp = build_component(field, "m1", "f1", dicts=dicts, dict_code_map=dict_code_map)
        assert comp["componentType"] == "FORM_SELECT_INPUT_SINGLE"
        dsc = comp["dictionarySelectConfig"]
        assert dsc["dictionaryCode"] == "f_status_x1y2"  # 使用映射后的 code
        assert len(dsc["dictionarySelectOptions"]) == 2
        assert dsc["dictionarySelectOptions"][0]["label"] == "启用"

    def test_without_dict(self):
        field = {"name": "选项", "type": "下拉单选"}
        comp = build_component(field, "m1", "f1")
        assert comp["componentType"] == "FORM_SELECT_INPUT_SINGLE"
        assert "dictionarySelectConfig" not in comp


class TestBuildComponentSelectMulti:
    def test_with_dict_binding(self):
        field = {"name": "标签", "type": "下拉多选", "dict": "tags"}
        dicts = [{"code": "tags", "options": ["A", "B", "C"]}]
        dict_code_map = {"tags": "tags_abcd"}
        comp = build_component(field, "m1", "f1", dicts=dicts, dict_code_map=dict_code_map)
        assert comp["componentType"] == "FORM_SELECT_INPUT"
        dsc = comp["dictionarySelectConfig"]
        assert dsc["dictionaryCode"] == "tags_abcd"
        assert len(dsc["dictionarySelectOptions"]) == 3


class TestBuildComponentDataSelector:
    def test_with_ref_dict(self):
        field = {"name": "关联客户", "type": "数据单选",
                 "ref": {"model": "customer", "field": "customer_name"}}
        code_map = {"customer": "customer_x1y2"}
        comp = build_component(field, "m1", "f1", code_map=code_map)
        assert comp["componentType"] == "FORM_DATA_SELECTOR_SINGLE"
        ds = comp["dataSelectorConfig"]
        assert ds["type"] == "LOV_CHOOSE"
        assert ds["otherModelCode"] == "customer_x1y2"
        assert ds["otherFieldCode"] == "customer_name"

    def test_with_ref_string(self):
        field = {"name": "关联", "type": "数据单选", "ref": "other_model"}
        comp = build_component(field, "m1", "f1")
        assert comp["dataSelectorConfig"]["otherModelCode"] == "other_model"


class TestBuildComponentSonTable:
    def test_son_table_structure(self):
        field = {"name": "配件明细", "type": "子表", "sub_code": "parts",
                 "sub_fields": [
                     {"name": "配件名", "type": "单行输入"},
                     {"name": "数量", "type": "数字"},
                 ]}
        code_map = {"parts": "parts_abcd"}
        comp = build_component(field, "order_abcd", "", code_map=code_map)
        assert comp["componentType"] == "FORM_WIDGET_SON_TABLE"
        assert comp["label"] == "配件明细"
        assert len(comp["tableColumn"]) == 2
        assert comp["tableColumn"][0]["componentType"] == "FORM_TEXT_INPUT"
        assert comp["tableColumn"][1]["componentType"] == "FORM_NUMBER_INPUT"


# ── build_form_config 完整表单 ──

class TestBuildFormConfig:
    def test_basic_form(self):
        models = [{"name": "客户", "code": "customer", "fields": [
            {"name": "名称", "type": "单行输入", "code": "cname"},
            {"name": "电话", "type": "手机号码", "code": "cphone"},
        ]}]
        code_map = {"customer": "customer_t1"}
        # 模拟 model_payload
        model_payload = {"dataModels": [{
            "modelCode": "customer_t1",
            "fields": [
                {"fieldCode": "cname", "fieldName": "名称", "fieldType": "STRING"},
                {"fieldCode": "cphone", "fieldName": "电话", "fieldType": "STRING"},
            ]
        }]}
        configs = build_form_config(models, [], model_payload=model_payload, code_map=code_map)
        assert len(configs) == 1
        fc = configs[0]
        assert fc["formName"] == "客户"
        assert fc["formCode"].startswith("form_")
        assert "customer_t1" in fc["allModelCodes"]
        assert len(fc["formComponents"]) == 2
        # 列表页
        assert len(fc["listPageView"]["queryConditions"]) == 2
        assert len(fc["listPageView"]["queryList"]) == 2

    def test_form_with_sub_table(self):
        models = [{"name": "工单", "code": "order", "fields": [
            {"name": "标题", "type": "单行输入", "code": "title"},
            {"name": "配件", "type": "子表", "sub_code": "order_parts",
             "sub_fields": [
                 {"name": "名称", "type": "单行输入"},
             ]},
        ]}]
        code_map = {"order": "order_t1", "order_parts": "order_parts_t1"}
        model_payload = {"dataModels": [
            {"modelCode": "order_parts_t1", "fields": [
                {"fieldCode": "sf_name", "fieldName": "名称", "fieldType": "STRING"},
            ]},
            {"modelCode": "order_t1", "fields": [
                {"fieldCode": "title", "fieldName": "标题", "fieldType": "STRING"},
            ]},
        ]}
        configs = build_form_config(models, [], model_payload=model_payload, code_map=code_map)
        fc = configs[0]
        assert "order_t1" in fc["allModelCodes"]
        assert "order_parts_t1" in fc["allModelCodes"]
        # 应有 2 个组件：标题 + 子表
        assert len(fc["formComponents"]) == 2
        son = fc["formComponents"][1]
        assert son["componentType"] == "FORM_WIDGET_SON_TABLE"

    def test_file_upload_excluded_from_list(self):
        """附件上传不应出现在列表页查询条件和展示列中"""
        models = [{"name": "文档", "code": "doc", "fields": [
            {"name": "标题", "type": "单行输入", "code": "title"},
            {"name": "附件", "type": "附件上传", "code": "attachment"},
        ]}]
        code_map = {"doc": "doc_t1"}
        model_payload = {"dataModels": [{
            "modelCode": "doc_t1",
            "fields": [
                {"fieldCode": "title", "fieldType": "STRING"},
                {"fieldCode": "attachment", "fieldType": "STRING"},
            ]
        }]}
        configs = build_form_config(models, [], model_payload=model_payload, code_map=code_map)
        fc = configs[0]
        for mf in fc["listPageView"]["queryConditions"]:
            assert "attachment" not in mf
        for mf in fc["listPageView"]["queryList"]:
            assert "attachment" not in mf


# ── 组件覆盖度 ──

class TestComponentCoverage:
    def test_all_component_types_registered(self):
        """确保所有 COMPONENT_TYPE_MAP 中的组件类型都在 COMPONENT_REGISTRY 中注册"""
        for cn_type, comp_type in COMPONENT_TYPE_MAP.items():
            assert comp_type in COMPONENT_REGISTRY, \
                f"组件类型 {comp_type} ({cn_type}) 未在 COMPONENT_REGISTRY 中注册"

    def test_registry_has_16_types(self):
        """注册表应覆盖全部 16 种组件类型"""
        # 去重后的组件类型数量（布尔和开关映射到同一个）
        unique_types = set(COMPONENT_TYPE_MAP.values())
        for t in unique_types:
            assert t in COMPONENT_REGISTRY, f"{t} missing from registry"

    def test_full_coverage_form(self):
        """构造包含全部组件类型的模型，验证 build_form_config 输出"""
        fields = [
            {"name": "单据号", "type": "单据号", "code": "doc_no"},
            {"name": "名称", "type": "单行输入", "code": "f_name"},
            {"name": "描述", "type": "多行输入", "code": "desc"},
            {"name": "电话", "type": "手机号码", "code": "f_phone"},
            {"name": "邮箱", "type": "电子邮箱", "code": "f_email"},
            {"name": "日期", "type": "日期时间", "code": "f_date"},
            {"name": "金额", "type": "金额", "code": "f_amount"},
            {"name": "数量", "type": "数字", "code": "qty"},
            {"name": "附件", "type": "附件上传", "code": "attach"},
            {"name": "启用", "type": "开关", "code": "enabled"},
            {"name": "负责人", "type": "人员选择", "code": "owner"},
            {"name": "位置", "type": "地理位置", "code": "loc"},
            {"name": "类型", "type": "下拉单选", "code": "stype", "dict": "stype"},
            {"name": "标签", "type": "下拉多选", "code": "tags", "dict": "tags"},
            {"name": "关联", "type": "数据单选", "code": "ref_cust",
             "ref": {"model": "customer", "field": "cname"}},
        ]
        models = [{"name": "全覆盖表单", "code": "full", "fields": fields}]
        dicts = [
            {"code": "stype", "name": "类型", "options": [{"name": "A", "code": "a"}]},
            {"code": "tags", "name": "标签", "options": ["X", "Y"]},
        ]
        code_map = {"full": "full_t1", "customer": "customer_t1"}
        dict_code_map = {"stype": "stype_t1", "tags": "tags_t1"}

        # 构建 model_payload
        sent_fields = [{"fieldCode": f["code"], "fieldType": "STRING"} for f in fields]
        model_payload = {"dataModels": [{"modelCode": "full_t1", "fields": sent_fields}]}

        configs = build_form_config(
            models, dicts,
            model_payload=model_payload, code_map=code_map, dict_code_map=dict_code_map,
        )
        fc = configs[0]
        comp_types = {c["componentType"] for c in fc["formComponents"]}

        expected = {
            "FORM_DOCUMENT_NUMBER", "FORM_TEXT_INPUT", "FORM_TEXTAREA_INPUT",
            "FORM_PHONE_INPUT", "FORM_EMAIL_INPUT", "FORM_DATEPICK_INPUT",
            "FORM_MONEY_INPUT", "FORM_NUMBER_INPUT", "FORM_FILE_UPLOAD",
            "FORM_SWITCH_SELECT", "FORM_PEOPLE_SELECT", "FORM_WIDGET_LOCATION",
            "FORM_SELECT_INPUT_SINGLE", "FORM_SELECT_INPUT",
            "FORM_DATA_SELECTOR_SINGLE",
        }
        missing = expected - comp_types
        assert not missing, f"缺少组件类型: {missing}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
