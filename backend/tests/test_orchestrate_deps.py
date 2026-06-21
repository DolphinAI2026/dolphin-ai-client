from app.coding.orchestrate import run_multi_artifact
from app.coding.decompose import Artifact


class _P:
    message = "招聘 管理端+用户端"; user_id = 1; tenant_id = 1
    workspace_id = None; conversation_id = None; project_id = None
    selected_model = None; app_id = None; attachments = None


def _runner(rec):
    async def runner(params, db):
        rec.append(params.message)
        yield {"type": "done", "workspace_id": f"ws_{len(rec)}", "conversation_id": None}
    return runner


async def _decomposer_with_deps(req, cfg, scenes):
    arts = [Artifact(name="后台", side="admin", scene="form-list", sub_request="管理列表"),
            Artifact(name="用户端", side="user", scene="mobile-page", sub_request="移动端")]
    deps = [{"from": 0, "to": 1, "expose": "暴露 /api/ticket",
             "consume": "consume ticketApi", "note": "改字段影响用户端"}]
    return arts, deps


async def test_writes_resolved_edges():
    written = []
    async def dep_writer(project_id, edges):
        written.append((project_id, edges))
    async def proj_factory(params, db):
        return 42
    rec = []
    events = [ev async for ev in run_multi_artifact(
        _P(), db=None, available_scenes={"form-list", "mobile-page"},
        decomposer=_decomposer_with_deps, runner=_runner(rec),
        project_factory=proj_factory, dep_writer=dep_writer)]
    assert len(written) == 1
    pid, edges = written[0]
    assert pid == 42 and len(edges) == 1
    assert edges[0]["from_ref"] == "workspace:ws_1"
    assert edges[0]["to_ref"] == "workspace:ws_2"
    assert edges[0]["expose_label"] == "暴露 /api/ticket"


async def test_legacy_list_decomposer_still_works():
    # 旧 fake 返回 list(无 deps),不传 dep_writer → 不崩、不写边
    async def legacy(req, cfg, scenes):
        return [Artifact(name="a", side="admin", scene="form-list", sub_request="x"),
                Artifact(name="b", side="user", scene="mobile-page", sub_request="y")]
    rec = []
    events = [ev async for ev in run_multi_artifact(
        _P(), db=None, available_scenes={"form-list", "mobile-page"},
        decomposer=legacy, runner=_runner(rec), project_factory=None)]
    assert any(e.get("type") == "multi_artifact_summary" for e in events)
