from datetime import datetime
from app.builder_spec.schema import (
    Spec, Phase, Goal, Role, FieldSpec, ObjectSpec, DictSpec, DictOption,
    PermissionRule, PermissionSpec, Completeness,
)
from app.builder_spec.converter import spec_to_config


def _full_spec():
    """A minimally-complete SPEC ready for conversion."""
    return Spec(
        id="spec_full",
        phase=Phase.GENERATING,
        goal=Goal(title="预算管理", summary="x", business_problem="y", confirmed=True),
        roles=[Role(code="finance_lead", name="财务负责人", scope="ALL", confirmed=True)],
        objects=[ObjectSpec(
            code="t_quarter_forecast", name="季度预测", confirmed=True,
            fields=[
                FieldSpec(code="forecast_no", name="预测编号", type="单据号", required=True, confirmed=True),
                FieldSpec(code="amount", name="金额", type="数字", required=True, confirmed=True),
                FieldSpec(code="status", name="状态", type="下拉单选", dict_code="forecast_status", confirmed=True),
            ],
        )],
        dicts=[DictSpec(code="forecast_status", name="预测状态", confirmed=True, options=[
            DictOption(code="draft", name="草稿"),
            DictOption(code="confirmed", name="已确认"),
        ])],
        permissions=[PermissionSpec(object_code="t_quarter_forecast", confirmed=True, rules=[
            PermissionRule(role="all", op="all", data="ALL"),
            PermissionRule(role="finance_lead", op="edit", data="DEPT"),
        ])],
        completeness=Completeness(confirmed=8, total=8),
        created_at=datetime(2026, 4, 25), updated_at=datetime(2026, 4, 25),
        created_by=1,
    )


def test_converter_emits_appName():
    config = spec_to_config(_full_spec())
    assert config["appName"] == "预算管理"


def test_converter_emits_roles():
    config = spec_to_config(_full_spec())
    assert config["roles"] == [{"code": "finance_lead", "name": "财务负责人"}]


def test_converter_emits_dicts_with_options():
    config = spec_to_config(_full_spec())
    assert config["dicts"] == [{
        "code": "forecast_status", "name": "预测状态",
        "options": [{"code": "draft", "name": "草稿"}, {"code": "confirmed", "name": "已确认"}],
    }]


def test_converter_emits_models_with_fields():
    config = spec_to_config(_full_spec())
    models = config["models"]
    assert len(models) == 1
    m = models[0]
    assert m["code"] == "t_quarter_forecast"
    assert m["name"] == "季度预测"
    assert len(m["fields"]) == 3
    f0 = m["fields"][0]
    assert f0["code"] == "forecast_no"
    assert f0["type"] == "单据号"
    assert f0["required"] is True


def test_converter_attaches_dict_to_field():
    config = spec_to_config(_full_spec())
    status_field = next(f for f in config["models"][0]["fields"] if f["code"] == "status")
    assert status_field.get("dict") == "forecast_status"


def test_converter_emits_permissions():
    config = spec_to_config(_full_spec())
    perms = config["permissions"]
    assert len(perms) == 1
    assert perms[0]["form"] == "t_quarter_forecast"
    assert {"role": "all", "op": "all", "data": "ALL"} in perms[0]["rules"]


def test_converter_skips_unconfirmed_items():
    """Per design: only confirmed items go into the config."""
    spec = _full_spec()
    spec.roles[0].confirmed = False  # unconfirmed role should not appear
    config = spec_to_config(spec)
    assert config["roles"] == []


def test_converter_wraps_with_data_envelope():
    """Top-level structure must match preview JSON envelope used by frontend."""
    config = spec_to_config(_full_spec())
    # The current preview consumer reads either {"data": {...}} or flat dict; we emit flat.
    assert "appName" in config
    assert "models" in config
    assert "roles" in config
