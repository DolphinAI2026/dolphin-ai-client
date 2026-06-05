"""回归: 生成表单配置时不得注入 detailPage.webFormSettings / mobileFormSettings。

根因(2026-06-05 实测+肉眼坐实): 注入空的 webFormSettings={} 后, apaas 会展开成
formTitleConfigList 指向不存在的 "formName" 标题组件, 表单设计器画布渲染崩(暂无数据,
字段"选不出来")。原生/对话(build_apaas_feature_from_spec)建的表单都不带这俩。
"""
import app.generator_v2 as g2
import app.step_executor as se


def test_generator_v2_force_form_identity_no_webform_settings():
    cfg: dict = {"detailPage": {}}
    g2._force_form_identity(
        cfg, form_name="设备报修", form_code="repair_form", all_model_codes=["repair"],
        app_id="a", form_id="f", menu_id="m",
    )
    dp = cfg["detailPage"]
    assert "webFormSettings" not in dp, "不应注入 webFormSettings(会让设计器画布崩)"
    assert "mobileFormSettings" not in dp, "不应注入 mobileFormSettings"
    # 保留的默认仍在, 确认没误删
    assert dp.get("previewLanguage") == "zh-CN"
    assert "formVersionConfig" in dp


def test_step_executor_apply_form_identity_no_webform_settings():
    cfg: dict = {"detailPage": {}}
    se._apply_form_identity_to_form_config(
        cfg, form_name="设备报修", form_code="repair_form", all_model_codes=["repair"],
        app_id="a", form_id="f", menu_id="m",
    )
    dp = cfg["detailPage"]
    assert "webFormSettings" not in dp
    assert "mobileFormSettings" not in dp
    assert dp.get("previewLanguage") == "zh-CN"
    assert "formVersionConfig" in dp
