# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

aPaaS Builder AI - 得帆云低代码平台智能搭建助手。通过对话式交互帮助用户在得帆云平台上快速搭建应用。

## Development Commands

### Quick Start
```bash
./start.sh  # 一键启动前后端
```

### Backend (Python/FastAPI)
```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python run.py  # 启动于 http://localhost:8000
```

### Frontend (Vue 3/TypeScript)
```bash
cd frontend
npm install
npm run dev      # 开发服务器 http://localhost:5173
npm run build    # 生产构建
```

### Database
SQLite 数据库位于 `backend/apaas_builder.db`，首次运行自动创建。
```bash
sqlite3 backend/apaas_builder.db  # 查看数据
```

## Architecture

### Backend (`backend/app/`)
- **main.py**: FastAPI 入口，CORS 配置，路由注册
- **routes/**: API 路由
  - `auth.py` - JWT 认证（注册/登录）
  - `chat.py` - SSE 流式聊天
  - `conversations.py` - 对话管理
  - `applications.py` - 应用管理
  - `apaas.py` - 得帆云平台代理
  - `generation_steps.py` - 生成步骤
- **apaas_client.py**: 得帆云 API 客户端，RSA 加密登录，应用/模型/字典/表单 CRUD
- **llm_client.py**: OpenAI 兼容 LLM 客户端（支持流式/非流式）
- **database.py**: SQLAlchemy 2.0 异步配置
- **models/**: SQLAlchemy 模型
- **schemas.py**: Pydantic v2 数据验证
- **skills/**: 平台能力封装（组件/编排/平台操作）

### Frontend (`frontend/src/`)
- **views/**: 页面组件（Login, ChatPage, Apps, Generate）
- **stores/**: Pinia 状态管理（user, preview）
- **api/**: Axios API 客户端
- **types/**: TypeScript 类型定义
- **router/**: Vue Router 配置

### Skills (`skills/`)
平台原子能力文档集合，定义 30 个 Skills：
- 14 个平台操作（create/query/update app/model/dict/role/form）
- 16 个表单组件（text/number/select/date/file/son-table 等）

## Key Patterns

### APaaS Client Authentication
得帆云使用 RSA PKCS1v15 加密密码登录，公钥硬编码在 `apaas_client.py`。
所有 API 请求需携带 headers: `xdaptoken`, `xdaptenantid`, `xdaptimestamp`, `appid`。

### SSE Streaming
聊天使用 Server-Sent Events 流式响应，前端通过 EventSource 或 fetch + ReadableStream 接收。

### Code Generation
模型/字典/表单编码建议添加随机后缀避免冲突：
```python
suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
model_code = f"customer_{suffix}"  # customer_a1b2
```

### Reserved Words
字段编码避免数据库保留字（name, status, type, order, level, date, user, id 等），使用 `f_` 前缀解决。

## Environment Variables

配置在 `backend/.env`：
- `APAAS_BASE_URL` / `APAAS_TENANT_ID` - 得帆云平台
- `LLM_API_BASE` / `LLM_API_KEY` / `LLM_MODEL` - LLM 配置
- `DATABASE_URL` - SQLite 连接
- `JWT_SECRET_KEY` - JWT 密钥

## API Endpoints

- `POST /api/auth/register|login` - 认证
- `GET /api/auth/me` - 当前用户
- `POST /api/chat/send` - SSE 流式聊天
- `GET|POST /api/conversations` - 对话管理
- `GET /api/applications` - 应用列表
- `GET /api/health` - 健康检查
- API 文档: http://localhost:8000/docs
