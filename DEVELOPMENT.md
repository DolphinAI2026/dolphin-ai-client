# 开发指南

## 项目结构

```
apaas-builder-ai/
├── backend/                 # FastAPI后端
│   ├── app/
│   │   ├── routes/         # API路由
│   │   │   ├── auth.py     # 认证（注册/登录）
│   │   │   ├── conversations.py  # 对话管理
│   │   │   ├── chat.py     # 聊天（SSE流式）
│   │   │   └── applications.py   # 应用管理
│   │   ├── config.py       # 配置管理
│   │   ├── database.py     # 数据库连接
│   │   ├── models.py       # 数据模型
│   │   ├── schemas.py      # Pydantic schemas
│   │   ├── auth.py         # JWT认证
│   │   ├── apaas_client.py # 得帆云API客户端
│   │   └── llm_client.py   # LLM客户端
│   ├── requirements.txt
│   ├── .env               # 环境变量（已配置）
│   └── run.py             # 启动脚本
├── frontend/              # Vue 3前端
│   ├── src/
│   │   ├── api/          # API客户端
│   │   ├── stores/       # Pinia状态管理
│   │   ├── router/       # Vue Router
│   │   ├── views/        # 页面组件
│   │   ├── types/        # TypeScript类型
│   │   └── utils/        # 工具函数
│   ├── vite.config.ts    # Vite配置（已配置代理）
│   └── package.json
├── start.sh              # 一键启动脚本
└── README.md
```

## 快速开始

### 方式1：使用启动脚本（推荐）

```bash
./start.sh
```

### 方式2：手动启动

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
npm install  # 已完成
npm run dev
```

## 访问地址

- 前端：http://localhost:5173
- 后端：http://localhost:8000
- API文档：http://localhost:8000/docs

## 数据库

使用SQLite，数据库文件：`backend/apaas_builder.db`（首次运行自动创建）

### 数据表

- `users` - 用户表
- `conversations` - 对话表
- `messages` - 消息表
- `applications` - 应用表

## API端点

### 认证
- `POST /api/auth/register` - 注册
- `POST /api/auth/login` - 登录
- `GET /api/auth/me` - 获取当前用户

### 对话
- `POST /api/conversations` - 创建对话
- `GET /api/conversations` - 对话列表
- `GET /api/conversations/{id}` - 对话详情

### 聊天
- `POST /api/chat/send` - 发送消息（SSE流式响应）

### 应用
- `GET /api/applications` - 应用列表

## 环境变量

后端环境变量已配置在 `backend/.env`：

```env
# aPaaS Platform
APAAS_BASE_URL=https://apaas-poc.definesys.cn/backend
APAAS_TENANT_ID=743906758237356033

# LLM Configuration
LLM_API_BASE=https://api.jiekou.ai/openai
LLM_API_KEY=sk_PRw1U5P4FO8Ep_P4aqCn231Uq2jXvB4YXzNccYwT6Jg
LLM_MODEL=claude-haiku-4-5-20251001

# Database
DATABASE_URL=sqlite+aiosqlite:///./apaas_builder.db

# JWT
JWT_SECRET_KEY=STJNDwwzapqfloz3ccjpamqRXjeLJRhj3l-6-6rozGg
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=1440
```

## 技术栈

### 后端
- FastAPI - Web框架
- SQLAlchemy 2.0 - ORM（异步）
- Pydantic v2 - 数据验证
- JWT - 认证
- SSE - 流式响应
- httpx - HTTP客户端

### 前端
- Vue 3 - 框架
- TypeScript - 类型系统
- Vite - 构建工具
- Element Plus - UI组件库
- Pinia - 状态管理
- Vue Router - 路由
- Axios - HTTP客户端

## 开发流程

### 1. 首次使用

1. 启动服务：`./start.sh`
2. 访问前端：http://localhost:5173
3. 注册账号（首次使用）
4. 登录系统

### 2. 创建对话

1. 点击"新建对话"
2. 选择智能体类型：
   - 搭建智能体：用于应用搭建
   - 辅助开发：用于辅助开发
   - 复杂开发：用于复杂开发
3. 开始对话

### 3. 聊天交互

- 输入消息，按Enter或点击"发送"
- AI回复采用流式输出
- 对话历史自动保存

## 下一步开发

### Week 1-2：核心功能
- [x] 项目框架搭建
- [x] 用户认证系统
- [x] 对话管理
- [x] 基础聊天功能
- [ ] 得帆云登录集成（RSA加密）
- [ ] 需求收集流程
- [ ] 配置预览面板（5个tab）
- [ ] 调用得帆云智能搭建API
- [ ] 生成进度展示

### Week 3-4：辅助功能
- [ ] 辅助开发智能体
- [ ] 应用管理页面
- [ ] 需求模板库
- [ ] 错误处理与重试

## 调试

### 后端日志
后端使用uvicorn的日志输出，可以在终端查看请求日志。

### 前端调试
使用浏览器开发者工具：
- Network：查看API请求
- Console：查看日志输出
- Vue DevTools：查看组件状态

### 数据库查看
```bash
cd backend
sqlite3 apaas_builder.db
.tables
SELECT * FROM users;
```

## 常见问题

### 1. 端口被占用
修改配置：
- 后端：`backend/.env` 中的 `PORT`
- 前端：`frontend/vite.config.ts` 中的 `server.port`

### 2. 依赖安装失败
```bash
# 后端
cd backend
pip install --upgrade pip
pip install -r requirements.txt

# 前端
cd frontend
rm -rf node_modules package-lock.json
npm install
```

### 3. 数据库错误
删除数据库文件重新初始化：
```bash
rm backend/apaas_builder.db
# 重启后端服务
```
