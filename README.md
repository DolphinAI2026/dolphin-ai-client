# aPaaS Builder AI

得帆云低代码平台的智能搭建助手 - 通过对话式交互帮助用户快速搭建应用

## ✨ 特性

- 🤖 三个智能体：搭建智能体、辅助开发、复杂开发
- 💬 多轮对话需求收集
- 📊 实时配置预览（模型/表单/流程/权限）
- 🚀 一键生成应用
- 📡 SSE流式响应
- 🔐 JWT认证

## 🚀 快速开始

### 一键启动（推荐）

```bash
./start.sh
```

### 手动启动

**后端：**
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python run.py
```

**前端：**
```bash
cd frontend
npm install
npm run dev
```

## 📦 访问地址

- 前端：http://localhost:5173
- 后端：http://localhost:8000
- API文档：http://localhost:8000/docs

## 🏗️ 项目结构

```
apaas-builder-ai/
├── backend/          # FastAPI后端
│   ├── app/
│   │   ├── routes/   # API路由（auth/conversations/chat/applications）
│   │   ├── config.py # 配置管理
│   │   ├── database.py # 数据库（SQLite + SQLAlchemy）
│   │   ├── models.py # 数据模型（User/Conversation/Message/Application）
│   │   ├── schemas.py # Pydantic schemas
│   │   ├── auth.py   # JWT认证
│   │   ├── apaas_client.py # 得帆云API客户端
│   │   └── llm_client.py # LLM客户端（OpenAI兼容）
│   ├── requirements.txt
│   ├── .env         # 环境变量（已配置）
│   └── run.py
└── frontend/        # Vue 3前端
    ├── src/
    │   ├── api/     # API客户端
    │   ├── stores/  # Pinia状态管理
    │   ├── router/  # Vue Router
    │   ├── views/   # 页面组件（Login/Home/Chat）
    │   ├── types/   # TypeScript类型
    │   └── utils/   # 工具函数
    ├── vite.config.ts
    └── package.json
```

## 🛠️ 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | Vue 3 + TypeScript + Vite + Element Plus + Pinia + Vue Router |
| 后端 | FastAPI + SQLAlchemy 2.0 (async) + Pydantic v2 |
| 数据库 | SQLite + aiosqlite |
| 认证 | JWT (HS256) |
| LLM | OpenAI兼容API (claude-haiku-4-5) |
| 流式 | SSE (Server-Sent Events) |

## 📖 使用指南

1. 启动服务后访问 http://localhost:5173
2. 注册/登录账号
3. 点击"新建对话"，选择智能体类型
4. 开始对话，描述你的应用需求
5. AI会引导你完善需求，并生成配置预览
6. 确认后点击"开始生成"，调用得帆云API创建应用

## 🔧 环境配置

环境变量请在本地 `backend/.env` 配置，仓库只保留占位示例：

```env
# aPaaS Platform
APAAS_BASE_URL=https://your-apaas.example.com/backend
APAAS_TENANT_ID=<your-tenant-id>

# LLM Configuration
LLM_API_BASE=https://your-llm-gateway.example.com/openai
LLM_API_KEY=<your-llm-api-key>
LLM_MODEL=<your-model-name>

# Database
DATABASE_URL=sqlite+aiosqlite:///./apaas_builder.db

# JWT
JWT_SECRET_KEY=<generate-a-long-random-secret>
```

## 📚 开发文档

详细开发指南请查看 [DEVELOPMENT.md](DEVELOPMENT.md)

## MCP 服务

独立 MCP 服务在单独仓库 [`apaas-builder-mcp-server`](https://github.com/Mars-hub404/apaas-builder-mcp-server) 维护并部署（k8s，端口 `8004`），不再随本仓库 vendoring。主后端通过 bridge 调用它（默认 `http://127.0.0.1:8004/api/mcp/mcp`；未启动时优雅降级，Builder 核心工具不受影响）。需要本地联调时，克隆该仓库按其 README 启动 8004 即可，或用 `MCP_V2_INTERNAL_BASE` 指向已有的 MCP 服务。

## 🗺️ 开发计划

### Week 1-2：核心框架 + 搭建智能体
- [x] 前后端项目搭建
- [x] 用户认证系统
- [x] 对话管理
- [x] 基础聊天功能（SSE流式）
- [ ] 得帆云登录认证集成（RSA加密）
- [ ] 多轮对话 + 需求收集
- [ ] 调用得帆云API生成应用
- [ ] 右侧配置预览面板（5个tab）

### Week 3-4：辅助开发 + 应用管理
- [ ] 辅助开发智能体
- [ ] 应用管理页面
- [ ] 需求模板库
- [ ] 错误处理与重试

## 📄 License

MIT
