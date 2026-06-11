from app.routes.coding import _resolve_page_register_name


def test_page_register_name_uses_router_key_not_output_name():
    config = {
        "router": {
            "apaas-custom-quality-job-dashboard": {
                "name": "apaas-custom-quality-job-dashboard",
                "path": "apaas-custom-quality-job-dashboard",
            }
        },
        "outputName": "form-page-quality-job-dashboard",
    }

    assert _resolve_page_register_name(config, "质量驾驶舱大屏") == "apaas-custom-quality-job-dashboard"


def test_page_register_name_falls_back_when_router_missing():
    assert _resolve_page_register_name({"outputName": "form-page-demo"}, "Demo") == "Demo"
