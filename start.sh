#!/bin/bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
RUN_DIR="$ROOT_DIR/.run"
BACKEND_LOG="$RUN_DIR/backend.log"
FRONTEND_LOG="$RUN_DIR/frontend.log"
BACKEND_PID_FILE="$RUN_DIR/backend.pid"
FRONTEND_PID_FILE="$RUN_DIR/frontend.pid"

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

wait_for_http() {
    local url="$1"
    local name="$2"
    local attempts="${3:-30}"
    local i
    for ((i = 1; i <= attempts; i++)); do
        if curl -fsS "$url" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    echo "$name 启动失败，日志见: ${3:-}" >&2
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

    echo "启动后端服务..."
    cd "$BACKEND_DIR"
    if [ "$DETACH_MODE" = "--daemon" ]; then
        nohup ./venv/bin/python run.py >"$BACKEND_LOG" 2>&1 &
    else
        ./venv/bin/python run.py >"$BACKEND_LOG" 2>&1 &
    fi
    echo $! >"$BACKEND_PID_FILE"
    cd "$ROOT_DIR"

    if ! wait_for_http "http://127.0.0.1:8000/docs" "后端"; then
        echo "后端日志:"
        tail -n 80 "$BACKEND_LOG" || true
        exit 1
    fi
}

start_frontend() {
    if is_pid_running "$FRONTEND_PID_FILE"; then
        echo "前端已在运行，PID: $(cat "$FRONTEND_PID_FILE")"
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

    if ! wait_for_http "http://127.0.0.1:5173/ai-builder/" "前端"; then
        echo "前端日志:"
        tail -n 80 "$FRONTEND_LOG" || true
        exit 1
    fi
}

echo "启动 aPaaS Builder AI..."
ensure_mysql
ensure_backend_env
start_backend
start_frontend

echo
echo "服务已就绪："
echo "  前端: http://127.0.0.1:5173/ai-builder/"
echo "  后端: http://127.0.0.1:8000"
echo "  API文档: http://127.0.0.1:8000/docs"
echo "  后端日志: $BACKEND_LOG"
echo "  前端日志: $FRONTEND_LOG"
echo "  停止服务: ./stop.sh"

if [ "$DETACH_MODE" != "--daemon" ]; then
    echo
    echo "当前为前台守护模式，按 Ctrl+C 会自动停止前后端。"
    trap './stop.sh >/dev/null 2>&1 || true; exit' INT TERM EXIT
    wait
fi
