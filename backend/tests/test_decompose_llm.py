import app.coding.decompose as dc
from app.coding.decompose import decompose

SCENES = {"form-list", "menu-page", "mobile-page", "form-page"}
CFG = {"api_key": "k", "base_url": "u", "model": "m"}


async def test_returns_plan_from_llm(monkeypatch):
    monkeypatch.setattr(dc, "_call_decompose_llm", lambda p, c: (
        '{"artifacts":[{"name":"职位管理","side":"admin","scene":"form-list","sub_request":"做职位管理列表页"},'
        '{"name":"求职端","side":"user","scene":"mobile-page","sub_request":"做求职移动端"}]}'))
    plan = await decompose("招聘系统 管理端+用户端两端", CFG, SCENES)
    assert plan is not None and len(plan) == 2


async def test_falls_back_to_none_on_llm_error(monkeypatch):
    def boom(p, c):
        raise RuntimeError("llm down")
    monkeypatch.setattr(dc, "_call_decompose_llm", boom)
    assert await decompose("招聘系统两端", CFG, SCENES) is None


async def test_none_when_llm_returns_single(monkeypatch):
    monkeypatch.setattr(dc, "_call_decompose_llm", lambda p, c:
        '{"artifacts":[{"name":"x","side":"admin","scene":"form-list","sub_request":"做列表"}]}')
    assert await decompose("做个列表", CFG, SCENES) is None


async def test_strips_json_fence(monkeypatch):
    monkeypatch.setattr(dc, "_call_decompose_llm", lambda p, c: (
        '```json\n{"artifacts":[{"name":"a","side":"admin","scene":"form-list","sub_request":"x"},'
        '{"name":"b","side":"user","scene":"mobile-page","sub_request":"y"}]}\n```'))
    plan = await decompose("两端系统", CFG, SCENES)
    assert plan is not None and len(plan) == 2
