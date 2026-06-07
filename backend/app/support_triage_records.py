"""Support triage record persistence shared by MCP endpoints."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


SUPPORT_TRIAGE_RECORDS_PATH = Path(
    os.getenv(
        "SUPPORT_TRIAGE_RECORDS_PATH",
        str(Path(__file__).resolve().parent.parent / ".run" / "support-triage-records.jsonl"),
    )
)


def write_support_triage_record(
    *,
    user_question: str,
    category: str,
    summary: str,
    reason: str,
    user_reply: str,
    confidence: str = "中",
    missing_info: str = "",
    priority: str = "P2",
    status: str = "新建",
    source: str = "external_agent",
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict[str, Any]:
    category = (category or "").strip()
    allowed_categories = {"操作问题", "Bug", "需求", "待确认"}
    if category not in allowed_categories:
        return {
            "ok": False,
            "error_code": "INVALID_CATEGORY",
            "message": f"category 必须是 {sorted(allowed_categories)}",
        }

    confidence = (confidence or "中").strip()
    if confidence not in {"高", "中", "低"}:
        confidence = "中"

    priority = (priority or "P2").strip().upper()
    if priority not in {"P0", "P1", "P2", "P3"}:
        priority = "P2"

    if not user_question.strip() or not summary.strip() or not user_reply.strip():
        return {
            "ok": False,
            "error_code": "INVALID_PARAMS",
            "message": "user_question、summary 和 user_reply 必填",
        }

    record_id = f"TRIAGE-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{user_id or 'anon'}"
    row = {
        "id": record_id,
        "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "tenant_id": int(tenant_id or 0),
        "user_id": int(user_id or 0),
        "source": (source or "external_agent").strip()[:80],
        "user_question": user_question.strip()[:4000],
        "category": category,
        "confidence": confidence,
        "summary": summary.strip()[:240],
        "reason": reason.strip()[:2000],
        "user_reply": user_reply.strip()[:4000],
        "missing_info": missing_info.strip()[:2000],
        "priority": priority,
        "status": (status or "新建").strip()[:40],
    }

    success = True
    error = None
    try:
        SUPPORT_TRIAGE_RECORDS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with SUPPORT_TRIAGE_RECORDS_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception as exc:
        success = False
        error = f"分诊记录失败: {exc}"

    result = {
        "ok": True,
        "record_id": record_id,
        "category": category,
        "priority": priority,
        "status": row["status"],
        "path": str(SUPPORT_TRIAGE_RECORDS_PATH),
        "user_reply": row["user_reply"],
    }
    if not success:
        result = {"ok": False, "error_code": "WRITE_FAILED", "message": error}

    try:
        from app.routes.mcp_platform import append_mcp_call_log
        append_mcp_call_log({
            "service": "support-triage",
            "path": "/api/support-triage-mcp/mcp",
            "rpc_method": "tools/call",
            "tool": "record_support_triage",
            "request_arguments": {
                "user_question": row["user_question"],
                "category": row["category"],
                "confidence": row["confidence"],
                "summary": row["summary"],
                "reason": row["reason"],
                "user_reply": row["user_reply"],
                "missing_info": row["missing_info"],
                "priority": row["priority"],
                "status": row["status"],
                "source": row["source"],
            },
            "status_code": 200 if success else 500,
            "success": success,
            "error": error,
            "auth_source": "mcp_api_key_or_admin_tester",
            "local_user_id": row["user_id"] or None,
            "local_tenant_id": row["tenant_id"] or None,
        })
    except Exception:
        pass

    return result
