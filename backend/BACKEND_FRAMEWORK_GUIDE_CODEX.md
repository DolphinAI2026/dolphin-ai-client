# aPaaS Builder AI Backend 接手文档

## 1. 项目定位

这个仓库是一个 **Python 异步后端服务**，核心职责不是传统 CRUD，而是把几类能力串起来：

1. 提供给前端的 API 服务
2. 管理用户、租户、团队、权限
3. 调用大模型生成低代码应用配置
4. 连接得帆云 aPaaS 平台，创建应用、模型、表单、流程、权限
5. 提供一个 coding/workspace 能力，用于生成二次开发代码骨架

如果只看“框架”，这个项目的主框架其实就是：

- **FastAPI**: Web API 框架
- **Pydantic v2**: 请求/响应数据校验
- **SQLAlchemy 2.x Async**: 异步 ORM 和数据库访问
- **httpx**: 调用外部 LLM / aPaaS 接口
- **sse-starlette**: 流式 SSE 输出

项目本质上是一个“**FastAPI + 异步服务编排 + 外部平台适配**”的后端。

## 2. 实际技术栈

### Web 层

- **FastAPI 0.115.0**
  - 入口在 `app/main.py`
  - 用 `APIRouter` 组织模块
  - 用 `Depends(...)` 做依赖注入
  - 用 `response_model` 做响应约束
  - 用 `lifespan` 做启动初始化

- **Uvicorn 0.32.0**
  - 本地启动入口是 `run.py`
  - 本质上就是启动 `app.main:app`

- **CORS Middleware**
  - 在 `app/main.py` 里配置
  - 当前放行本地前端开发地址：`http://localhost:5173`、`http://localhost:3000`

### 配置与数据校验

- **Pydantic 2.9.2**
  - 主要放在 `app/schemas.py`
  - 用于定义登录、对话、应用、步骤执行等请求和响应模型

- **pydantic-settings 2.6.0**
  - 配置入口在 `app/config.py`
  - 自动从 `.env` 读取环境变量

### 数据层

- **SQLAlchemy 2.0.36 Async**
  - 入口在 `app/database.py`
  - 使用 `create_async_engine`、`AsyncSession`、`async_sessionmaker`
  - Model 基类是 `DeclarativeBase`

- **数据库驱动**
  - `requirements.txt` 里装了 `aiomysql`
  - `config.py` 的默认值是 `sqlite+aiosqlite:///./apaas_builder.db`
  - 但当前项目实际 `.env` 配置使用的是 **MySQL + aiomysql**
  - 如果你想直接用默认 SQLite 启动，还需要确认环境里有 `aiosqlite`，因为当前 `requirements.txt` 没有显式写出它

结论：

- **代码默认设计兼容 SQLite 和 MySQL**
- **当前实际运行更偏向 MySQL 环境**

### 认证与安全

- **python-jose**
  - JWT 编解码
  - 位置：`app/auth.py`、`app/deps.py`

- **HTTPBearer**
  - FastAPI 的 Bearer Token 鉴权方式

- **cryptography**
  - 主要用于 aPaaS 登录时的 RSA 公钥加密
  - 位置：`app/apaas_client.py`

### 对外集成

- **httpx 0.27.2**
  - 调 LLM 的 OpenAI 兼容接口
  - 调得帆云 aPaaS 接口

- **sse-starlette 2.1.3**
  - 用于聊天、配置生成、代码生成等流式响应
  - 典型文件：`app/routes/chat.py`、`app/routes/applications.py`、`app/routes/coding.py`

## 3. 当前项目的实际运行配置

根据当前 `.env`，这套服务实际运行时的关键配置是：

- `DATABASE_URL`: MySQL + `aiomysql`
- `HOST`: `0.0.0.0`
- `PORT`: `8001`
- `APAAS_BASE_URL`: 指向一套得帆云 dev 环境
- `LLM_API_BASE`: OpenAI 兼容接口
- `LLM_MODEL`: `claude-haiku-4-5-20251001`

这说明：

1. 这个仓库虽然能本地跑 SQLite 默认值，但团队真实环境主要还是按 MySQL 使用
2. 它不是纯内部业务系统，而是明显依赖外部平台和外部模型接口

## 4. 项目分层怎么理解

这个项目不是那种非常严格的“controller-service-repository”分层，更接近：

1. **路由层**
   - 在 `app/routes/*`
   - 负责接 API、参数校验、鉴权、查库、调用外部服务、组装响应

2. **基础能力层**
   - `app/config.py`: 配置
   - `app/database.py`: 数据库连接
   - `app/models/*`: ORM 模型
   - `app/schemas.py`: Pydantic 模型
   - `app/auth.py` / `app/deps.py`: 认证上下文
   - `app/permissions.py`: RBAC 权限判断

3. **集成与生成层**
   - `app/llm_client.py`: 大模型统一客户端
   - `app/apaas_client.py`: 得帆云平台客户端
   - `app/generator_v2.py`: 一次性完整生成流程
   - `app/config_assembler.py`: 分阶段配置生成
   - `app/ai_doc_parser.py`: 文档转配置
   - `app/step_executor.py`: 分步执行创建流程

4. **coding 子域**
   - `app/routes/coding.py`
   - `app/coding/*`
   - 负责场景识别、模板生成、代码生成、工作区管理

要注意一个事实：

- **很多业务编排逻辑直接写在 route 里**
- 所以接手时不能假设“route 很薄、service 很厚”
- 实际阅读时经常要从 `routes/*.py` 直接顺着读到 client / generator

## 5. 目录地图

推荐把下面这些文件当成主干：

- `app/main.py`
  - 应用入口
  - 注册中间件、路由、启动生命周期

- `app/config.py`
  - 环境变量配置

- `app/database.py`
  - 异步 engine / session
  - 启动时建表
  - 做了少量手工 `ALTER TABLE` 兼容逻辑

- `app/models/__init__.py`
  - 用户、对话、消息、应用模型

- `app/models/tenant.py`
  - 多租户、角色、团队相关模型

- `app/schemas.py`
  - API 请求/响应模型

- `app/auth.py`
  - JWT、密码 hash、当前用户获取

- `app/deps.py`
  - `AuthContext`
  - 多租户上下文解析

- `app/permissions.py`
  - 双层权限模型

- `app/routes/auth.py`
  - 注册、登录、选择租户、获取当前用户

- `app/routes/conversations.py`
  - 对话与消息列表

- `app/routes/chat.py`
  - Builder/Assistant/Developer 对话
  - SSE 流式输出

- `app/routes/applications.py`
  - 应用 CRUD
  - 文档上传
  - 本地应用与平台应用合并展示

- `app/routes/generation_steps.py`
  - Copilot 分步生成

- `app/routes/coding.py`
  - coding/vibe coding 场景
  - 代码生成、工作区管理

- `app/llm_client.py`
  - OpenAI 兼容协议封装

- `app/apaas_client.py`
  - 得帆云 API 封装

- `app/generator_v2.py`
  - 从 preview 配置完整创建平台资源

- `app/config_assembler.py`
  - 骨架、字典、模型分阶段生成

- `app/ai_doc_parser.py`
  - 文档解析为 preview JSON

## 6. 核心框架机制

### 6.1 FastAPI 的使用方式

这个项目里最需要掌握的 FastAPI 点：

1. **APIRouter 模块化**
   - 每个业务域一个 route 文件
   - 最终统一在 `app/main.py` 注册到 `/api`

2. **Depends 依赖注入**
   - `get_db` 注入数据库会话
   - `get_auth_context` 注入当前登录用户 + 当前租户 + 权限

3. **response_model**
   - 返回结果会经过 Pydantic 序列化和约束
   - 对前后端契约很重要

4. **lifespan**
   - 启动时会跑 `init_db()`
   - 然后执行 `seed_initial_data()`

5. **SSE 流式接口**
   - 使用 `EventSourceResponse`
   - 适用于聊天内容逐段返回、配置阶段进度返回、代码生成流式返回

### 6.2 Pydantic 的使用方式

主要是两类用途：

1. **请求体校验**
   - 比如 `UserLogin`、`ApplicationCreate`、`ChatRequest`

2. **响应格式约束**
   - 比如 `ApplicationResponse`、`ConversationResponse`、`GenerationStatusResponse`

你接手时重点不是“会写 BaseModel”这么简单，而是要看：

- 哪些字段是前端依赖的稳定契约
- 哪些字段是后端内部兼容历史逻辑才保留的

### 6.3 SQLAlchemy Async 的使用方式

这个项目采用的是 **SQLAlchemy 2.x 异步 ORM 写法**：

- 查询常见模式：
  - `await db.execute(select(...))`
  - `result.scalar_one_or_none()`
  - `result.scalars().all()`

- 新增/提交常见模式：
  - `db.add(obj)`
  - `await db.commit()`
  - `await db.refresh(obj)`

要特别注意：

- 这里**没有 Alembic 迁移体系**
- 当前 schema 变更主要靠 `Base.metadata.create_all()` + 手工 `ALTER TABLE`

这意味着：

- 小改动接起来快
- 但长期维护时，数据库演进可控性一般

### 6.4 认证与多租户

这是项目理解的关键，不只是 JWT 登录这么简单。

登录链路：

1. `auth/login` 验证用户名密码
2. 如果用户是平台管理员，直接发无租户 token
3. 如果用户属于一个租户，直接发带 `tid` 的 JWT
4. 如果属于多个租户，先发 `selection_token`，再选租户换正式 token

请求鉴权链路：

1. `HTTPBearer` 取出 token
2. `app/deps.py` 解析 JWT
3. 读出 `sub` 和 `tid`
4. 查询用户、租户成员关系、角色权限
5. 组装 `AuthContext`

`AuthContext` 是整个项目里非常重要的对象，里面有：

- 当前用户
- 当前租户 ID
- 当前租户角色
- 当前组织级权限 JSON

### 6.5 权限模型

权限不是单层判断，而是 **双层权限模型**：

1. **组织角色权限**
   - 例如 `application:create`
   - 来自 `Role.permissions`

2. **资源范围权限**
   - 是否本人创建
   - 是否团队成员
   - 团队角色是 `admin/member/viewer`

这块封装在 `app/permissions.py`。

理解这个模型后，再看 `applications.py` 里的权限校验会清楚很多。

### 6.6 SSE 流式输出

这个项目大量用 SSE，而不是 WebSocket。

典型场景：

- 聊天回复逐段输出
- 生成配置时分阶段推送进度
- coding 代码生成时持续推送结果

对应实现特点：

- `EventSourceResponse(event_generator())`
- 生成器里边调 LLM，边收到 chunk 边 `yield`
- 最后把完整结果落库

如果你后续改前后端交互，这一块要特别小心，前端通常会依赖事件类型和 JSON 格式。

## 7. 业务主链路

### 7.1 服务启动

启动时序：

1. 启动 FastAPI 应用
2. `lifespan` 中执行 `init_db()`
3. 自动建表
4. 自动补部分新列
5. 执行 `seed_initial_data()`
6. 确保默认租户和默认角色存在

### 7.2 Builder 对话生成链路

主要发生在 `app/routes/chat.py`：

1. 用户创建对话
2. 用户发送消息
3. 后端保存消息到 `messages`
4. 根据 `agent_type` 注入不同 system prompt
5. 调 `LLMClient.chat_completion_stream()`
6. 通过 SSE 把生成内容持续推给前端
7. 最终把 assistant 回复落库

### 7.3 配置生成链路

有两种思路：

1. **一次性 preview JSON**
   - 传统 builder 对话里让模型直接吐配置

2. **分阶段组装**
   - `app/config_assembler.py`
   - 先骨架，再字典，再模型，再汇总

后者更适合长需求，降低一次性输出超长 JSON 的失败概率。

### 7.4 文档解析链路

`app/ai_doc_parser.py` 的思路不是规则引擎，而是：

1. 文档小则一次性丢给 LLM
2. 文档大则拆段
3. 分段提取模型、字段、字典
4. 最后合并并做 code 清洗

这说明项目对“需求文档 -> 结构化配置”的依赖很重。

### 7.5 平台生成链路

平台资源创建分两类方式：

1. **完整生成**
   - 在 `app/generator_v2.py`
   - 一口气跑角色、字典、模型、表单、流程、权限

2. **分步生成**
   - 在 `app/routes/generation_steps.py` + `app/step_executor.py`
   - 每个步骤可单独执行、重试、查看状态

如果未来要提升可观测性或失败恢复能力，优先看分步生成这套。

### 7.6 Coding / Workspace 链路

`coding` 模块是这个项目比较“产品化”的一层扩展：

1. 识别开发场景
2. 给出模板骨架
3. 调 LLM 生成代码
4. 在 `workspaces/` 下创建工作区
5. 支持文件读写、npm install、build

注意：

- 工作区目录不在 `backend/app` 里
- 它会创建到仓库上层的 `workspaces/` 目录

## 8. 你接手时最该先读什么

建议阅读顺序：

1. `app/main.py`
   - 先看服务怎么启动、注册了哪些路由

2. `app/config.py`
   - 明白环境变量入口

3. `app/database.py`
   - 明白数据库连接、session、初始化方式

4. `app/models/__init__.py` + `app/models/tenant.py`
   - 把核心实体关系先建立起来

5. `app/auth.py` + `app/deps.py` + `app/permissions.py`
   - 先吃透认证、多租户、权限

6. `app/routes/auth.py`
   - 登录模型最能体现权限上下文怎么进入系统

7. `app/routes/chat.py`
   - 看 SSE + LLM 是怎么串起来的

8. `app/routes/applications.py`
   - 看应用主业务是怎么组织的

9. `app/apaas_client.py`
   - 看平台 API 能力边界

10. `app/generator_v2.py` + `app/step_executor.py`
   - 看配置最终如何落地为平台资源

11. `app/routes/coding.py` + `app/coding/*`
   - 最后再看扩展能力

如果你只有半天时间，至少读完前 8 步。

## 9. 推荐学习顺序

如果你想“学框架 + 接项目”一起推进，建议按这个顺序学：

### 第一阶段: FastAPI 基础

掌握这些关键词就够接这个项目：

- `FastAPI`
- `APIRouter`
- `Depends`
- `HTTPException`
- `response_model`
- `lifespan`
- `UploadFile`

### 第二阶段: Pydantic v2

重点看：

- `BaseModel`
- 字段约束
- 嵌套模型
- 响应序列化

### 第三阶段: SQLAlchemy 2 Async

重点看：

- `create_async_engine`
- `AsyncSession`
- `select(...)`
- `scalar_one_or_none()`
- `scalars().all()`
- `commit / refresh / flush`

### 第四阶段: FastAPI 鉴权与依赖注入

重点看：

- Bearer Token
- JWT
- 把“认证上下文”通过 `Depends` 注入业务接口

### 第五阶段: SSE 与外部 API

重点看：

- `EventSourceResponse`
- 异步生成器
- `httpx.AsyncClient`

### 第六阶段: 项目私有业务

最后再补：

- aPaaS 平台对象模型
- 应用配置 preview JSON 结构
- 平台生成步骤
- coding 工作区机制

## 10. 接手时要特别注意的实现特点

### 10.1 这不是标准的“纯净分层”

route 层里有不少业务编排代码，所以排查问题时不要只盯 service。

### 10.2 数据库迁移方式比较轻

当前没有标准 migration 工具，字段新增主要靠启动时补列。

如果后续持续演进 schema，建议尽早评估引入 Alembic。

### 10.3 外部依赖很多

系统可用性依赖：

- MySQL
- LLM API
- 得帆云 aPaaS 平台

所以联调问题不一定是后端本身逻辑错误，很多时候是外部依赖异常。

### 10.4 测试更像脚本验证，不是完整测试体系

仓库根目录有不少 `test_*.py`、`check_*.py`、`verify_*.py` 文件，但目前看更像手工验证脚本，不是完整的自动化测试体系。

接手后如果要做稳定性建设，建议优先把关键链路补成标准测试。

### 10.5 配置文件需要安全治理

当前 `.env.example` 中包含了比较完整的示例配置。接手时建议检查是否存在不该保留在样例文件中的敏感信息，并做脱敏处理。

### 10.6 当前密码实现比较轻

`app/auth.py` 里当前密码哈希是直接用 SHA256，而不是 `passlib + bcrypt` 这类更常见的密码方案。

这不影响你理解框架，但如果后续要做安全加固，这里是一个应优先评估的点。

## 11. 你可以把这个项目归类成什么框架

如果别人问你“这项目是什么框架”，比较准确的回答是：

> 这是一个基于 **FastAPI** 的异步 Python 后端，使用 **Pydantic v2** 做数据模型、**SQLAlchemy Async** 做数据库访问，并通过 **httpx + SSE** 编排 LLM 和得帆云 aPaaS 平台能力。

如果要再通俗一点：

> 这是一个“FastAPI 后端 + AI 生成服务 + 低代码平台适配层”的项目。

## 12. 建议的接手动作

建议你按下面顺序开始接：

1. 先本地跑通登录和 `/api/health`
2. 再跑通一条对话 SSE 链路
3. 再看应用创建和平台同步
4. 最后再看 coding/workspace

这样会比一开始直接啃 `generator_v2.py` 更高效。
