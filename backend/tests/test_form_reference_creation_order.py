import app.generator_v2 as g2


def test_data_selector_dependency_orders_target_form_first():
    forms = [
        {
            "name": "订单",
            "modelCode": "order",
            "components": [{
                "componentType": "FORM_DATA_SELECTOR_SINGLE",
                "label": "客户",
                "modelField": "order.customer_id",
                "ref": {"model": "customer", "field": "name"},
            }],
        },
        {
            "name": "客户",
            "modelCode": "customer",
            "components": [{"componentType": "FORM_TEXT_INPUT", "label": "名称", "modelField": "customer.name"}],
        },
    ]

    ordered, issues = g2._sort_forms_by_data_selector_dependencies(forms, {})

    assert issues == []
    assert [form["modelCode"] for form in ordered] == ["customer", "order"]


def test_data_selector_cycle_returns_issue_instead_of_ordering():
    forms = [
        {
            "name": "A表",
            "modelCode": "a",
            "components": [{
                "componentType": "FORM_DATA_SELECTOR_SINGLE",
                "label": "选B",
                "modelField": "a.b_id",
                "ref": {"model": "b", "field": "name"},
            }],
        },
        {
            "name": "B表",
            "modelCode": "b",
            "components": [{
                "componentType": "FORM_DATA_SELECTOR_SINGLE",
                "label": "选A",
                "modelField": "b.a_id",
                "ref": {"model": "a", "field": "name"},
            }],
        },
    ]

    _, issues = g2._sort_forms_by_data_selector_dependencies(forms, {})

    assert len(issues) == 1
    assert "数据选择引用存在循环" in issues[0]
    assert "A表" in issues[0]
    assert "B表" in issues[0]


def test_association_does_not_create_order_dependency():
    forms = [
        {
            "name": "A表",
            "modelCode": "a",
            "components": [{
                "componentType": "FORM_ASSOCIATION",
                "label": "关联B",
                "association_form_code": "b",
            }],
        },
        {
            "name": "B表",
            "modelCode": "b",
            "components": [{
                "componentType": "FORM_ASSOCIATION",
                "label": "关联A",
                "association_form_code": "a",
            }],
        },
    ]

    ordered, issues = g2._sort_forms_by_data_selector_dependencies(forms, {})

    assert issues == []
    assert ordered == forms


def test_association_components_are_skipped_from_initial_create_payload():
    form = {
        "components": [
            {
                "componentType": "FORM_TEXT_INPUT",
                "label": "名称",
                "modelField": "a.name",
            },
            {
                "componentType": "FORM_ASSOCIATION",
                "label": "关联B",
                "association_form_code": "b",
                "association_origin_field_code": "name",
                "association_target_field_code": "name",
            },
        ],
    }

    components, _, _ = g2._build_form_components_from_definition(
        form,
        default_model_code="a",
        model_lookup={"a": {"code": "a_platform"}, "b": {"code": "b_platform"}},
    )

    assert [component["componentType"] for component in components] == ["FORM_TEXT_INPUT"]
    assert components[0]["modelField"] == "a_platform.name"
