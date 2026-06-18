"""C5 AutoFix 信号收集器 —— 纯函数单测（不起进程、不连 LLM）。"""
from __future__ import annotations

from app.agents.coding.autofix_signals import (
    build_fix_hint,
    collect_build_errors,
    collect_runtime_errors,
    signals_signature,
)


def test_collect_build_errors_extracts_message_on_error():
    result = {"status": "error", "message": "web/ 构建失败: Module not found: ./foo.vue"}
    errs = collect_build_errors(result)
    assert errs == ["web/ 构建失败: Module not found: ./foo.vue"]


def test_collect_build_errors_empty_on_ok():
    assert collect_build_errors({"status": "ok", "message": "构建成功"}) == []


def test_collect_runtime_errors_filters_console_error_and_pageerror():
    console = [
        {"seq": 1, "level": "log", "text": "hello", "location": ""},
        {"seq": 2, "level": "error", "text": "x is not a function", "location": "edit.vue:10"},
        {"seq": 3, "level": "pageerror", "text": "Uncaught TypeError: y", "location": ""},
        {"seq": 4, "level": "warning", "text": "deprecated", "location": ""},
    ]
    errs = collect_runtime_errors(console, [])
    assert errs == [
        "[console.error] x is not a function (edit.vue:10)",
        "[pageerror] Uncaught TypeError: y",
    ]


def test_collect_runtime_errors_includes_network_failures():
    network = [
        {"seq": 1, "url": "http://127.0.0.1:8080/api/x", "status": 500, "method": "GET", "failed": False},
        {"seq": 2, "url": "http://127.0.0.1:8080/api/y", "status": 0, "method": "POST", "failed": True},
    ]
    errs = collect_runtime_errors([], network)
    assert errs == [
        "[network 500] GET http://127.0.0.1:8080/api/x",
        "[network failed] POST http://127.0.0.1:8080/api/y",
    ]


def test_build_fix_hint_renders_sections():
    hint = build_fix_hint(["build boom"], ["[console.error] runtime boom"])
    assert "构建报错" in hint
    assert "build boom" in hint
    assert "运行时报错" in hint
    assert "runtime boom" in hint


def test_build_fix_hint_empty_when_no_signals():
    assert build_fix_hint([], []) == ""


def test_signals_signature_stable_and_order_independent():
    sig_a = signals_signature(["e1", "e2"], ["r1"])
    sig_b = signals_signature(["e2", "e1"], ["r1"])
    sig_c = signals_signature(["e1"], ["r1"])
    assert sig_a == sig_b
    assert sig_a != sig_c
