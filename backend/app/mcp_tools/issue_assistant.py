"""Issue recording and dev-fix policy MCP tools."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


_ISSUE_REPORTS_PATH = Path(
    os.getenv(
        "ISSUE_REPORTS_PATH",
        str(Path(__file__).resolve().parents[2] / ".run" / "issue-reports.jsonl"),
    )
)

_registered_mcp_ids: set[int] = set()


def _read_issue_reports(limit: int = 200) -> list[dict]:
    if not _ISSUE_REPORTS_PATH.exists():
        return []
    rows: list[dict] = []
    try:
        with _ISSUE_REPORTS_PATH.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []
    return rows[-max(1, min(limit, 1000)):]


def register(mcp, resolve_identity: Callable[[int | None, int | None], tuple[int, int]]) -> None:
    """Register issue/support tools on the shared FastMCP instance."""
    marker = id(mcp)
    if marker in _registered_mcp_ids:
        return
    _registered_mcp_ids.add(marker)

    @mcp.tool()
    async def record_support_triage(
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
    ) -> dict:
        """记录外挂问题分诊智能体的判断结果。

        category 取值：操作问题 / Bug / 需求 / 待确认。
        本工具只负责记录分类、判断原因和给用户的回复，不会创建工单、改代码或部署。
        """
        try:
            tid, uid = resolve_identity(tenant_id, user_id)
        except Exception:
            tid, uid = int(tenant_id or 0), int(user_id or 0)
        from app.support_triage_records import write_support_triage_record
        return write_support_triage_record(
            user_question=user_question,
            category=category,
            summary=summary,
            reason=reason,
            user_reply=user_reply,
            confidence=confidence,
            missing_info=missing_info,
            priority=priority,
            status=status,
            source=source,
            tenant_id=tid,
            user_id=uid,
        )

    @mcp.tool()
    async def record_product_issue(
        summary: str,
        user_message: str,
        classification: str,
        severity: str = "normal",
        current_url: str = "",
        page_title: str = "",
        reproduction_steps: str = "",
        expected_behavior: str = "",
        actual_behavior: str = "",
        evidence_json: str = "",
        suggested_action: str = "",
        can_auto_fix: bool = False,
        auto_fix_scope: str = "dev",
        tenant_id: int = 0,
        user_id: int = 0,
    ) -> dict:
        """记录右侧得小帆识别出的产品问题或疑似 Bug。

        classification 取值：bug / howto / config / permission / feature_request / needs_info。
        只有 classification=bug 且 can_auto_fix=true 时，后续才允许进入 dev 分支修复流程。
        本工具只记录，不会修改 git，不会部署。
        """
        tid, uid = resolve_identity(tenant_id, user_id)
        classification = (classification or "").strip().lower()
        allowed_classifications = {"bug", "howto", "config", "permission", "feature_request", "needs_info"}
        if classification not in allowed_classifications:
            return {
                "ok": False,
                "error_code": "INVALID_CLASSIFICATION",
                "message": f"classification 必须是 {sorted(allowed_classifications)}",
            }
        severity = (severity or "normal").strip().lower()
        if severity not in {"low", "normal", "high", "critical"}:
            severity = "normal"
        if not summary.strip() or not user_message.strip():
            return {"ok": False, "error_code": "INVALID_PARAMS", "message": "summary 和 user_message 必填"}

        report_id = f"ISS-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uid}"
        evidence: Any = None
        if evidence_json.strip():
            try:
                evidence = json.loads(evidence_json)
            except Exception:
                evidence = {"raw": evidence_json[:4000]}

        row = {
            "id": report_id,
            "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "tenant_id": tid,
            "user_id": uid,
            "summary": summary.strip()[:240],
            "user_message": user_message.strip()[:4000],
            "classification": classification,
            "severity": severity,
            "current_url": current_url.strip()[:1000],
            "page_title": page_title.strip()[:300],
            "reproduction_steps": reproduction_steps.strip()[:4000],
            "expected_behavior": expected_behavior.strip()[:2000],
            "actual_behavior": actual_behavior.strip()[:2000],
            "evidence": evidence,
            "suggested_action": suggested_action.strip()[:2000],
            "can_auto_fix": bool(can_auto_fix and classification == "bug"),
            "auto_fix_scope": "dev" if auto_fix_scope != "none" else "none",
            "status": "recorded",
        }

        try:
            _ISSUE_REPORTS_PATH.parent.mkdir(parents=True, exist_ok=True)
            with _ISSUE_REPORTS_PATH.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        except Exception as exc:
            return {"ok": False, "error_code": "WRITE_FAILED", "message": f"问题记录失败: {exc}"}

        return {
            "ok": True,
            "issue_id": report_id,
            "classification": classification,
            "severity": severity,
            "can_auto_fix": row["can_auto_fix"],
            "next_action": (
                "已记录为 Bug；若可自动修复，只允许提交到 dev 分支，等待 19:00 dev 自动部署。"
                if classification == "bug"
                else "已记录为非 Bug；请直接给用户操作指引或补充信息。"
            ),
        }

    @mcp.tool()
    async def list_product_issues(
        classification: str = "",
        status: str = "",
        limit: int = 20,
        tenant_id: int = 0,
        user_id: int = 0,
    ) -> dict:
        """列出右侧得小帆记录的问题。默认只看当前租户。"""
        tid, _uid = resolve_identity(tenant_id, user_id)
        rows = _read_issue_reports(limit=500)
        if tid:
            rows = [r for r in rows if int(r.get("tenant_id") or 0) == tid]
        if classification.strip():
            c = classification.strip().lower()
            rows = [r for r in rows if str(r.get("classification") or "").lower() == c]
        if status.strip():
            s = status.strip().lower()
            rows = [r for r in rows if str(r.get("status") or "").lower() == s]
        rows = rows[-max(1, min(limit, 100)):]
        rows.reverse()
        return {"ok": True, "count": len(rows), "issues": rows}

    @mcp.tool()
    async def get_dev_fix_policy(tenant_id: int = 0, user_id: int = 0) -> dict:
        """返回得小帆自动修复与 dev 部署策略。

        用于回答用户"能不能自动修"、"什么时候部署"、"会不会动 main"等问题。
        """
        resolve_identity(tenant_id, user_id)
        return {
            "ok": True,
            "branch_policy": {
                "allowed_branch": "dev",
                "forbidden_branches": ["main", "master", "prod", "production"],
                "auto_fix_requires_bug": True,
                "must_commit_before_deploy": True,
                "dirty_worktree_deploy": "forbidden",
            },
            "deploy_policy": {
                "environment": "dev",
                "schedule": "每天 19:00 自动部署 dev",
                "automation_id": "19-00-dev",
                "deploy_command": "scripts/deploy_k8s_dev.sh",
                "production_deploy": "不由得小帆自动触发",
            },
            "reply_template": (
                "如果确认是 Bug，我会记录问题；可自动修复的只提交到 dev 分支。"
                "dev 环境每天 19:00 自动部署，main 分支不会被修改。"
            ),
        }

