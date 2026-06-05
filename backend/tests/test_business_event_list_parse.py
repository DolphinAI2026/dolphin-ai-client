"""回归: apaas /xdap-app/event/query/list 把业务事件放在【顶层 table/total】, 不是包在 data 里。

根因(2026-06-05 app10 电池护照系统实测坐实): apaas 返
  {"code":"ok","total":1,"table":[{eventId,eventName,triggerType,executionEvent,status,...}]}
但 list_business_events 老代码 `return data.get("data") or {}` —— 响应里【没有 data 键】→
永远返 {} → 业务事件面板查不到任何事件(明明后台有)。规整成 {table,total} 即修。
"""
from app.apaas_client import _normalize_business_event_list


REAL_RESP = {
    "code": "ok",
    "message": "操作成功",
    "total": 1,
    "table": [
        {
            "eventId": "6a2286ba74cfbc26cbf28d05",
            "status": "ENABLE",
            "eventName": "电池护照生效自动生成生产建档事件",
            "triggerType": "电池护照档案.表单提交成功后",
            "executionEvent": "自定义节点",
            "version": "v3.0",
            "intactFlag": True,
        }
    ],
}


def test_extracts_top_level_table_and_total():
    """核心: 顶层 table/total 要被取出来(老代码取 data → 空, 这就是 bug)。"""
    out = _normalize_business_event_list(REAL_RESP)
    assert out["total"] == 1
    assert len(out["table"]) == 1
    assert out["table"][0]["eventName"] == "电池护照生效自动生成生产建档事件"
    assert out["table"][0]["triggerType"] == "电池护照档案.表单提交成功后"


def test_old_data_key_returns_empty_is_the_bug():
    """坐实老行为=bug: resp 没有 'data' 键, 取 data 必空; 规整后必须非空。"""
    assert REAL_RESP.get("data") is None  # 老代码 data.get("data") → None → {} → 0 事件
    out = _normalize_business_event_list(REAL_RESP)
    assert out["table"], "规整后必须能从顶层 table 取到事件"


def test_nested_data_fallback():
    """兜底: 个别环境若真包在 data 里也能取。"""
    resp = {"code": "ok", "data": {"total": 2, "table": [{"eventId": "a"}, {"eventId": "b"}]}}
    out = _normalize_business_event_list(resp)
    assert out["total"] == 2
    assert len(out["table"]) == 2


def test_records_and_list_aliases():
    assert _normalize_business_event_list({"records": [{"eventId": "x"}]})["table"][0]["eventId"] == "x"
    assert _normalize_business_event_list({"list": [{"eventId": "y"}]})["table"][0]["eventId"] == "y"


def test_empty_and_garbage():
    assert _normalize_business_event_list({"code": "ok"}) == {"table": [], "total": 0}
    assert _normalize_business_event_list(None) == {"table": [], "total": 0}
    # total 缺失时按 table 长度兜底
    assert _normalize_business_event_list({"table": [{"eventId": "1"}]})["total"] == 1
