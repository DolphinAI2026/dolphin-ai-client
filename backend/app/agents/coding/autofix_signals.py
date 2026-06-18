"""C5 AutoFix 信号收集器（纯函数，无副作用）。

把三类失败信号归一成字符串列表，再渲染成喂给 CodingAgent 的 fix_hint。
- build：WorkspaceManager.build_project 返回 dict（status/message）
- console：BrowserService.get_console_logs（level/text/location）
- network：BrowserService.get_network_requests（status>=400 或 failed，C2 已过滤）

signals_signature 用于「同一报错重复出现即停」的判定（顺序无关、稳定 hash）。
"""
from __future__ import annotations

import hashlib

# 视为运行时错误的 console level（pageerror 由 C2 以 level="pageerror" 投递）
_ERROR_CONSOLE_LEVELS = {"error", "pageerror"}


def collect_build_errors(build_result: dict) -> list[str]:
    """从 build_project 返回 dict 抠错误信息。status != 'ok' 即视为失败。"""
    if not build_result:
        return []
    if build_result.get("status") == "ok":
        return []
    msg = str(build_result.get("message") or "").strip()
    return [msg] if msg else ["构建失败（无错误信息）"]


def collect_runtime_errors(
    console_logs: list[dict],
    network_requests: list[dict],
) -> list[str]:
    """从 C2 抓到的 console / network 列表里挑出失败信号。

    - console.error / pageerror → 文本（带 location）
    - network：C2 已只投递 status>=400 与 failed，这里全部计入
    """
    errors: list[str] = []
    for entry in console_logs or []:
        level = str(entry.get("level") or "").lower()
        if level not in _ERROR_CONSOLE_LEVELS:
            continue
        text = str(entry.get("text") or "").strip()
        if not text:
            continue
        location = str(entry.get("location") or "").strip()
        tag = "pageerror" if level == "pageerror" else "console.error"
        errors.append(f"[{tag}] {text}" + (f" ({location})" if location else ""))

    for req in network_requests or []:
        method = str(req.get("method") or "").strip() or "GET"
        url = str(req.get("url") or "").strip()
        if req.get("failed"):
            errors.append(f"[network failed] {method} {url}")
        else:
            status = int(req.get("status") or 0)
            errors.append(f"[network {status}] {method} {url}")
    return errors


def build_fix_hint(build_errors: list[str], runtime_errors: list[str]) -> str:
    """渲染成 CodingAgent build_initial_user_message 期望的 fix_hint markdown。

    返回空字符串表示「没有任何失败信号」（driver 据此判定本轮干净、停止）。
    """
    if not build_errors and not runtime_errors:
        return ""
    parts: list[str] = ["**本轮验收发现以下问题，请针对性修复：**\n"]
    if build_errors:
        parts.append("### 构建报错")
        parts.extend(f"- {e}" for e in build_errors)
    if runtime_errors:
        parts.append("### 运行时报错（console.error / pageerror / network）")
        parts.extend(f"- {e}" for e in runtime_errors)
    return "\n".join(parts)


def signals_signature(build_errors: list[str], runtime_errors: list[str]) -> str:
    """顺序无关的稳定指纹，用于「同一报错重复出现」判定。"""
    payload = "\n".join(sorted(build_errors) + ["::"] + sorted(runtime_errors))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
