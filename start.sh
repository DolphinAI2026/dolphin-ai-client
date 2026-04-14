#!/bin/bash

echo "启动 aPaaS Builder AI..."

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
MAIN_DB_URL="sqlite+aiosqlite:///$BACKEND_DIR/apaas_builder.db"

# 启动后端
echo "启动后端服务..."
cd "$BACKEND_DIR"
source venv/bin/activate 2>/dev/null || python3 -m venv venv && source venv/bin/activate
python3 -m pip install -q -r requirements.txt
DATABASE_URL="$MAIN_DB_URL" python3 run.py &
BACKEND_PID=$!

# 等待后端启动
sleep 3

# 启动前端
echo "启动前端服务..."
cd "$FRONTEND_DIR"
npm run dev &
FRONTEND_PID=$!

echo ""
echo "服务已启动："
echo "  后端: http://localhost:8000"
echo "  前端: http://localhost:5173"
echo "  API文档: http://localhost:8000/docs"
echo ""
echo "按 Ctrl+C 停止所有服务"

# 等待用户中断
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM

wait
