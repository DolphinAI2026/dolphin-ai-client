from __future__ import annotations

import asyncio
from datetime import datetime

from app.apaas_session import call_apaas_with_relogin

from .types import AppSnapshotInput


PROCESS_DETAIL_CONCURRENCY = 8
PROCESS_DETAIL_CAP = 40  # 流程过多则跳过详情拉取（连通性检查转 N/A），避免 N+1 失控


async def _safe(coro):
    try:
        return await coro, True
    except Exception:
        return None, False


async def _enrich_processes(client, aid: str, procs):
    """流程列表接口不含 edges（连线只在详情里），逐流程拉详情补齐 nodes+edges。

    单流程详情失败 → 不标 _detail_ok，连通性检查对该流程转 N/A（不误判断流）。
    流程数超 PROCESS_DETAIL_CAP → 整体跳过详情拉取。
    """
    procs = [p for p in procs if isinstance(p, dict)]
    if not procs or len(procs) > PROCESS_DETAIL_CAP:
        return procs
    sem = asyncio.Semaphore(PROCESS_DETAIL_CONCURRENCY)

    async def _one(p):
        pid = str(p.get("id") or "")
        if not pid:
            return p
        async with sem:
            try:
                detail = await client.query_process_config(aid, pid)
            except Exception:
                return p
        data = detail.get("data") if isinstance(detail, dict) else None
        if not isinstance(data, dict):
            return p
        return {
            **p,
            "nodes": data.get("nodes") or p.get("nodes") or [],
            "edges": data.get("edges") or [],
            "_detail_ok": True,
        }

    return list(await asyncio.gather(*[_one(p) for p in procs]))


async def collect_app_snapshot(app, env_id: int, db, as_of: datetime) -> AppSnapshotInput:
    aid = str(app.apaas_app_id)

    async def fn(client):
        results = await asyncio.gather(
            _safe(client.query_menus(aid)),
            _safe(client.query_models(aid, with_fields=False)),
            _safe(client.query_dicts(aid)),
            _safe(client.query_roles(aid)),
            _safe(client.list_processes(aid)),
            _safe(client.list_business_events(aid)),
            _safe(client.query_app_list()),
        )
        # 流程：列表不含 edges，逐流程补详情拿真实连线
        procs, ok_p = results[4]
        if ok_p and procs:
            try:
                results[4] = (await _enrich_processes(client, aid, procs), True)
            except Exception:
                pass
        return results

    res = await call_apaas_with_relogin(env_id, db, fn)
    (menus, ok_m), (models, ok_md), (dicts, ok_d), (roles, ok_r), \
        (procs, ok_p), (events, ok_e), (applist, ok_a) = res

    app_entry = None
    if ok_a and isinstance(applist, list):
        app_entry = next(
            (a for a in applist if str(a.get("id")) == aid or str(a.get("appId")) == aid),
            None,
        )
    cov = {
        "menus": ok_m,
        "models": ok_md,
        "dicts": ok_d,
        "roles": ok_r,
        "processes": ok_p,
        "events": ok_e,
        "app_entry": bool(app_entry),
    }
    return AppSnapshotInput(
        app_id=app.id,
        apaas_app_id=aid,
        as_of=as_of,
        menus=menus,
        models=models,
        dicts=dicts,
        roles=roles,
        processes=procs,
        events=events,
        app_entry=app_entry,
        deploy_records=[],
        coverage=cov,
    )
