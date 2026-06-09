"""aPaaS 编辑器路径构建（从 platform_proxy 抽出的纯函数）。"""
from __future__ import annotations

from app.apaas_editor_url import build_editor_entry_path, build_editor_path


def test_model_menu_path():
    p = build_editor_path("MODEL", apaas_app_id="A1", menu_id="M9", form_id="F3", tid="T7")
    assert p == "/platform/T7/default/data-model-fn-config?appId=A1&menuId=M9&formId=F3&processVersion=false"


def test_no_menu_id_goes_to_overview():
    p = build_editor_path("", apaas_app_id="A1", menu_id="", form_id="", tid="T7")
    assert p == "/platform/T7/admin/app-store/edit-app?appId=A1&currentStepIndex=0"


def test_quote_menu_type_subpath():
    p = build_editor_path("QUOTE", apaas_app_id="A1", menu_id="M2", form_id="", tid="T7")
    assert p == "/platform/T7/default/quote-fn-config?appId=A1&menuId=M2&processVersion=false"


def test_unknown_menu_type_defaults_fn_config():
    p = build_editor_path("WHATEVER", apaas_app_id="A1", menu_id="M2", form_id="", tid="T7")
    assert p.startswith("/platform/T7/default/fn-config?appId=A1&menuId=M2")


def test_no_embed_flags():
    # 真标签页要完整编辑器，不带 embed=1/hideClose=1
    p = build_editor_path("MODEL", apaas_app_id="A1", menu_id="M9", form_id="F3", tid="T7")
    assert "embed=1" not in p and "hideClose=1" not in p


def test_editor_entry_path_goes_to_menu_step():
    p = build_editor_entry_path(apaas_app_id="A1", tid="T7")
    assert p == "/platform/T7/admin/app-store/edit-app?appId=A1&currentStepIndex=2"
