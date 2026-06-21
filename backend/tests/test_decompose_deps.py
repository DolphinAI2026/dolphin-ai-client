from app.coding.decompose import parse_dependencies


def test_parses_valid_dependency():
    raw = ('{"artifacts":[{},{}],"dependencies":[{"from":0,"to":1,'
           '"expose":"暴露 /api/ticket","consume":"consume ticketApi","note":"改字段会影响用户端"}]}')
    deps = parse_dependencies(raw, n_artifacts=2)
    assert len(deps) == 1
    assert deps[0]["from"] == 0 and deps[0]["to"] == 1
    assert deps[0]["expose"] == "暴露 /api/ticket"


def test_drops_out_of_range_and_self_ref():
    raw = ('{"dependencies":[{"from":0,"to":5,"expose":"x","consume":"y","note":""},'
           '{"from":1,"to":1,"expose":"x","consume":"y","note":""},'
           '{"from":0,"to":1,"expose":"ok","consume":"ok","note":""}]}')
    deps = parse_dependencies(raw, n_artifacts=2)
    assert len(deps) == 1 and deps[0]["expose"] == "ok"


def test_empty_when_missing_or_illegal():
    assert parse_dependencies('{"artifacts":[{}]}', 1) == []
    assert parse_dependencies('not json', 2) == []
    assert parse_dependencies('{"dependencies":"nope"}', 2) == []
