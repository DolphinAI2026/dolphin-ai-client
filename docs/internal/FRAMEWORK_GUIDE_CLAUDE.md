# aPaaS Builder AI - 技术框架学习指南

> 本文档帮助开发者快速了解项目技术栈，便于接手和开发。

## 目录

1. [项目概述](#项目概述)
2. [后端技术栈](#后端技术栈)
3. [前端技术栈](#前端技术栈)
4. [快速启动](#快速启动)
5. [学习资源](#学习资源)

---

## 项目概述

**aPaaS Builder AI** 是得帆云低代码平台的智能搭建助手，主要特性：
- 对话式交互搭建应用
- Vibe Coding 自开发模块（AI辅助组件开发）
- 多租户架构
- 流式 AI 响应

---

## 后端技术栈

### 核心框架

| 框架/库 | 版本 | 用途 | 学习优先级 |
|---------|------|------|-----------|
| **FastAPI** | 0.115.0 | Web 框架 | ⭐⭐⭐ 必学 |
| **SQLAlchemy** | 2.0.36 | ORM | ⭐⭐⭐ 必学 |
| **Pydantic** | 2.9.2 | 数据验证 | ⭐⭐⭐ 必学 |
| **Uvicorn** | 0.32.0 | ASGI 服务器 | ⭐⭐ 了解 |
| **httpx** | 0.27.2 | 异步 HTTP 客户端 | ⭐⭐ 了解 |
| **python-jose** | 3.3.0 | JWT 认证 | ⭐⭐ 了解 |
| **sse-starlette** | 2.1.3 | 流式响应 | ⭐ 需要时查 |

### 1. FastAPI (Web 框架)

FastAPI 是现代化的 Python Web 框架，基于 Starlette 和 Pydantic。

**核心特性：**
- 自动生成 API 文档（Swagger/ReDoc）
- 原生异步支持（async/await）
- 类型提示驱动的数据验证
- 依赖注入系统

**项目中的使用：**

```python
# backend/app/main.py - 应用入口
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="aPaaS Builder AI")

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 路由注册
app.include_router(auth.router, prefix="/api/auth")
app.include_router(chat.router, prefix="/api/chat")
```

```python
# backend/app/routes/auth.py - 路由示例
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(tags=["认证"])

@router.post("/login")
async def login(form: LoginForm):
    # 业务逻辑
    return {"token": token}

@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user
```

**学习资源：**
- 官方文档：https://fastapi.tiangolo.com/zh/
- 推荐从 Tutorial 部分开始

---

### 2. SQLAlchemy 2.0 (ORM)

SQLAlchemy 2.0 是 Python 最流行的 ORM，本项目使用**异步模式**。

**核心概念：**
- `AsyncEngine` - 异步数据库引擎
- `AsyncSession` - 异步会话
- `Mapped[]` - 类型注解式字段定义
- `relationship()` - 关系映射

**项目中的使用：**

```python
# backend/app/database.py - 数据库配置
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# 异步引擎
engine = create_async_engine(DATABASE_URL, echo=True)

# 异步会话工厂
AsyncSessionLocal = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

# 依赖注入
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
```

```python
# backend/app/models/user.py - 模型定义
from sqlalchemy import String, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    email: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(default=True)

    # 关系
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="user")
```

```python
# 查询示例
async def get_user(db: AsyncSession, user_id: int):
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    return result.scalar_one_or_none()
```

**学习资源：**
- 官方文档：https://docs.sqlalchemy.org/en/20/
- 重点看 ORM Quick Start 和 Async IO 章节

---

### 3. Pydantic v2 (数据验证)

Pydantic 用于数据验证和序列化，v2 性能大幅提升。

**核心概念：**
- `BaseModel` - 数据模型基类
- `Field()` - 字段约束
- `model_validator` - 模型级验证

**项目中的使用：**

```python
# backend/app/schemas.py
from pydantic import BaseModel, Field, EmailStr

class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=6)

class UserResponse(BaseModel):
    id: int
    username: str
    email: str

    model_config = {"from_attributes": True}  # 支持 ORM 模型转换

# 使用
@router.post("/register", response_model=UserResponse)
async def register(user: UserCreate):
    # user 已自动验证
    pass
```

**学习资源：**
- 官方文档：https://docs.pydantic.dev/latest/

---

### 4. 依赖注入

FastAPI 的依赖注入是核心模式，本项目大量使用。

```python
# backend/app/deps.py
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer

security = HTTPBearer()

async def get_current_user(
    token: str = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    """获取当前登录用户"""
    payload = decode_token(token.credentials)
    user = await get_user(db, payload["sub"])
    if not user:
        raise HTTPException(status_code=401)
    return user

# 路由中使用
@router.get("/profile")
async def profile(user: User = Depends(get_current_user)):
    return user
```

---

### 5. SSE 流式响应

用于 AI 聊天的流式输出。

```python
# backend/app/routes/chat.py
from sse_starlette.sse import EventSourceResponse

@router.post("/send")
async def chat_send(message: ChatMessage):
    async def generate():
        async for chunk in llm_client.stream(message.content):
            yield {"event": "message", "data": chunk}
        yield {"event": "done", "data": ""}

    return EventSourceResponse(generate())
```

---

### 后端目录结构

```
backend/
├── app/
│   ├── main.py          # FastAPI 入口
│   ├── database.py      # 数据库配置
│   ├── deps.py          # 依赖注入
│   ├── schemas.py       # Pydantic 模型
│   ├── permissions.py   # 权限检查
│   ├── models/          # SQLAlchemy 模型
│   │   ├── user.py
│   │   ├── tenant.py
│   │   └── conversation.py
│   ├── routes/          # API 路由
│   │   ├── auth.py      # 认证
│   │   ├── chat.py      # 聊天
│   │   ├── conversations.py
│   │   └── applications.py
│   ├── apaas_client.py  # 得帆云 API 客户端
│   ├── llm_client.py    # LLM 客户端
│   └── skills/          # 平台能力封装
├── requirements.txt
├── run.py               # 启动脚本
└── .env                 # 环境配置
```

---

## 前端技术栈

### 核心框架

| 框架/库 | 版本 | 用途 | 学习优先级 |
|---------|------|------|-----------|
| **Vue 3** | 3.5.25 | UI 框架 | ⭐⭐⭐ 必学 |
| **TypeScript** | 5.9.3 | 类型系统 | ⭐⭐⭐ 必学 |
| **Pinia** | 3.0.4 | 状态管理 | ⭐⭐⭐ 必学 |
| **Vue Router** | 5.0.3 | 路由 | ⭐⭐ 了解 |
| **Element Plus** | 2.13.5 | UI 组件库 | ⭐⭐ 按需查 |
| **Vite** | 7.3.1 | 构建工具 | ⭐ 了解即可 |

### 1. Vue 3 Composition API

Vue 3 推荐使用 Composition API，代码更清晰、复用性更强。

**核心概念：**
- `ref()` / `reactive()` - 响应式数据
- `computed()` - 计算属性
- `watch()` / `watchEffect()` - 侦听器
- `onMounted()` 等生命周期钩子

**项目中的使用：**

```vue
<!-- frontend/src/views/ChatPage.vue -->
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useUserStore } from '@/stores/user'

// 响应式数据
const messages = ref<Message[]>([])
const inputText = ref('')
const loading = ref(false)

// Store
const userStore = useUserStore()

// 计算属性
const canSend = computed(() => inputText.value.trim() && !loading.value)

// 方法
async function sendMessage() {
  loading.value = true
  try {
    // 发送逻辑
  } finally {
    loading.value = false
  }
}

// 生命周期
onMounted(() => {
  loadHistory()
})
</script>

<template>
  <div class="chat-page">
    <div v-for="msg in messages" :key="msg.id">
      {{ msg.content }}
    </div>
    <el-input v-model="inputText" @keyup.enter="sendMessage" />
    <el-button :disabled="!canSend" @click="sendMessage">发送</el-button>
  </div>
</template>
```

**学习资源：**
- 官方文档：https://cn.vuejs.org/guide/introduction.html
- 重点学习 Composition API 章节

---

### 2. Pinia (状态管理)

Pinia 是 Vue 3 官方推荐的状态管理库，替代 Vuex。

**核心概念：**
- `defineStore()` - 定义 Store
- `state` - 状态
- `getters` - 计算属性
- `actions` - 方法

**项目中的使用：**

```typescript
// frontend/src/stores/user.ts
import { defineStore } from 'pinia'

interface UserState {
  user: User | null
  token: string | null
  tenantId: string | null
}

export const useUserStore = defineStore('user', {
  state: (): UserState => ({
    user: null,
    token: localStorage.getItem('token'),
    tenantId: null,
  }),

  getters: {
    isLoggedIn: (state) => !!state.token,
    isTenantAdmin: (state) => state.user?.role === 'admin',
  },

  actions: {
    async login(username: string, password: string) {
      const res = await authApi.login({ username, password })
      this.token = res.token
      this.user = res.user
      localStorage.setItem('token', res.token)
    },

    logout() {
      this.token = null
      this.user = null
      localStorage.removeItem('token')
    },
  },
})
```

```vue
<!-- 组件中使用 -->
<script setup lang="ts">
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()

// 直接访问
console.log(userStore.user)
console.log(userStore.isLoggedIn)

// 调用 action
await userStore.login('admin', '123456')
</script>
```

**学习资源：**
- 官方文档：https://pinia.vuejs.org/zh/

---

### 3. TypeScript

本项目使用 TypeScript 严格模式，类型安全是重点。

```typescript
// frontend/src/types/index.ts
export interface User {
  id: number
  username: string
  email: string
  role: 'admin' | 'member' | 'viewer'
}

export interface Message {
  id: string
  content: string
  role: 'user' | 'assistant'
  createdAt: string
}

export interface ApiResponse<T> {
  code: number
  data: T
  message: string
}
```

```typescript
// frontend/src/api/auth.ts
import request from '@/utils/request'
import type { User, ApiResponse } from '@/types'

export function login(data: { username: string; password: string }) {
  return request.post<ApiResponse<{ token: string; user: User }>>('/auth/login', data)
}
```

---

### 4. Vue Router

路由配置和导航守卫。

```typescript
// frontend/src/router/index.ts
import { createRouter, createWebHistory } from 'vue-router'
import { useUserStore } from '@/stores/user'

const routes = [
  { path: '/login', component: () => import('@/views/Login.vue') },
  {
    path: '/',
    component: () => import('@/views/Landing.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/chat/:id?',
    component: () => import('@/views/ChatPage.vue'),
    meta: { requiresAuth: true }
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 导航守卫
router.beforeEach((to, from, next) => {
  const userStore = useUserStore()
  if (to.meta.requiresAuth && !userStore.isLoggedIn) {
    next('/login')
  } else {
    next()
  }
})

export default router
```

---

### 5. Element Plus

企业级 UI 组件库，按需使用即可。

```vue
<template>
  <el-form :model="form" :rules="rules">
    <el-form-item label="用户名" prop="username">
      <el-input v-model="form.username" />
    </el-form-item>
    <el-form-item>
      <el-button type="primary" @click="submit">提交</el-button>
    </el-form-item>
  </el-form>

  <el-table :data="list">
    <el-table-column prop="name" label="名称" />
    <el-table-column prop="status" label="状态" />
  </el-table>
</template>
```

**学习资源：**
- 官方文档：https://element-plus.org/zh-CN/

---

### 前端目录结构

```
frontend/src/
├── views/              # 页面组件
│   ├── Login.vue       # 登录
│   ├── Landing.vue     # 首页
│   ├── ChatPage.vue    # 对话
│   ├── CodingPage.vue  # Vibe Coding
│   └── Apps.vue        # 应用列表
├── stores/             # Pinia 状态管理
│   ├── user.ts         # 用户状态
│   ├── coding.ts       # Coding 模块
│   └── preview.ts      # 预览数据
├── api/                # API 封装
│   ├── auth.ts
│   ├── conversation.ts
│   └── coding.ts
├── components/         # 通用组件
├── router/             # 路由配置
├── types/              # TypeScript 类型
├── utils/              # 工具函数
│   └── request.ts      # Axios 配置
├── App.vue             # 根组件
└── main.ts             # 入口文件
```

---

## 快速启动

### 一键启动

```bash
./start.sh
```

### 手动启动

```bash
# 后端
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python run.py  # http://localhost:8001

# 前端（新终端）
cd frontend
npm install
npm run dev    # http://localhost:5173
```

### 访问地址

- 前端：http://localhost:5173
- 后端 API：http://localhost:8001
- API 文档：http://localhost:8001/docs

---

## 学习资源

### 推荐学习顺序

1. **FastAPI 官方教程** (2-3 天)
   - https://fastapi.tiangolo.com/zh/tutorial/
   - 重点：路由、依赖注入、请求体验证

2. **SQLAlchemy 2.0 ORM** (1-2 天)
   - https://docs.sqlalchemy.org/en/20/orm/quickstart.html
   - 重点：模型定义、关系、异步查询

3. **Vue 3 Composition API** (2-3 天)
   - https://cn.vuejs.org/guide/essentials/reactivity-fundamentals.html
   - 重点：ref/reactive、computed、watch、生命周期

4. **Pinia** (半天)
   - https://pinia.vuejs.org/zh/core-concepts/
   - 跟着官方示例走一遍即可

5. **TypeScript 基础** (1-2 天)
   - https://www.typescriptlang.org/zh/docs/handbook/
   - 重点：类型注解、接口、泛型

### 视频教程推荐

- FastAPI：B站搜索 "FastAPI 教程"
- Vue 3：B站搜索 "Vue3 Composition API"

### 实践建议

1. 先跑通项目，理解整体流程
2. 从简单的接口开始，如 `/api/health`
3. 跟踪一个完整请求：登录 → 获取用户信息
4. 尝试添加一个简单的新功能

---

## 常见问题

### Q: 为什么使用异步（async/await）？

本项目涉及大量 I/O 操作（数据库查询、LLM 调用、外部 API），异步可以提高并发性能，避免阻塞。

### Q: Pydantic v1 和 v2 的区别？

v2 是重写版本，性能提升 5-50 倍，但 API 有变化：
- `Config` 类改为 `model_config`
- `orm_mode` 改为 `from_attributes`
- 验证器装饰器改变

### Q: Vue 2 和 Vue 3 的区别？

- Composition API vs Options API
- `<script setup>` 语法糖
- Pinia 替代 Vuex
- 更好的 TypeScript 支持

---

*文档更新时间：2026-03-20*
