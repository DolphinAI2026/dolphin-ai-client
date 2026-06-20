from app.coding.decompose import parse_decomposition

SCENES = {"form-list", "menu-page", "mobile-page", "form-page"}


def test_parses_valid_two_artifact_plan():
    raw = ('{"artifacts":[{"name":"职位管理","side":"admin","scene":"form-list","sub_request":"做一个职位管理列表页"},'
           '{"name":"求职端","side":"user","scene":"mobile-page","sub_request":"做求职者移动端"}]}')
    plan = parse_decomposition(raw, SCENES)
    assert plan is not None and len(plan) == 2
    assert plan[0]["scene"] == "form-list" and plan[1]["side"] == "user"


def test_none_when_single_artifact():
    raw = '{"artifacts":[{"name":"x","side":"admin","scene":"form-list","sub_request":"做个列表"}]}'
    assert parse_decomposition(raw, SCENES) is None


def test_drops_illegal_scene_keeps_valid():
    raw = ('{"artifacts":[{"name":"a","side":"admin","scene":"WAT","sub_request":"x"},'
           '{"name":"b","side":"admin","scene":"form-list","sub_request":"y"},'
           '{"name":"c","side":"user","scene":"mobile-page","sub_request":"z"}]}')
    plan = parse_decomposition(raw, SCENES)
    assert plan is not None and len(plan) == 2 and all(a["scene"] in SCENES for a in plan)


def test_caps_at_max():
    arts = ",".join('{"name":"n%d","side":"admin","scene":"form-list","sub_request":"r"}' % i for i in range(8))
    plan = parse_decomposition('{"artifacts":[%s]}' % arts, SCENES, max_artifacts=4)
    assert plan is not None and len(plan) == 4


def test_none_on_garbage():
    assert parse_decomposition("not json", SCENES) is None
    assert parse_decomposition('{"artifacts":[]}', SCENES) is None
    assert parse_decomposition('{"artifacts":[{"scene":"form-list"}]}', SCENES) is None
