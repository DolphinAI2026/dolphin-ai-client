"""generator_v2 Phase 5：把解析出的 workflows 在 aPaaS 平台建成审批流程。

build_workflow_payload —— 纯函数：按 form_code 反查 formId/menuId，按 role_code 反查角色雪花 id，
组成已验证的平台 payload。create_workflows —— async generator：逐条建、调 save_process_config，
单条失败（找不到表单/角色/平台报错）只 yield 一个 stage:5 告警，绝不中断（流程是增强、非核心）。
"""
from __future__ import annotations

import logging
from typing import AsyncIterator, List, Optional, Tuple

from app.process_payload import build_process_payload

logger = logging.getLogger(__name__)


def _workflow_process_code(form_code: str, name: str) -> str:
    """确定性 ascii 流程编码。V1 假设一表单一流程，proc_<form_code> 已足够唯一。"""
    return f"proc_{form_code}"


def build_workflow_payload(
    wf: dict, form_results: List[dict], role_code_map: dict, *, app_id: str
) -> Tuple[Optional[dict], Optional[str]]:
    """(payload, None) 成功；(None, reason) 跳过（reason 是给用户的告警文案）。纯函数，无 IO。"""
    form_code = wf.get("form_code")
    fr = next((f for f in form_results if f.get("formCode") == form_code), None)
    if not fr or not fr.get("formId"):
        return None, f"流程 '{wf.get('name')}'：关联表单 '{form_code}' 未找到或未创建成功，跳过"

    stages: List[dict] = []
    for node in wf.get("nodes", []):
        role_code = node.get("role_code")
        info = role_code_map.get(role_code) or {}
        role_id = info.get("id")
        if not role_id:
            return None, f"流程 '{wf.get('name')}'：审批人角色 '{role_code}' 未找到（需在第二章定义），跳过"
        stages.append({
            "name": node.get("name") or "审批",
            "approver_type": "ROLE",
            "approver_value": str(role_id),
            "approver_label": info.get("roleName") or role_code,
        })
    if not stages:
        return None, f"流程 '{wf.get('name')}'：无有效审批节点，跳过"

    payload = build_process_payload(
        app_id=app_id,
        form_id=fr["formId"],
        menu_id=fr.get("menuId", ""),
        process_name=wf.get("name") or "审批流程",
        process_code=_workflow_process_code(form_code, wf.get("name") or ""),
        stages_with_role=stages,
    )
    return payload, None


async def create_workflows(
    client, app_id: str, workflows: List[dict], form_results: List[dict], role_code_map: dict
) -> AsyncIterator[dict]:
    """Phase 5：逐条建审批流程。非致命 —— 任何一条失败只告警，继续下一条。"""
    if not workflows:
        return
    yield {"stage": 5, "status": "running", "step": f"创建审批流程（{len(workflows)} 条）..."}
    created_indices: list[int] = []
    for idx, wf in enumerate(workflows):
        payload, reason = build_workflow_payload(wf, form_results, role_code_map, app_id=app_id)
        if reason:
            yield {"stage": 5, "status": "running", "step": f"⚠️ {reason}", "workflow_index": idx}
            continue
        try:
            await client.save_process_config(app_id, payload)
            created_indices.append(idx)
            yield {"stage": 5, "status": "running", "step": f"流程: {wf.get('name')}", "workflow_index": idx}
        except Exception as e:
            logger.warning("create workflow failed: %s", e, exc_info=True)
            yield {"stage": 5, "status": "running", "step": f"⚠️ 流程 '{wf.get('name')}' 创建失败（{e}），跳过", "workflow_index": idx}
    yield {
        "stage": 5,
        "status": "done",
        "step": f"审批流程完成（{len(created_indices)}/{len(workflows)} 条）",
        "created": len(created_indices),
        "total": len(workflows),
        "created_indices": created_indices,
    }
