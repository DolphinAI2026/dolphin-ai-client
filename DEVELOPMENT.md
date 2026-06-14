# 开发指南

## 项目结构

```
apaas-builder-ai/
├── backend/           # Python FastAPI 后端
│   ├── app/
│   │   ├── routes/    # API 路由
│   │   ├── coding/    # AI Coding 核心（workspace、agent）
│   │   ├── config.py  # 配置管理
│   │   ├── models.py  # 数据模型
│   │   └── ...
│   ├── venv/          # Python 虚拟环境（gitignored）
│   ├── run.py         # 启动入口
│   ├── requirements.txt
│   └── tests/         # 后端测试用例
├── frontend/          # Vue 3 + TypeScript 前端
│   ├── src/
│   │   ├── api/       # API 客户端
│   │   ├── stores/    # Pinia 状态管理
│   │   ├── views/     # 页面组件
│   │   ├── router/    # Vue Router
│   │   └── utils/     # 工具函数
│   ├── vite.config.ts
│   └── package.json
├── scripts/           # 部署脚本
├── tests/             # 历史离线测试/迁移基线资产；新增后端测试优先放 backend/tests/
├── docs/              # 文档
│   ├── deploy/        # 部署指南
│   ├── reference/     # 业务参考、开发指南、skill 文档
│   └── internal/      # 内部规划文档
├── workspaces/        # 运行时动态生成（gitignored）
├── start.sh           # 一键启动
└── test.sh            # 运行测试
```

## 目录规范

### 根目录只放核心内容

根目录**只允许**以下内容：

| 类型 | 允许的文件/目录 |
|------|---------------|
| 核心代码 | `backend/`, `frontend/`, `admin-spa/`, `extensions/`, `scripts/` |
| 配置 | `.env`, `.gitignore`, `start.sh`, `test.sh` |
| 核心文档 | `README.md`, `CHANGELOG.md`, `DEVELOPMENT.md`, `QUICKSTART.md`, `TOOLCHAIN.md` |
| 测试/基线 | `backend/tests/`, `tests/` |
| 文档归档 | `docs/` |
| 运行时产物 | `workspaces/`（gitignored） |

**禁止**在根目录放置：
- 业务需求文档、数据模型设计 → 放 `docs/reference/`
- 规划文档、改进计划、TODO → 放 `docs/internal/`
- 临时测试文件、截图、payload → 不入库，或放对应模块的 `tests/fixtures/`
- 独立的组件/页面开发项目 → 放 `docs/reference/` 或独立仓库

### 各目录职责

| 目录 | 职责 | 注意事项 |
|------|------|----------|
| `backend/` | Python 后端代码 | `venv/`, `*.db` 已 gitignore |
| `frontend/` | Vue 前端代码 | `node_modules/`, `dist/` 已 gitignore |
| `scripts/` | 部署和运维脚本 | 仅放 **实际运行的** 脚本，一次性脚本执行后删除 |
| `backend/tests/` | 后端测试代码 | 当前 pytest 入口在 `backend/pytest.ini` 中声明 |
| `tests/` | 历史离线测试/迁移基线资产 | 新增后端测试优先放 `backend/tests/` |
| `docs/deploy/` | 部署指南 | 面向运维 |
| `docs/reference/` | 参考文档 | 业务文档、开发指南、skill 定义等 |
| `docs/internal/` | 内部文档 | 规划、改进计划、架构笔记 |
| `workspaces/` | 动态工作区 | **永远不要提交到 git** |

### 新文件放哪里？

```
我写了一份需求文档          → docs/reference/
我写了一份架构改进计划      → docs/internal/
我写了一个部署脚本          → scripts/
我写了一个后端测试          → backend/tests/
我写了一个一次性数据迁移脚本 → 执行后删除，不入库
我开发了一个示例组件        → docs/reference/ 或独立仓库
我截了一些调试截图          → 不入库（加到 .gitignore）
```

## 快速开始

### 一键启动

```bash
./start.sh
```

### 手动启动

**后端：**
```bash
cd backend
source venv/bin/activate
python run.py
# 端口由 backend/.env 中 PORT 决定，默认 8000
```

**前端：**
```bash
cd frontend
npm run dev
# 默认端口 5173（代理到后端 8000）
```

### 访问地址

- 前端：http://localhost:5173
- 后端 API：http://localhost:8000
- 线上环境：https://agent.dfy.definesys.cn/ai-builder/

## 技术栈

### 后端
- Flask + SQLAlchemy（SQLite）
- MiniMax / Claude — LLM 调用
- SSE — 流式响应
- JWT — 认证

### 前端
- Vue 3 + TypeScript + Vite
- Element Plus — UI 组件库
- Pinia — 状态管理

### 代码工作区
- AI Builder 原生文件树 / 代码查看 / diff
- 后端工作区命令与构建工具
- 自开发资产上传和应用重新发布工具

## Git 规范

### 提交前检查

1. **不要提交运行时产物**：`workspaces/`, `*.db`, `node_modules/`, `venv/`, `dist/`
2. **不要提交敏感信息**：`.env` 中的 API Key（已 gitignore）
3. **不要在根目录堆文件**：按上面的规范归类

### .gitignore 覆盖范围

```
workspaces/         # 动态工作区
*.db                # SQLite 数据库
venv/ .venv/        # Python 虚拟环境
node_modules/       # Node 依赖
frontend/dist/      # 前端构建产物
.env .env.local     # 环境变量
.DS_Store           # macOS 系统文件
__pycache__/        # Python 缓存
.claude/            # Claude Code 配置
```

## 部署

参考 `docs/deploy/deploy-aliyun.md`。

关键步骤：
1. 后端部署到阿里云 ECS
2. 前端 `npm run build` → 静态文件部署
3. 确认 `/coding` 原生代码工作区和自开发上传链路可用

## 调试

### 后端日志
终端直接查看 Flask 日志输出。

### 前端调试
- 浏览器 DevTools → Network / Console
- Vue DevTools 查看组件状态

### 数据库
```bash
cd backend
sqlite3 apaas_builder.db
.tables
```
