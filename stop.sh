#!/bin/bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUN_DIR="$ROOT_DIR/.run"
CODE_SERVER_PID_FILE="$RUN_DIR/code-server.pid"
CODE_SERVER_PORT="${CODE_SERVER_PORT:-8080}"

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

stop_code_server_port() {
    local pids
    pids="$(lsof -tiTCP:"$CODE_SERVER_PORT" -sTCP:LISTEN 2>/dev/null || true)"
    if [ -z "$pids" ]; then
        return 0
    fi

    local pid
    while IFS= read -r pid; do
        [ -n "$pid" ] || continue
        local command
        command="$(ps -p "$pid" -o command= 2>/dev/null || true)"
        if [[ "$command" == *"code-server"* ]]; then
            kill "$pid" 2>/dev/null || true
            echo "已停止 code-server 监听进程 (PID: $pid)"
        else
            echo "端口 $CODE_SERVER_PORT 被非 code-server 进程占用，跳过: $pid"
        fi
    done <<<"$pids"
}

stop_launchctl_job "后端" "codex.apaas-builder-ai.backend"
stop_launchctl_job "前端" "codex.apaas-builder-ai.frontend"
stop_launchctl_job "code-server" "codex.apaas-builder-ai.code-server"
stop_pid "后端" "$RUN_DIR/backend.pid"
stop_pid "前端" "$RUN_DIR/frontend.pid"
stop_pid "code-server" "$CODE_SERVER_PID_FILE"
stop_code_server_port
