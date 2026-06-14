#!/bin/bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUN_DIR="$ROOT_DIR/.run"

stop_launchctl_job() {
    local name="$1"
    local label="$2"

    if launchctl print "gui/$(id -u)/$label" >/dev/null 2>&1; then
        launchctl remove "$label" >/dev/null 2>&1 || true
        echo "已停止 $name ($label)"
    fi
}

stop_pid() {
    local name="$1"
    local pid_file="$2"

    if [ ! -f "$pid_file" ]; then
        echo "$name 未记录 PID"
        return 0
    fi

    local pid
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        kill "$pid"
        echo "已停止 $name (PID: $pid)"
    else
        echo "$name 未运行"
    fi
    rm -f "$pid_file"
}

stop_launchctl_job "后端" "codex.apaas-builder-ai.backend"
stop_launchctl_job "前端" "codex.apaas-builder-ai.frontend"
stop_pid "后端" "$RUN_DIR/backend.pid"
stop_pid "前端" "$RUN_DIR/frontend.pid"
