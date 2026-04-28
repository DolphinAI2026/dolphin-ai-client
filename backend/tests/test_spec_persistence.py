import pytest
from app.builder_spec.persistence import bootstrap_from_legacy_config
from app.builder_spec.schema import Phase


def test_bootstrap_from_legacy_config_basic():
    cfg = {
        "appName": "ems",
        "roles": [{"code": "approver", "name": "审批人", "scope": "DEPT"}],
        "dicts": [{"code": "ems_status", "name": "报销状态",
                   "options": [{"code": "draft", "name": "草稿"}]}],
        "models": [{"code": "t_ems_form", "name": "报销单", "fields": [
            {"code": "amount", "name": "金额", "type": "数字", "required": True},
            {"code": "status", "name": "状态", "type": "下拉单选", "dict": "ems_status"},
        ]}],
        "permissions": [{"form": "t_ems_form", "rules": [
            {"role": "all", "op": "all", "data": "ALL"},
        ]}],
    }
    spec = bootstrap_from_legacy_config(application_id=99, legacy_config=cfg, created_by=1)

    assert spec.phase == Phase.DRAFTING
    assert spec.application_id == 99
    assert spec.goal.title == "ems"
    assert spec.goal.confirmed is False
    assert len(spec.roles) == 1 and spec.roles[0].code == "approver"
    assert len(spec.dicts) == 1 and len(spec.dicts[0].options) == 1
    assert len(spec.objects) == 1 and len(spec.objects[0].fields) == 2
    field_status = next(f for f in spec.objects[0].fields if f.code == "status")
    assert field_status.dict_code == "ems_status"
    assert len(spec.permissions) == 1
    assert all(not r.confirmed for r in spec.roles)
    assert spec.completeness.total > 0
    assert spec.completeness.confirmed == 0
