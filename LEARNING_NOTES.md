# aPaaS Builder AI - 学习笔记

> 记录项目接手过程中的问题和理解，便于回顾思路。

---

## 问题 1：项目技术框架梳理

**问题**：帮我梳理一下这个项目使用的框架，我需要学习一下这个框架，帮我更好的接手这个项目

**回答摘要**：

### 后端技术栈
| 框架/库 | 版本 | 用途 |
|---------|------|------|
| FastAPI | 0.115.0 | Web 框架 |
| SQLAlchemy | 2.0.36 | ORM（异步模式） |
| Pydantic | 2.9.2 | 数据验证 |
| Uvicorn | 0.32.0 | ASGI 服务器 |
| httpx | 0.27.2 | 异步 HTTP 客户端 |
| python-jose | 3.3.0 | JWT 认证 |
| sse-starlette | 2.1.3 | 流式响应 |

### 前端技术栈
| 框架/库 | 版本 | 用途 |
|---------|------|------|
| Vue 3 | 3.5.25 | UI 框架（Composition API） |
| TypeScript | 5.9.3 | 类型系统 |
| Pinia | 3.0.4 | 状态管理 |
| Element Plus | 2.13.5 | UI 组件库 |
| Vite | 7.3.1 | 构建工具 |

**产出文档**：`FRAMEWORK_GUIDE.md`

---

## 问题 2：PyCharm 运行配置

**问题**：我要在 PyCharm 上配置 run 的入口，该怎么设置这个配置

**回答摘要**：

### 方式一：直接运行 run.py（推荐）
```
Name:              Backend Server
Script path:       backend/run.py
Working directory: backend
Python interpreter: venv
```

### 方式二：使用 Uvicorn 模块（支持热重载）
```
Name:              Backend Dev (Reload)
Module name:       uvicorn
Parameters:        app.main:app --host 0.0.0.0 --port 8001 --reload
Working directory: backend
```

### 虚拟环境配置
路径：`backend/venv/bin/python`

---

## 问题 3：分步执行接口解读

**问题**：详细解读一下 `/applications/{app_id}/steps/execute` 这个接口干了什么

**回答摘要**：

### 接口作用
分步执行平台资源创建，将 AI 生成的应用配置逐步部署到得帆云平台。

### 6 个步骤
1. **create_app** - 创建平台应用，生成 `apaas_app_id` 和随机后缀 `suffix`
2. **create_roles_dicts** - 批量创建角色和字典，添加字典选项
3. **create_model:{idx}** - 创建数据模型（含子表），每个模型独立执行
4. **create_form:{idx}** - 创建表单 + 菜单 + 绑定字典
5. **create_workflow:{idx}** - 创建审批流程
6. **configure_permissions** - 配置操作权限和数据权限

### 步骤依赖关系
```
create_app
    │
    ├──────────────────┬─────────────────────────────────┐
    ▼                  ▼                                 ▼
create_roles_dicts   create_model:0    create_model:1   ...
    │                  │                   │
    └──────────────────┴───────────────────┘
                       │
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
    create_form:0  create_form:1    ...
         │             │
         └─────────────┴─────────────┐
                                     ▼
                            create_workflow:0 ...
                                     │
                                     ▼
                          configure_permissions
```

### 关键代码位置
- `backend/app/routes/generation_steps.py` - 步骤路由
- `backend/app/step_executor.py` - 步骤执行器

---

## 问题 4：配置数据存储位置

**问题**：只传入了 step，如何知道整个应用的配置的？它是存在哪里的？

**回答摘要**：

### 存储位置
配置存储在数据库 `applications` 表的 `config_preview` 字段（TEXT/JSON）。

### 数据流向
```
AI 对话 / 上传文档 / 手动创建
            ↓
    POST /api/applications
            ↓
    Application.config_preview = JSON 序列化
            ↓
    数据库持久化
            ↓
    POST /steps/execute
            ↓
    _load_config(app) → json.loads(app.config_preview)
            ↓
    提取 models, roles, dicts, workflows, permissions
```

### config_preview 数据结构
```json
{
  "type": "preview",
  "data": {
    "appName": "客户管理系统",
    "models": [{ "name": "客户信息", "fields": [...] }],
    "roles": [{ "name": "销售", "code": "sales" }],
    "dicts": [{ "name": "客户类型", "options": [...] }],
    "workflows": [{ "name": "审批流程", "nodes": [...] }],
    "permissions": [{ "form": "客户信息", "rules": [...] }]
  }
}
```

### 关键代码
```python
# generation_steps.py:55-58
def _load_config(app: Application) -> dict:
    return json.loads(app.config_preview)
```

---

## 问题 5：增量更新资源需求

**问题**：如果用户在同一个会话中上传了文档创建了应用，之后文档有修改，希望不要再次创建应用，直接更新原本的资源（角色、数据字典等），该如何做？

**回答摘要**：

### 当前限制
1. 平台 API 缺少 `update_*` 方法（角色、字典、模型）
2. 只有表单配置支持 `save_form_config` 全量更新
3. 字典选项支持增量添加（merge 模式）

### 现有复用机制
- 按名称检测已存在资源，但只是"跳过"不是"更新"

### 设计方案

#### 核心思路：差异检测 + 增量执行
```
新配置 ──┐
         ├─→ compute_diff() ─→ ConfigDiff ─→ IncrementalExecutor ─→ 平台 API
旧配置 ──┘
```

#### 更新策略
| 变更类型 | 角色 | 字典 | 字典选项 | 模型 | 表单组件 |
|---------|------|------|---------|------|---------|
| 新增 | ✅ 创建 | ✅ 创建 | ✅ 添加 | ✅ 创建 | ✅ 更新 |
| 修改 | ❌ 跳过 | ❌ 跳过 | ❌ 跳过 | ❌ 跳过 | ✅ 更新 |
| 删除 | ❌ 忽略 | ❌ 忽略 | ❌ 忽略 | ❌ 忽略 | ✅ 移除 |

#### 新增 API
- `POST /applications/{app_id}/incremental/diff` - 对比差异
- `POST /applications/{app_id}/incremental/preview` - 预览步骤
- `POST /applications/{app_id}/incremental/execute` - 执行更新

**产出文档**：`INCREMENTAL_UPDATE_PLAN.md`

---

## 待深入学习

1. **FastAPI 依赖注入** - `Depends()` 的使用模式
2. **SQLAlchemy 2.0 异步** - `AsyncSession` 和 `select()` 语法
3. **SSE 流式响应** - `EventSourceResponse` 实现
4. **得帆云 API** - RSA 加密登录、资源 CRUD

---

## 相关文档索引

| 文档 | 位置 | 内容 |
|------|------|------|
| 框架学习指南 | `FRAMEWORK_GUIDE.md` | 技术栈详解和学习资源 |
| 增量更新计划 | `INCREMENTAL_UPDATE_PLAN.md` | 增量更新功能设计 |
| 项目说明 | `CLAUDE.md` | 项目概述和开发命令 |
| 后端接口文档 | `docs/backend-interface-doc.md` | API 接口说明 |

---

*更新时间：2026-03-20*
