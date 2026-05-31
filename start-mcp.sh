#!/bin/bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
MCP_DIR="$ROOT_DIR/mcp-server"
BACKEND_DIR="$MCP_DIR/backend"
RUN_DIR="$ROOT_DIR/.run"
LOG_FILE="$RUN_DIR/mcp-server.log"
PID_FILE="$RUN_DIR/mcp-server.pid"

PYTHON_BIN="${PYTHON_BIN:-$HOME/.local/bin/python3.13}"
MCP_HOST="${MCP_HOST:-127.0.0.1}"
MCP_PORT="${MCP_PORT:-8004}"
DETACH_MODE="${1:-}"

mkdir -p "$RUN_DIR"

is_pid_running() {
    local pid_file="$1"
    [ -f "$pid_file" ] || return 1
    local pid
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    [ -n "$pid" ] || return 1
    kill -0 "$pid" 2>/dev/null
}

wait_for_http() {
    local url="$1"
    local attempts="${2:-30}"
    local i
    for ((i = 1; i <= attempts; i++)); do
        if curl -fsS "$url" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    echo "MCP server 启动失败，日志见: $LOG_FILE" >&2
    tail -n 80 "$LOG_FILE" 2>/dev/null || true
    return 1
}

if [ ! -d "$BACKEND_DIR" ]; then
    echo "未找到 MCP 服务目录: $BACKEND_DIR" >&2
    exit 1
fi

if [ ! -f "$BACKEND_DIR/.env" ] && [ -f "$BACKEND_DIR/.env.example" ]; then
    cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
    echo "已创建 $BACKEND_DIR/.env，请按环境补齐真实配置。"
fi

if [ ! -x "$PYTHON_BIN" ]; then
    echo "未找到 Python: $PYTHON_BIN" >&2
    exit 1
fi

if [ ! -x "$BACKEND_DIR/venv/bin/python" ]; then
    echo "创建 MCP 后端虚拟环境..."
    "$PYTHON_BIN" -m venv "$BACKEND_DIR/venv"
    "$BACKEND_DIR/venv/bin/python" -m pip install -r "$BACKEND_DIR/requirements.txt"
fi

if is_pid_running "$PID_FILE"; then
    echo "MCP server 已在运行，PID: $(cat "$PID_FILE")"
    exit 0
fi

if curl -fsS "http://$MCP_HOST:$MCP_PORT/api/health" >/dev/null 2>&1; then
    existing_pid="$(lsof -tiTCP:"$MCP_PORT" -sTCP:LISTEN 2>/dev/null | head -n 1 || true)"
    if [ -n "$existing_pid" ]; then
        echo "$existing_pid" >"$PID_FILE"
    fi
    echo "MCP server 已就绪: http://$MCP_HOST:$MCP_PORT"
    exit 0
fi

echo "启动 MCP server..."
cd "$BACKEND_DIR"
if [ "$DETACH_MODE" = "--daemon" ]; then
    nohup ./venv/bin/python -m uvicorn app.main:app --host "$MCP_HOST" --port "$MCP_PORT" >"$LOG_FILE" 2>&1 &
else
    ./venv/bin/python -m uvicorn app.main:app --host "$MCP_HOST" --port "$MCP_PORT" >"$LOG_FILE" 2>&1 &
fi
echo $! >"$PID_FILE"
cd "$ROOT_DIR"

wait_for_http "http://$MCP_HOST:$MCP_PORT/api/health" 45

echo "MCP server 已就绪："
echo "  Health: http://$MCP_HOST:$MCP_PORT/api/health"
echo "  Main:   http://$MCP_HOST:$MCP_PORT/api/mcp/mcp"
echo "  Design: http://$MCP_HOST:$MCP_PORT/api/mcp-design/mcp"
echo "  日志:   $LOG_FILE"
