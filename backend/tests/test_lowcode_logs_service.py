from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.lowcode_logs import (
    build_lowcode_log_analysis,
    extract_lowcode_log_records,
    filter_lowcode_logs_for_application,
    normalize_lowcode_log_record,
)


def test_normalize_lowcode_record_maps_platform_fields_and_risk():
    item = normalize_lowcode_log_record(
        {
            "id": "log-1",
            "operationTime": "2026-06-14 21:58:42",
            "functionMenu": "高级设置",
            "operationObject": "智能体WMS系统.自开发配置",
            "operationDescription": "启用了【自开发配置】",
            "operationType": "编辑",
            "operationUserName": "管理",
        }
    )

    assert item["id"] == "lowcode-log-1"
    assert item["timestamp"] == "2026-06-14 21:58:42"
    assert item["type"] == "编辑"
    assert item["user"] == "管理"
    assert item["status"] == "risk_medium"
    assert item["summary"] == "高级设置 · 智能体WMS系统.自开发配置 · 启用了【自开发配置】"
    assert item["details"]["risk_level"] == "medium"
    assert item["details"]["function_menu"] == "高级设置"


def test_extract_lowcode_log_records_accepts_common_platform_shapes():
    assert extract_lowcode_log_records({"table": [{"id": 1}]}) == [{"id": 1}]
    assert extract_lowcode_log_records({"data": {"records": [{"id": 2}]}}) == [{"id": 2}]
    assert extract_lowcode_log_records({"data": {"list": [{"id": 3}]}}) == [{"id": 3}]
    assert extract_lowcode_log_records([{"id": 4}]) == [{"id": 4}]


def test_filter_lowcode_logs_for_application_matches_name_code_and_apaas_id():
    app = SimpleNamespace(app_name="智能体WMS系统", app_code="wms_app", apaas_app_id="10010")
    rows = [
        {"operationObject": "智能体WMS系统.菜单功能", "operationDescription": "新增菜单"},
        {"operationObject": "其他应用.菜单功能", "operationDescription": "appCode=wms_app"},
        {"operationObject": "平台配置", "operationDescription": "应用ID:10010 发布成功"},
        {"operationObject": "完全无关", "operationDescription": "ignore me"},
    ]

    matched = filter_lowcode_logs_for_application(rows, app)

    assert matched == rows[:3]


def test_build_lowcode_log_analysis_counts_risks_and_dimensions():
    items = [
        normalize_lowcode_log_record(
            {
                "operationTime": "2026-06-14 21:59:46",
                "functionMenu": "应用信息",
                "operationObject": "智能体WMS系统.智能体WMS系统",
                "operationDescription": "发布了应用【智能体WMS系统】",
                "operationType": "发布",
                "operationUserName": "管理",
            }
        ),
        normalize_lowcode_log_record(
            {
                "operationTime": "2026-06-14 21:58:42",
                "functionMenu": "高级设置",
                "operationObject": "智能体WMS系统.自开发配置",
                "operationDescription": "启用了【自开发配置】",
                "operationType": "编辑",
                "operationUserName": "管理",
            }
        ),
        normalize_lowcode_log_record(
            {
                "operationTime": "2026-06-14 21:57:01",
                "functionMenu": "菜单功能",
                "operationObject": "智能体WMS系统.仓库区域",
                "operationDescription": "新增了菜单【仓库区域】",
                "operationType": "新增",
                "operationUserName": "运营",
            }
        ),
    ]

    analysis = build_lowcode_log_analysis(items)

    assert analysis["total"] == 3
    assert analysis["risk_total"] == 2
    assert analysis["high_risk_total"] == 0
    assert analysis["top_operation_types"][0] == {"name": "发布", "count": 1}
    assert analysis["top_menus"][0]["name"] == "应用信息"
    assert "最近 3 条低代码变更" in analysis["summary"]

