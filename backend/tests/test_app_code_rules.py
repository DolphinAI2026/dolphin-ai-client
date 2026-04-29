from app.app_code import is_valid_app_code, normalize_app_code
from app.config_assembler import _normalize_app_code as normalize_assembled_app_code
from app.routes.applications._helpers import (
    _is_valid_app_code as route_is_valid_app_code,
    _normalize_app_code as normalize_route_app_code,
)
from app.routes.requirements import _infer_unified_app_code, _normalize_doc_app_info
from app.services.config_converter import convert_analysis_to_app_config


def test_low_code_app_code_validation_rules():
    assert is_valid_app_code("hr-mgmt")
    assert is_valid_app_code("a")
    assert is_valid_app_code("a1-b2")

    assert not is_valid_app_code("app_mgmt")
    assert not is_valid_app_code("App")
    assert not is_valid_app_code("1app")
    assert not is_valid_app_code("hr管理")
    assert not is_valid_app_code("a" * 18)


def test_low_code_app_code_normalization_is_shared():
    assert normalize_app_code("APP_MGMT") == "app-mgmt"
    assert normalize_app_code("  1_app__Code  ") == "app-1-app-code"
    assert normalize_app_code("hr-mgmt-v1-extra-long") == "hr-mgmt-v1-extra"

    assert normalize_route_app_code("APP_MGMT") == "app-mgmt"
    assert route_is_valid_app_code("app-mgmt")
    assert normalize_assembled_app_code("APP_MGMT") == "app-mgmt"


def test_requirements_doc_uses_low_code_app_code_rules():
    assert _normalize_doc_app_info({"name": "综合人才管理系统", "code": "APP_MGMT"})["code"] == "app-mgmt"
    assert _normalize_doc_app_info({"name": "综合人才管理系统"})["code"] == "talent-mgmt"
    assert _infer_unified_app_code("请假管理系统") == "leave-mgmt"


def test_doc_to_preview_conversion_preserves_low_code_app_code():
    config = convert_analysis_to_app_config({
        "app_info": {"name": "综合人才管理系统", "code": "APP_MGMT"},
        "roles": [],
        "data_dictionary": [],
        "tables": [],
        "flows": [],
        "role_table_mapping": [],
    })

    assert config["appCode"] == "app-mgmt"
