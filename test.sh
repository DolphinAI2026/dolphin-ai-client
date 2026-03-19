#!/bin/bash

echo "测试 aPaaS Builder AI 项目..."
echo ""

# 检查后端
echo "1. 检查后端文件..."
if [ -f "backend/app/main.py" ]; then
    echo "   ✓ 后端主文件存在"
else
    echo "   ✗ 后端主文件缺失"
    exit 1
fi

# 检查前端
echo "2. 检查前端文件..."
if [ -f "frontend/src/main.ts" ]; then
    echo "   ✓ 前端主文件存在"
else
    echo "   ✗ 前端主文件缺失"
    exit 1
fi

# 检查依赖
echo "3. 检查依赖..."
if [ -d "frontend/node_modules" ]; then
    echo "   ✓ 前端依赖已安装"
else
    echo "   ✗ 前端依赖未安装"
    exit 1
fi

if [ -d "backend/venv" ]; then
    echo "   ✓ 后端虚拟环境已创建"
else
    echo "   ✗ 后端虚拟环境未创建"
    exit 1
fi

# 检查配置
echo "4. 检查配置文件..."
if [ -f "backend/.env" ]; then
    echo "   ✓ 后端环境变量已配置"
else
    echo "   ✗ 后端环境变量未配置"
    exit 1
fi

echo ""
echo "✓ 所有检查通过！"
echo ""
echo "启动项目："
echo "  ./start.sh"
echo ""
echo "或手动启动："
echo "  后端: cd backend && source venv/bin/activate && python run.py"
echo "  前端: cd frontend && npm run dev"
