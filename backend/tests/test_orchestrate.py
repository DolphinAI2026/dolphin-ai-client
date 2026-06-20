from app.coding.orchestrate import run_multi_artifact
from app.coding.decompose import Artifact


class _Params:
    def __init__(self):
        self.message = "招聘系统 管理端+用户端"
        self.user_id = 1
        self.tenant_id = 1
    workspace_id = None
    conversation_id = None
    project_id = None
    selected_model = None
    app_id = None
    attachments = None


def test_sub_params_forces_codegen():
    from app.coding.orchestrate import _sub_params

    class B:
        user_id = 1
        tenant_id = 1
        selected_model = None
    p = _sub_params(B(), "做个职位列表页", 7)
    assert p.force_codegen is True and p.project_id == 7 and p.message == "做个职位列表页"


async def _fake_decomposer(req, cfg, scenes):
    return [Artifact(name="后台", side="admin", scene="form-list", sub_request="做招聘管理列表页"),
            Artifact(name="求职端", side="user", scene="mobile-page", sub_request="做求职移动端")]


def _make_runner(record):
    async def runner(params, db):
        record.append(params.message)
        yield {"type": "step", "step": "generate", "status": "done", "data": {}}
        yield {"type": "done", "workspace_id": f"ws_{len(record)}", "conversation_id": None}
    return runner


async def test_decomposes_runs_n_subpipelines_and_groups():
    record = []
    events = []

    async def proj_factory(params, db):
        return 77

    async for ev in run_multi_artifact(_Params(), db=None,
            available_scenes={"form-list", "mobile-page"},
            decomposer=_fake_decomposer, runner=_make_runner(record),
            project_factory=proj_factory):
        events.append(ev)

    assert len(record) == 2
    assert any("职位" in m or "招聘" in m or "管理" in m or "求职" in m for m in record)
    assert any(e.get("type") == "multi_artifact_plan" for e in events)
    summ = [e for e in events if e.get("type") == "multi_artifact_summary"][0]
    assert summ["project_id"] == 77 and len(summ["artifacts"]) == 2


async def test_falls_back_to_single_when_no_plan():
    record = []

    async def none_decomposer(req, cfg, scenes):
        return None

    events = [ev async for ev in run_multi_artifact(_Params(), db=None,
            available_scenes={"form-list"}, decomposer=none_decomposer,
            runner=_make_runner(record), project_factory=None)]
    assert len(record) == 1
    assert record[0] == "招聘系统 管理端+用户端"
    assert not any(e.get("type") == "multi_artifact_plan" for e in events)


async def test_isolates_failing_artifact():
    record = []

    async def runner(params, db):
        record.append(params.message)
        if "求职" in params.message:
            raise RuntimeError("boom")
        yield {"type": "done", "workspace_id": "ws", "conversation_id": None}

    async def proj_factory(params, db):
        return 5

    events = [ev async for ev in run_multi_artifact(_Params(), db=None,
            available_scenes={"form-list", "mobile-page"}, decomposer=_fake_decomposer,
            runner=runner, project_factory=proj_factory)]
    summ = [e for e in events if e.get("type") == "multi_artifact_summary"][0]
    fails = [a for a in summ["artifacts"] if a.get("status") == "failed"]
    assert len(fails) == 1 and len(record) == 2


async def test_auto_serves_each_artifact_and_records_port():
    record = []
    served = []

    async def serve_fn(ws_id):
        served.append(ws_id)
        return 8100 + len(served)

    async def proj_factory(params, db):
        return 9

    events = [ev async for ev in run_multi_artifact(_Params(), db=None,
            available_scenes={"form-list", "mobile-page"}, decomposer=_fake_decomposer,
            runner=_make_runner(record), project_factory=proj_factory, serve_fn=serve_fn)]
    summ = [e for e in events if e.get("type") == "multi_artifact_summary"][0]
    assert served == ["ws_1", "ws_2"]                 # 每个产物都起了 serve
    ports = [a.get("port") for a in summ["artifacts"]]
    assert ports == [8101, 8102]


async def test_serve_failure_is_non_fatal():
    record = []

    async def serve_fn(ws_id):
        raise RuntimeError("serve boom")

    async def proj_factory(params, db):
        return 1

    events = [ev async for ev in run_multi_artifact(_Params(), db=None,
            available_scenes={"form-list", "mobile-page"}, decomposer=_fake_decomposer,
            runner=_make_runner(record), project_factory=proj_factory, serve_fn=serve_fn)]
    summ = [e for e in events if e.get("type") == "multi_artifact_summary"][0]
    assert len(summ["artifacts"]) == 2                # serve 失败不影响产物
    assert all(a.get("port") is None for a in summ["artifacts"])
