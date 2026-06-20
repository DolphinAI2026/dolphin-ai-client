"""多产物分解编排:把多端请求拆成 N 个聚焦 sub_request, 各跑一次首轮 run_coding_pipeline,
挂同一 Project 分组。复用现有单产物流水线当生成原语;失败隔离;无计划则回落单产物。

源自招聘系统 dogfood:两端系统不再被塌缩成单页 mock,而是真分解成多个 aPaaS 产物。
"""
from __future__ import annotations

import logging
from typing import AsyncIterator, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


async def _default_project_factory(params, db) -> Optional[int]:
    """新建一个 Project 行作分组;失败返回 None(产物仍生成, 只是不分组)。"""
    try:
        from app.models import Project
        name = (params.message or "多产物应用").strip().split("\n")[0][:40]
        proj = Project(name=name, user_id=params.user_id, tenant_id=getattr(params, "tenant_id", None))
        db.add(proj)
        await db.commit()
        await db.refresh(proj)
        return proj.id
    except Exception as exc:  # noqa: BLE001 — 分组失败非致命
        logger.warning("Project 分组创建失败(非致命): %r", exc)
        return None


async def _default_serve(ws_id: str) -> Optional[int]:
    """best-effort 起本地预览, 返回 port 或 None(失败/非 ok)。"""
    from app.coding.workspace import WorkspaceManager
    info = await WorkspaceManager().start_serve(ws_id)
    return info.get("port") if info.get("status") == "ok" else None


def _sub_params(base, sub_request: str, project_id: Optional[int]):
    from app.coding.pipeline import PipelineParams
    return PipelineParams(
        message=sub_request, user_id=base.user_id, tenant_id=base.tenant_id,
        workspace_id=None, conversation_id=None, project_id=project_id,
        selected_model=getattr(base, "selected_model", None),
        force_codegen=True,  # 已分解的聚焦子任务: 直接 codegen, 不再各自 brainstorm/READ 门
    )


async def run_multi_artifact(
    params, db, *, available_scenes: set[str],
    decomposer: Callable[..., Awaitable],
    runner: Callable[..., AsyncIterator[dict]],
    project_factory: Optional[Callable[..., Awaitable]] = None,
    serve_fn: Optional[Callable[..., Awaitable]] = None,
    llm_cfg: Optional[dict] = None,
) -> AsyncIterator[dict]:
    """多端请求 → N 个产物;无计划/异常 → 回落整请求单产物一次。"""
    plan = None
    try:
        plan = await decomposer(params.message, llm_cfg or {}, available_scenes)
    except Exception as exc:  # noqa: BLE001
        logger.warning("分解异常, 回落单产物: %r", exc)
        plan = None

    if not plan:
        async for ev in runner(params, db):
            yield ev
        return

    factory = project_factory or _default_project_factory
    project_id = await factory(params, db)
    yield {"type": "multi_artifact_plan", "project_id": project_id,
           "artifacts": [{"name": a["name"], "side": a["side"], "scene": a["scene"]} for a in plan]}

    results = []
    for idx, art in enumerate(plan):
        ws_id = None
        status = "done"
        try:
            async for ev in runner(_sub_params(params, art["sub_request"], project_id), db):
                ev = {**ev, "artifact_index": idx, "artifact_name": art["name"]}
                if ev.get("type") == "done" and ev.get("workspace_id"):
                    ws_id = ev["workspace_id"]
                yield ev
        except Exception as exc:  # noqa: BLE001 — 单产物失败隔离, 不整崩
            status = "failed"
            logger.warning("产物 %s 生成失败: %r", art["name"], exc)
            yield {"type": "multi_artifact_error", "artifact_index": idx,
                   "artifact_name": art["name"], "message": str(exc)}
        # G3: best-effort 给该产物起本地预览(仅注入了 serve_fn 时, 单测默认不跑真 serve)
        port = None
        if ws_id and status == "done" and serve_fn is not None:
            try:
                port = await serve_fn(ws_id)
            except Exception as exc:  # noqa: BLE001 — 起预览失败非致命
                logger.warning("产物 %s 起预览失败(非致命): %r", art["name"], exc)
                port = None
        results.append({"name": art["name"], "side": art["side"], "scene": art["scene"],
                        "workspace_id": ws_id, "status": status, "port": port})

    yield {"type": "multi_artifact_summary", "project_id": project_id, "artifacts": results}
