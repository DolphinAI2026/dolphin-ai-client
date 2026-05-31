#!/bin/bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUN_DIR="$ROOT_DIR/.run"
PID_FILE="$RUN_DIR/mcp-server.pid"
MCP_PORT="${MCP_PORT:-8004}"

if [ -f "$PID_FILE" ]; then
    pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        kill "$pid"
        echo "已停止 MCP server (PID: $pid)"
    else
        echo "MCP server 未运行"
    fi
    rm -f "$PID_FILE"
fi

pids="$(lsof -tiTCP:"$MCP_PORT" -sTCP:LISTEN 2>/dev/null || true)"
if [ -n "$pids" ]; then
    while IFS= read -r pid; do
        [ -n "$pid" ] || continue
        command="$(ps -p "$pid" -o command= 2>/dev/null || true)"
        if [[ "$command" == *"uvicorn"* && "$command" == *"app.main:app"* ]]; then
            kill "$pid" 2>/dev/null || true
            echo "已停止 MCP server 监听进程 (PID: $pid)"
        fi
    done <<<"$pids"
fi
