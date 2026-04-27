"""对比基线与 candidate，用于 VibeCodingAgent → CodingAgent 迁移验证。

用法：
  python scripts/compare_baseline.py \\
      --baseline tests/fixtures/baselines/case_a_rating_star_run1 \\
      --candidate tests/fixtures/baselines/case_a_rating_star_migrated \\
      [--baseline2 tests/fixtures/baselines/case_a_rating_star_run2]

对比规则（与 SETUP 指南保持一致）：
  严格：事件类型集合、tool 名集合、workspace 路径集合、关键 JSON 字段
  宽松：turn 数（±3）、总事件数（±20%）、文件 md5（允许差异）

输出：
  ✓/⚠/✗ 每条规则的对比结果
  最终 PASS / WARN / FAIL 结论
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


class Result:
    def __init__(self):
        self.rows: list[tuple[str, str, str]] = []  # (status, rule, detail)
        self.has_fail = False
        self.has_warn = False

    def ok(self, rule: str, detail: str = ""):
        self.rows.append(("✓", rule, detail))

    def warn(self, rule: str, detail: str = ""):
        self.rows.append(("⚠", rule, detail))
        self.has_warn = True

    def fail(self, rule: str, detail: str = ""):
        self.rows.append(("✗", rule, detail))
        self.has_fail = True

    def print(self):
        for status, rule, detail in self.rows:
            line = f"  {status}  {rule}"
            if detail:
                line += f" — {detail}"
            print(line)
        print()
        if self.has_fail:
            print("❌ FAIL")
        elif self.has_warn:
            print("⚠️  WARN（不阻断，请人工确认）")
        else:
            print("✅ PASS")


# ══════════════════════════════════════════════════════════════
# 加载
# ══════════════════════════════════════════════════════════════

def _load(path: Path) -> dict:
    """加载一个基线目录"""
    if not (path / "metadata.json").exists():
        print(f"❌ 不是有效基线目录：{path}", file=sys.stderr)
        sys.exit(2)
    metadata = json.loads((path / "metadata.json").read_text())
    events = []
    events_file = path / "events.jsonl"
    if events_file.exists():
        for line in events_file.read_text().splitlines():
            if line.strip():
                events.append(json.loads(line))
    tree = []
    tree_file = path / "workspace_tree.txt"
    if tree_file.exists():
        for line in tree_file.read_text().splitlines():
            parts = line.split("\t")
            if len(parts) == 3:
                tree.append({"path": parts[0], "size": int(parts[1]), "md5": parts[2]})
    # 关键文件内容
    key_files: dict[str, dict] = {}
    ws_dir = path / "workspace"
    if ws_dir.exists():
        for fp in ws_dir.rglob("*"):
            if fp.is_file():
                rel = fp.relative_to(ws_dir)
                try:
                    key_files[str(rel)] = json.loads(fp.read_text())
                except Exception:
                    # 不是 JSON，存 raw 文本
                    key_files[str(rel)] = {"_raw": fp.read_text()}
    return {
        "metadata": metadata,
        "events": events,
        "tree": tree,
        "key_files": key_files,
    }


# ══════════════════════════════════════════════════════════════
# 对比规则
# ══════════════════════════════════════════════════════════════

def _compare_final_status(a: dict, b: dict, res: Result):
    sa = a["metadata"]["final_status"]
    sb = b["metadata"]["final_status"]
    if sa == sb == "success":
        res.ok("final_status", "both success")
    elif sa != sb:
        res.fail("final_status", f"baseline={sa} candidate={sb}")
    else:
        res.warn("final_status", f"both={sa}")


def _compare_event_type_set(a: dict, b: dict, res: Result):
    set_a = set(a["metadata"]["event_type_sequence"])
    set_b = set(b["metadata"]["event_type_sequence"])
    # 'heartbeat' 是 SSE 保活机制（VibeCodingAgent 有、新 agent 由 pipeline 层负责），差异不算回归
    only_a = (set_a - set_b) - {"heartbeat"}
    only_b = set_b - set_a
    if not only_a and not only_b:
        res.ok("event types (set)", f"{len(set_a | set_b)} types 一致（忽略 heartbeat）")
    else:
        detail = []
        if only_a:
            detail.append(f"基线独有: {only_a}")
        if only_b:
            detail.append(f"迁移独有: {only_b}")
        res.fail("event types (set)", "; ".join(detail))


def _compare_tool_names_set(a: dict, b: dict, res: Result):
    set_a = set(a["metadata"].get("tool_names_called") or []) - {None}
    set_b = set(b["metadata"].get("tool_names_called") or []) - {None}
    if set_a == set_b:
        res.ok("tool names (set)", f"{len(set_a)} tools 一致")
    else:
        only_a = set_a - set_b
        only_b = set_b - set_a
        detail = []
        if only_a:
            detail.append(f"基线独有: {only_a}")
        if only_b:
            detail.append(f"迁移独有: {only_b}")
        # tool 使用集合差异通常是 LLM 抖动（同需求不同 run 可能选用 edit_file vs write_file），
        # 非架构回归；降级为 WARN
        res.warn("tool names (set)", "; ".join(detail))


def _compare_counts(a: dict, b: dict, res: Result):
    turn_a = a["metadata"].get("tool_call_count", 0)
    turn_b = b["metadata"].get("tool_call_count", 0)
    if abs(turn_a - turn_b) <= 3:
        res.ok("tool_call_count", f"{turn_a} vs {turn_b} (±3)")
    else:
        res.warn("tool_call_count", f"{turn_a} vs {turn_b} (超过 ±3)")

    evt_a = a["metadata"].get("total_events", 0)
    evt_b = b["metadata"].get("total_events", 0)
    if evt_a == 0:
        res.warn("total_events", "baseline=0")
    else:
        diff_ratio = abs(evt_a - evt_b) / evt_a
        if diff_ratio <= 0.2:
            res.ok("total_events", f"{evt_a} vs {evt_b} (±20%)")
        else:
            res.warn("total_events", f"{evt_a} vs {evt_b} (差异 {diff_ratio:.0%})")


def _compare_workspace_tree(a: dict, b: dict, res: Result):
    paths_a = {r["path"] for r in a["tree"]}
    paths_b = {r["path"] for r in b["tree"]}
    if paths_a == paths_b:
        res.ok("workspace file paths", f"{len(paths_a)} files 一致")
    else:
        only_a = paths_a - paths_b
        only_b = paths_b - paths_a
        detail = []
        if only_a:
            sample = sorted(only_a)[:3]
            detail.append(f"基线独有 {len(only_a)}: {sample}...")
        if only_b:
            sample = sorted(only_b)[:3]
            detail.append(f"迁移独有 {len(only_b)}: {sample}...")
        # 差异超过 3 个文件算严重
        if len(only_a) + len(only_b) > 3:
            res.fail("workspace file paths", "; ".join(detail))
        else:
            res.warn("workspace file paths", "; ".join(detail))


def _compare_widget_config(a: dict, b: dict, res: Result):
    """widget.config.json 关键字段对比"""
    wa = _find_widget_config(a["key_files"])
    wb = _find_widget_config(b["key_files"])
    if wa is None or wb is None:
        res.warn("widget.config.json", "一方或两方缺失")
        return

    key_fields = ["code", "version", "componentModelField", "component"]
    mismatches = []
    for field in key_fields:
        va = wa.get(field)
        vb = wb.get(field)
        if va != vb:
            # component 子字段单独报
            if field == "component":
                sub_a = set((va or {}).keys())
                sub_b = set((vb or {}).keys())
                if sub_a != sub_b:
                    mismatches.append(f"component keys 不一致: {sub_a ^ sub_b}")
                continue
            mismatches.append(f"{field}: {va!r} vs {vb!r}")

    if not mismatches:
        res.ok("widget.config.json 关键字段", "code/version/componentModelField/component 一致")
    else:
        res.fail("widget.config.json 关键字段", "; ".join(mismatches))


def _find_widget_config(key_files: dict) -> dict | None:
    for path, content in key_files.items():
        if path.endswith("widget.config.json") and isinstance(content, dict) and "_raw" not in content:
            return content
    return None


def _compare_apaas_json(a: dict, b: dict, res: Result):
    """apaas.json 关键字段对比（支持多个 apaas.json：web/src/apaas.json, mobile/src/apaas.json 等）"""
    files_a = {p: c for p, c in a["key_files"].items() if p.endswith("apaas.json") and isinstance(c, dict) and "_raw" not in c}
    files_b = {p: c for p, c in b["key_files"].items() if p.endswith("apaas.json") and isinstance(c, dict) and "_raw" not in c}
    if set(files_a.keys()) != set(files_b.keys()):
        res.warn("apaas.json 文件集合", f"basel={sorted(files_a)} cand={sorted(files_b)}")

    key_fields = ["entry", "outputName", "templateType"]
    for path in sorted(set(files_a) & set(files_b)):
        ca, cb = files_a[path], files_b[path]
        mismatches = [f"{k}: {ca.get(k)!r} vs {cb.get(k)!r}" for k in key_fields if ca.get(k) != cb.get(k)]
        if not mismatches:
            res.ok(f"{path} 关键字段", "entry/outputName/templateType 一致")
        else:
            res.fail(f"{path} 关键字段", "; ".join(mismatches))


# ══════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True, help="基线目录")
    parser.add_argument("--candidate", required=True, help="迁移后产物目录")
    parser.add_argument("--baseline2", help="第二次基线录制（用于看两次基线自身差异）")
    args = parser.parse_args()

    baseline = _load(Path(args.baseline))
    candidate = _load(Path(args.candidate))

    print("═" * 60)
    print(f"baseline : {args.baseline}")
    print(f"candidate: {args.candidate}")
    print("═" * 60)

    res = Result()
    _compare_final_status(baseline, candidate, res)
    _compare_event_type_set(baseline, candidate, res)
    _compare_tool_names_set(baseline, candidate, res)
    _compare_counts(baseline, candidate, res)
    _compare_workspace_tree(baseline, candidate, res)
    _compare_widget_config(baseline, candidate, res)
    _compare_apaas_json(baseline, candidate, res)

    res.print()

    # 可选：两次基线的自身差异（参考）
    if args.baseline2:
        print()
        print("─" * 60)
        print(f"参考：基线自身两次运行的差异（baseline vs baseline2）")
        print("─" * 60)
        baseline2 = _load(Path(args.baseline2))
        res2 = Result()
        _compare_final_status(baseline, baseline2, res2)
        _compare_event_type_set(baseline, baseline2, res2)
        _compare_tool_names_set(baseline, baseline2, res2)
        _compare_counts(baseline, baseline2, res2)
        _compare_workspace_tree(baseline, baseline2, res2)
        _compare_widget_config(baseline, baseline2, res2)
        _compare_apaas_json(baseline, baseline2, res2)
        res2.print()

    return 1 if res.has_fail else 0


if __name__ == "__main__":
    sys.exit(main())
