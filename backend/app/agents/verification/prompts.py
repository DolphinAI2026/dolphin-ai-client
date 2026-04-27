"""VerificationAgent Prompts."""
from __future__ import annotations

from typing import Any


AGENT_SYSTEM_PROMPT = """你是 aPaaS 智能开发平台的**验收工程师**（Verification Agent）。

你的唯一任务：给定 Spec + Coding 产出的 workspace，**逐条验收** `intent.acceptance_criteria`
和 `constraints_hard` / `constraints_soft`，产出最终验收报告。

# 工作流

1. 收到的首条消息会给你完整 Spec + 当前 AC 检查状态
2. 对每条 `pending` 的 AC：
   - 用 `grep_code` 按关键词搜索 workspace（一次一个关键 query）
   - 用 `read_file` 精读关键文件（不要一次全读，按段读）
   - 综合判断 → 调用 `check_ac` 记录结果
3. 对所有 `constraints_hard`：检查是否违反，必要时调用 `check_ac`（或在 emit_report 时整体标注）
4. 所有 AC 检查完（无 pending）→ 调用 `emit_report` 产出最终报告，**结束循环**

# 检查原则

- **证据优先**：不要猜测，用 grep/read 找到代码证据再判 passed/failed
- **一条一调**：每条 AC 对应一次（或多次证据 → 一次）`check_ac`，不要合并
- **confidence 诚实**：找到明确证据 ≥ 0.85；推理但不确定 < 0.7
- **failed 要给修改提示**：evidence 字段说清楚"缺了什么"或"哪里错了"，供下游 CodingAgent 参考

# 终止

- 所有 AC 都已 check → 必须调 `emit_report`
- 最多 10 轮循环；超过强制降级（把 pending AC 标为 needs_review 并 emit）
- 禁止：不调 check_ac 就调 emit_report；不 emit_report 就结束对话

# 输出格式

- `grep_code`：返回命中的行，找不到时返回 []
- `read_file`：返回文件内容（最多 16KB）
- `check_ac`：记录结果，自动更新 state，返回更新后的 pending 列表
- `emit_report`：产出 VerificationReport，调用成功即本 session 结束

开始。"""


def build_user_prompt(
    *,
    spec_envelope: dict[str, Any],
    workspace_root: str,
    ac_items_snapshot: list[dict[str, Any]],
    constraint_snapshot: list[dict[str, Any]],
) -> str:
    """构造 VerificationAgent 首条 user 消息。

    包含：Spec 摘要 + 待验收 AC 列表 + 约束列表 + workspace 路径。
    """
    identity = spec_envelope.get("identity") or {}
    intent = spec_envelope.get("intent") or {}
    scene_type = spec_envelope.get("scene_type") or "?"

    lines: list[str] = []
    lines.append("## 目标 Spec")
    lines.append(f"- scene_type: `{scene_type}`")
    lines.append(f"- code_name: `{identity.get('code_name', '')}`")
    if identity.get("widget_code"):
        lines.append(f"- widget_code: `{identity['widget_code']}`")
    lines.append(f"- 核心目的: {intent.get('core_purpose', '')}")
    lines.append(f"- 原始需求: {intent.get('original_requirement', '')}")
    lines.append("")
    lines.append(f"## Workspace")
    lines.append(f"- 根目录: `{workspace_root}`")
    lines.append("")

    lines.append("## 待验收的 Acceptance Criteria")
    if not ac_items_snapshot:
        lines.append("（无 —— 这不应该发生）")
    else:
        for ac in ac_items_snapshot:
            tag = {
                "pending": "⏳",
                "passed": "✅",
                "failed": "❌",
                "needs_review": "⚠️",
            }.get(ac["status"], "?")
            lines.append(
                f"{tag} #{ac['index']} [{ac['status']}] {ac['description']}"
            )
    lines.append("")

    hard = [c for c in constraint_snapshot if c["severity"] == "hard"]
    soft = [c for c in constraint_snapshot if c["severity"] == "soft"]
    if hard:
        lines.append("## 硬约束（违反必须 failed）")
        for c in hard:
            lines.append(f"- [{c['status']}] {c['text']}")
        lines.append("")
    if soft:
        lines.append("## 软约束（违反仅 warning）")
        for c in soft:
            lines.append(f"- [{c['status']}] {c['text']}")
        lines.append("")

    lines.append("## 下一步")
    pending_count = sum(1 for a in ac_items_snapshot if a["status"] == "pending")
    if pending_count == 0:
        lines.append("所有 AC 已检查，直接调 `emit_report`。")
    else:
        lines.append(
            f"有 {pending_count} 条 pending AC 待检查。逐条用 grep_code / read_file "
            "找证据 → check_ac 记录；全部完成后 emit_report。"
        )

    return "\n".join(lines)
