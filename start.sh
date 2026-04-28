#!/bin/bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
RUN_DIR="$ROOT_DIR/.run"
BACKEND_LOG="$RUN_DIR/backend.log"
FRONTEND_LOG="$RUN_DIR/frontend.log"
CODE_SERVER_LOG="$RUN_DIR/code-server.log"
BACKEND_PID_FILE="$RUN_DIR/backend.pid"
FRONTEND_PID_FILE="$RUN_DIR/frontend.pid"
CODE_SERVER_PID_FILE="$RUN_DIR/code-server.pid"

MYSQL_HOME="${MYSQL_HOME:-$HOME/mysql}"
MYSQL_BIN="$MYSQL_HOME/bin/mysql"
MYSQLD_BIN="$MYSQL_HOME/bin/mysqld"
MYSQL_SOCKET="${MYSQL_SOCKET:-/tmp/mysql.sock}"
MYSQL_HOST="${MYSQL_HOST:-127.0.0.1}"
MYSQL_PORT="${MYSQL_PORT:-3306}"
MYSQL_USER="${MYSQL_USER:-apaas}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:-apaas2024}"
MYSQL_DATABASE="${MYSQL_DATABASE:-apaas_builder}"

PYTHON_BIN="${PYTHON_BIN:-$HOME/.local/bin/python3.13}"
CODE_SERVER_BIN="${CODE_SERVER_BIN:-$HOME/.local/bin/code-server}"
CODE_SERVER_HOST="${CODE_SERVER_HOST:-127.0.0.1}"
CODE_SERVER_PORT="${CODE_SERVER_PORT:-8080}"
CODE_SERVER_URL="${CODE_SERVER_URL:-http://$CODE_SERVER_HOST:$CODE_SERVER_PORT}"
CODE_SERVER_LAUNCHCTL_LABEL="${CODE_SERVER_LAUNCHCTL_LABEL:-codex.apaas-builder-ai.code-server}"
DETACH_MODE="${1:-}"

mkdir -p "$RUN_DIR"

require_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "缺少命令: $1" >&2
        exit 1
    fi
}

is_pid_running() {
    local pid_file="$1"
    [ -f "$pid_file" ] || return 1
    local pid
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    [ -n "$pid" ] || return 1
    kill -0 "$pid" 2>/dev/null
}

shell_quote() {
    printf "%q" "$1"
}

wait_for_http() {
    local url="$1"
    local name="$2"
    local attempts="${3:-30}"
    local log_path="${4:-}"
    local i
    for ((i = 1; i <= attempts; i++)); do
        if curl -fsS "$url" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    if [ -n "$log_path" ]; then
        echo "$name 启动失败，日志见: $log_path" >&2
    else
        echo "$name 启动失败" >&2
    fi
    return 1
}

ensure_mysql() {
    if "$MYSQL_BIN" --protocol=TCP -h"$MYSQL_HOST" -P"$MYSQL_PORT" -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" \
        -e "SELECT 1" >/dev/null 2>&1; then
        echo "MySQL 已就绪: $MYSQL_HOST:$MYSQL_PORT/$MYSQL_DATABASE"
        return 0
    fi

    if [ ! -x "$MYSQLD_BIN" ] || [ ! -x "$MYSQL_BIN" ]; then
        echo "未找到本地 MySQL: $MYSQL_HOME" >&2
        exit 1
    fi

    echo "启动本地 MySQL..."
    "$MYSQLD_BIN" \
        --user="$(whoami)" \
        --basedir="$MYSQL_HOME" \
        --datadir="$MYSQL_HOME/data" \
        --port="$MYSQL_PORT" \
        --socket="$MYSQL_SOCKET" \
        --log-error="$MYSQL_HOME/log/error.log" \
        --daemonize

    local i
    for ((i = 1; i <= 20; i++)); do
        if "$MYSQL_BIN" --protocol=TCP -h"$MYSQL_HOST" -P"$MYSQL_PORT" -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" \
            -e "SELECT 1" >/dev/null 2>&1; then
            echo "MySQL 启动完成"
            return 0
        fi
        sleep 1
    done

    echo "MySQL 启动失败，请查看 $MYSQL_HOME/log/error.log" >&2
    exit 1
}

ensure_backend_env() {
    if [ ! -x "$PYTHON_BIN" ]; then
        echo "未找到 Python 3.13: $PYTHON_BIN" >&2
        exit 1
    fi

    require_cmd npm
    require_cmd curl

    local venv_python="$BACKEND_DIR/venv/bin/python"
    local recreate_venv="false"

    if [ ! -x "$venv_python" ]; then
        recreate_venv="true"
    elif ! "$venv_python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
        recreate_venv="true"
    fi

    if [ "$recreate_venv" = "true" ]; then
        echo "重建后端虚拟环境..."
        rm -rf "$BACKEND_DIR/venv"
        "$PYTHON_BIN" -m venv "$BACKEND_DIR/venv"
        "$venv_python" -m pip install -r "$BACKEND_DIR/requirements.txt"
    fi

    if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
        echo "安装前端依赖..."
        (cd "$FRONTEND_DIR" && npm install)
    fi
}

start_backend() {
    if is_pid_running "$BACKEND_PID_FILE"; then
        echo "后端已在运行，PID: $(cat "$BACKEND_PID_FILE")"
        return 0
    fi

    if curl -fsS "http://127.0.0.1:8000/docs" >/dev/null 2>&1; then
        local existing_pid
        existing_pid="$(lsof -tiTCP:8000 -sTCP:LISTEN 2>/dev/null | head -n 1 || true)"
        if [ -n "$existing_pid" ]; then
            echo "$existing_pid" >"$BACKEND_PID_FILE"
            echo "后端已就绪，PID: $existing_pid"
        else
            echo "后端已就绪"
        fi
        return 0
    fi

    echo "启动后端服务..."
    cd "$BACKEND_DIR"
    if [ "$DETACH_MODE" = "--daemon" ]; then
        nohup ./venv/bin/python run.py >"$BACKEND_LOG" 2>&1 &
    else
        ./venv/bin/python run.py >"$BACKEND_LOG" 2>&1 &
    fi
    echo $! >"$BACKEND_PID_FILE"
    cd "$ROOT_DIR"

    if ! wait_for_http "http://127.0.0.1:8000/docs" "后端" 30 "$BACKEND_LOG"; then
        echo "后端日志:"
        tail -n 80 "$BACKEND_LOG" || true
        exit 1
    fi

    local listener_pid
    listener_pid="$(lsof -tiTCP:8000 -sTCP:LISTEN 2>/dev/null | head -n 1 || true)"
    if [ -n "$listener_pid" ]; then
        echo "$listener_pid" >"$BACKEND_PID_FILE"
    fi
}

start_frontend() {
    if is_pid_running "$FRONTEND_PID_FILE"; then
        echo "前端已在运行，PID: $(cat "$FRONTEND_PID_FILE")"
        return 0
    fi

    if curl -fsS "http://127.0.0.1:5173/ai-builder/" >/dev/null 2>&1; then
        local existing_pid
        existing_pid="$(lsof -tiTCP:5173 -sTCP:LISTEN 2>/dev/null | head -n 1 || true)"
        if [ -n "$existing_pid" ]; then
            echo "$existing_pid" >"$FRONTEND_PID_FILE"
            echo "前端已就绪，PID: $existing_pid"
        else
            echo "前端已就绪"
        fi
        return 0
    fi

    echo "启动前端服务..."
    cd "$FRONTEND_DIR"
    if [ "$DETACH_MODE" = "--daemon" ]; then
        nohup npm run dev >"$FRONTEND_LOG" 2>&1 &
    else
        npm run dev >"$FRONTEND_LOG" 2>&1 &
    fi
    echo $! >"$FRONTEND_PID_FILE"
    cd "$ROOT_DIR"

    if ! wait_for_http "http://127.0.0.1:5173/ai-builder/" "前端" 30 "$FRONTEND_LOG"; then
        echo "前端日志:"
        tail -n 80 "$FRONTEND_LOG" || true
        exit 1
    fi

    local listener_pid
    listener_pid="$(lsof -tiTCP:5173 -sTCP:LISTEN 2>/dev/null | head -n 1 || true)"
    if [ -n "$listener_pid" ]; then
        echo "$listener_pid" >"$FRONTEND_PID_FILE"
    fi
}

start_code_server() {
    if is_pid_running "$CODE_SERVER_PID_FILE"; then
        echo "code-server 已在运行，PID: $(cat "$CODE_SERVER_PID_FILE")"
        return 0
    fi

    if curl -fsS "$CODE_SERVER_URL" >/dev/null 2>&1; then
        local existing_pid
        existing_pid="$(lsof -tiTCP:"$CODE_SERVER_PORT" -sTCP:LISTEN 2>/dev/null | head -n 1 || true)"
        if [ -n "$existing_pid" ]; then
            echo "$existing_pid" >"$CODE_SERVER_PID_FILE"
            echo "code-server 已就绪: $CODE_SERVER_URL，PID: $existing_pid"
        else
            echo "code-server 已就绪: $CODE_SERVER_URL"
        fi
        return 0
    fi

    if [ ! -x "$CODE_SERVER_BIN" ]; then
        echo "未找到 code-server: $CODE_SERVER_BIN" >&2
        exit 1
    fi

    echo "启动 code-server..."
    if [ "$DETACH_MODE" = "--daemon" ]; then
        if command -v launchctl >/dev/null 2>&1; then
            if launchctl print "gui/$(id -u)/$CODE_SERVER_LAUNCHCTL_LABEL" >/dev/null 2>&1; then
                launchctl remove "$CODE_SERVER_LAUNCHCTL_LABEL" >/dev/null 2>&1 || true
            fi
            local command
            command="exec $(shell_quote "$CODE_SERVER_BIN") --bind-addr $(shell_quote "$CODE_SERVER_HOST:$CODE_SERVER_PORT") --auth none >> $(shell_quote "$CODE_SERVER_LOG") 2>&1"
            launchctl submit -l "$CODE_SERVER_LAUNCHCTL_LABEL" -- /bin/zsh -lc "$command"
        else
            nohup "$CODE_SERVER_BIN" --bind-addr "$CODE_SERVER_HOST:$CODE_SERVER_PORT" --auth none >"$CODE_SERVER_LOG" 2>&1 &
            echo $! >"$CODE_SERVER_PID_FILE"
        fi
    else
        "$CODE_SERVER_BIN" --bind-addr "$CODE_SERVER_HOST:$CODE_SERVER_PORT" --auth none >"$CODE_SERVER_LOG" 2>&1 &
        echo $! >"$CODE_SERVER_PID_FILE"
    fi

    if ! wait_for_http "$CODE_SERVER_URL" "code-server" 30 "$CODE_SERVER_LOG"; then
        echo "code-server 日志:"
        tail -n 80 "$CODE_SERVER_LOG" || true
        exit 1
    fi

    local listener_pid
    listener_pid="$(lsof -tiTCP:"$CODE_SERVER_PORT" -sTCP:LISTEN 2>/dev/null | head -n 1 || true)"
    if [ -n "$listener_pid" ]; then
        echo "$listener_pid" >"$CODE_SERVER_PID_FILE"
    fi
}

echo "启动 aPaaS Builder AI..."
ensure_mysql
ensure_backend_env
start_code_server
start_backend
start_frontend

echo
echo "服务已就绪："
echo "  前端: http://127.0.0.1:5173/ai-builder/"
echo "  后端: http://127.0.0.1:8000"
echo "  Web IDE: $CODE_SERVER_URL"
echo "  API文档: http://127.0.0.1:8000/docs"
echo "  后端日志: $BACKEND_LOG"
echo "  前端日志: $FRONTEND_LOG"
echo "  Web IDE 日志: $CODE_SERVER_LOG"
echo "  停止服务: ./stop.sh"

if [ "$DETACH_MODE" != "--daemon" ]; then
    echo
    echo "当前为前台守护模式，按 Ctrl+C 会自动停止前后端。"
    trap './stop.sh >/dev/null 2>&1 || true; exit' INT TERM EXIT
    wait
fi
