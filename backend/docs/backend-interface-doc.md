# Python 后端接口文档与调用链路

基于当前代码梳理，时间点为 2026-03-20。

## 1. 总览

### 1.1 服务入口

- 应用入口: `app/main.py`
- 统一前缀: `/api`
- 启动链路:
  - `FastAPI(lifespan=lifespan)`
  - `lifespan -> init_db()`
  - `lifespan -> seed_initial_data(session)`
  - `include_router(...)` 挂载各模块路由

### 1.2 当前暴露的接口数量

- 共 42 个 HTTP 接口
- 其中 SSE 流式接口 5 个

### 1.3 核心分层

- 路由层: `app/routes/*.py`
- 鉴权与租户上下文:
  - `app/auth.py`
  - `app/deps.py`
- 数据访问层:
  - `app/database.py`
  - `app/models/__init__.py`
  - `app/models/tenant.py`
- LLM 能力:
  - `app/llm_client.py`
  - `app/config_assembler.py`
  - `app/ai_doc_parser.py`
  - `app/coding/generator.py`
- aPaaS 平台集成:
  - `app/apaas_client.py`
  - `app/generator_v2.py`
  - `app/step_executor.py`
- 工作区能力:
  - `app/coding/workspace.py`

### 1.4 核心数据模型

- `User`: 登录用户、aPaaS Token、平台/租户身份
- `Tenant`: 租户
- `UserTenant`: 用户与租户关系
- `Role`: 租户级角色及组织权限
- `Conversation`: AI 对话
- `Message`: 对话消息
- `Application`: 应用草稿、配置预览、生成状态、aPaaS 应用 ID
- `Team` / `TeamMember`: 团队协作与资源权限

## 2. 全局约定

### 2.1 鉴权

- 无需鉴权:
  - `GET /api/health`
  - `POST /api/auth/register`
  - `POST /api/auth/login`
  - `POST /api/auth/select-tenant`
  - `GET /api/coding/scenes`
- 其余接口默认使用 `Authorization: Bearer <token>`
- 特殊接口:
  - `GET /api/applications/{app_id}/generate`
  - 这是 SSE 接口，代码里因为 `EventSource` 不能直接带 `Authorization` header，所以通过 `?token=` 传 JWT

### 2.2 多租户

- 常规鉴权依赖: `get_auth_context`
- 解析 JWT 中的:
  - `sub`: 用户 ID
  - `tid`: 当前租户 ID
- 返回 `AuthContext`:
  - `user`
  - `tenant_id`
  - `tenant_role`
  - `org_permissions`
- 资源接口通常再结合:
  - `has_org_permission`
  - `check_resource_permission`
  - `batch_get_permissions`

### 2.3 SSE 接口

- `POST /api/chat/send`
- `POST /api/chat/generate-config`
- `GET /api/applications/{app_id}/generate`
- `POST /api/applications/upload-doc-with-conversation`
- `POST /api/coding/generate-stream`

### 2.4 外部系统

- LLM 服务:
  - `LLMClient.chat_completion`
  - `LLMClient.chat_completion_stream`
- 得帆云 aPaaS:
  - `APaaSClient.login`
  - `APaaSClient.test_connection`
  - `APaaSClient.query_app_list/query_models/query_dicts/query_menus`
  - `APaaSClient.create_app/create_roles/create_dicts/create_models/create_form_config/create_menu/save_process_config/create_form_permissions`
- 本地工作区:
  - `WorkspaceManager`
  - 文件系统 + `npm install` + `npm run build`

## 3. 接口文档

下面每一行都包含接口作用和主调用链路。

### 3.1 健康检查

| 接口 | 鉴权 | 作用 | 关键入参 | 返回 | 调用链路 |
| --- | --- | --- | --- | --- | --- |
| `GET /api/health` | 否 | 服务存活检查 | 无 | `{"status":"ok"}` | `main.health_check -> 直接返回` |

### 3.2 认证模块

| 接口 | 鉴权 | 作用 | 关键入参 | 返回 | 调用链路 |
| --- | --- | --- | --- | --- | --- |
| `POST /api/auth/register` | 否 | 注册用户，并自动加入默认租户为租户管理员 | `username`, `password` | `Token` | `auth.register -> User 查询去重 -> get_password_hash -> 创建 User -> 查 default Tenant -> 查 R_tenant_admin -> 创建 UserTenant -> create_access_token` |
| `POST /api/auth/login` | 否 | 登录，并根据租户数决定直接发 JWT 还是先选租户 | `username`, `password` | `LoginResponse` | `auth.login -> 校验密码/状态 -> 平台管理员直接发 token 或查询 UserTenant -> 单租户直接发 token / 多租户返回 tenants 或 selection_token` |
| `POST /api/auth/select-tenant` | 否 | 多租户用户确认租户，换正式 JWT | `selection_token`, `tenant_id` | `Token` | `auth.select_tenant -> JWT decode(selection_token) -> 校验 UserTenant -> create_access_token` |
| `GET /api/auth/me` | Bearer | 获取当前登录用户和当前租户信息 | Header Token | `UserInfo` | `auth.get_me -> get_auth_context -> 查询 Tenant 名称 -> 组装 UserInfo` |

### 3.3 对话模块

| 接口 | 鉴权 | 作用 | 关键入参 | 返回 | 调用链路 |
| --- | --- | --- | --- | --- | --- |
| `POST /api/conversations` | Bearer | 创建 AI 对话 | `agent_type`，限定 `builder/assistant/developer` | `ConversationResponse` | `conversations.create_conversation -> get_auth_context -> 创建 Conversation -> commit/refresh -> 返回` |
| `GET /api/conversations` | Bearer | 获取当前用户当前租户下的对话列表 | 无 | `ConversationResponse[]` | `conversations.list_conversations -> get_auth_context -> select Conversation by user_id + tenant_id -> 返回` |
| `GET /api/conversations/{conversation_id}` | Bearer | 获取单个对话详情 | 路径参数 `conversation_id` | `ConversationResponse` | `conversations.get_conversation -> get_auth_context -> select Conversation -> 不存在返回 404` |
| `GET /api/conversations/{conversation_id}/messages` | Bearer | 获取对话消息列表 | 路径参数 `conversation_id` | `MessageResponse[]` | `conversations.list_messages -> 先校验 Conversation 归属 -> select Message order by created_at asc` |

### 3.4 聊天模块

| 接口 | 鉴权 | 作用 | 关键入参 | 返回 | 调用链路 |
| --- | --- | --- | --- | --- | --- |
| `POST /api/chat/send` | Bearer | 向 builder/assistant/developer 对话发送消息，并流式返回 LLM 回复 | `conversation_id`, `message`, `current_config?` | SSE: `message/done/error` | `chat.send_message -> get_auth_context -> 校验 Conversation -> 保存 user Message -> 读取历史 -> 拼 system prompt 与 current_config 摘要 -> LLMClient.chat_completion_stream -> 保存 assistant Message` |
| `POST /api/chat/generate-config` | Bearer | 根据已澄清需求分阶段生成 preview 配置 | `conversation_id`, `message` | SSE: `progress/done/error` | `chat.generate_config_phased -> get_auth_context -> 校验 Conversation -> 读取最近消息摘要 -> config_assembler.assemble_config_streaming -> 保存 system 预览消息 + assistant 摘要消息` |

补充说明:

- `chat/send` 的 `current_config` 不会全量传给 LLM，而是先压缩成摘要，强制走 patch 模式
- `chat/generate-config` 是真正的“配置组装器”入口，不再让模型一次性吐完整 JSON

### 3.5 应用模块

| 接口 | 鉴权 | 作用 | 关键入参 | 返回 | 调用链路 |
| --- | --- | --- | --- | --- | --- |
| `GET /api/applications` | Bearer | 获取应用列表，合并本地草稿和远端 aPaaS 应用 | `team_scope?`, `include_remote?`, `source_filter?` | `MergedAppResponse[]` | `applications.list_applications -> get_auth_context -> 查本地 Application -> batch_get_permissions -> 有 aPaaS token 时 APaaSClient.query_app_list -> 本地/远端合并构造返回` |
| `GET /api/applications/{app_id}` | Bearer | 获取单个本地应用详情 | `app_id` | `ApplicationResponse` | `applications.get_application -> get_auth_context -> select Application by tenant -> check_resource_permission(view) -> _enrich -> batch_get_permissions` |
| `POST /api/applications` | Bearer | 创建应用草稿 | `conversation_id`, `app_name`, `app_code`, `description?`, `config_preview?` | `ApplicationResponse` | `applications.create_application -> get_auth_context -> has_org_permission(application:create) -> 创建 Application(status=draft) -> commit/refresh -> _enrich` |
| `PUT /api/applications/{app_id}` | Bearer | 更新应用草稿与 preview 配置 | `app_id` + `ApplicationCreate` | `ApplicationResponse` | `applications.update_application -> get_auth_context -> select Application -> check_resource_permission(edit) -> 更新名称/描述/config_preview -> completed/failed 时重置为 draft` |
| `DELETE /api/applications/{app_id}` | Bearer | 删除本地应用记录 | `app_id` | `{"ok":true}` | `applications.delete_application -> get_auth_context -> select Application -> check_resource_permission(delete) -> db.delete` |
| `GET /api/applications/{app_id}/generate` | `?token=` | 一键完整生成 aPaaS 应用 | `app_id`, `token(query)` | SSE: `progress/done/error` | `applications.generate_application -> JWT decode(query token) -> 查 User/Application -> APaaSClient.create_app(首次) -> generator_v2.run_complete_generation -> 更新 Application.apaas_app_id/status` |
| `POST /api/applications/upload-doc` | Bearer | 上传 Markdown 设计文档，直接解析成 preview JSON | `multipart file(.md)` | `{type,data,summary,document_content}` | `applications.upload_design_doc -> 读文件 -> ai_doc_parser.parse_doc_with_ai -> 结果后处理 -> 生成摘要返回` |
| `POST /api/applications/upload-doc-with-conversation` | Bearer | 上传 Markdown 文档，流式解析并自动创建对话 | `multipart file(.md)` | SSE: `progress/done/error` | `applications.upload_doc_with_conversation -> 读文件 -> config_assembler.assemble_config_streaming -> 独立 AsyncSession 创建 Conversation + Message(system/assistant/preview)` |

补充说明:

- `GET /api/applications` 的 `team_scope`:
  - `personal`: 个人应用
  - 数字字符串: 指定团队 ID
- `source_filter`:
  - `local`
  - `remote`
  - `linked`
- `upload-doc` 和 `upload-doc-with-conversation` 只接受 `.md`

### 3.6 aPaaS 连接模块

| 接口 | 鉴权 | 作用 | 关键入参 | 返回 | 调用链路 |
| --- | --- | --- | --- | --- | --- |
| `POST /api/apaas/login` | Bearer | 用账号密码登录得帆云，保存平台 Token 到当前用户 | `username`, `password`, `base_url?`, `tenant_id?` | `{status,token,user_id}` | `apaas.apaas_login -> get_current_user -> APaaSClient.login(RSA 加密密码) -> 写回 User.apaas_token/base_url/tenant_id/user_id -> commit` |
| `POST /api/apaas/connect` | Bearer | 用已有平台 Token 建立连接并验证 | `token`, `base_url?`, `tenant_id?` | `{status,message}` | `apaas.apaas_connect -> get_current_user -> APaaSClient.test_connection -> 写回 User.apaas_token/base_url/tenant_id -> commit` |
| `GET /api/apaas/status` | Bearer | 查看当前用户是否已连接 aPaaS | 无 | `{connected:bool}` | `apaas.apaas_status -> get_current_user -> 判断 user.apaas_token 是否存在` |

### 3.7 分步生成模块

| 接口 | 鉴权 | 作用 | 关键入参 | 返回 | 调用链路 |
| --- | --- | --- | --- | --- | --- |
| `GET /api/applications/{app_id}/steps/status` | Bearer | 获取 Copilot 分步生成状态 | `app_id` | `GenerationStatusResponse` | `generation_steps.get_step_status -> _get_app -> _load_config -> _load_state -> _build_steps` |
| `POST /api/applications/{app_id}/steps/execute` | Bearer | 执行单个生成步骤 | `step`，如 `create_app`/`create_model:0` | `StepExecuteResponse` | `generation_steps.execute_step -> _get_app/_build_steps -> 创建 APaaSClient -> _execute_step_impl -> step_executor.execute_* -> 更新 generation_state` |
| `POST /api/applications/{app_id}/steps/reset` | Bearer | 重置某个步骤或全部步骤状态 | `step?` | `{"ok":true}` | `generation_steps.reset_step -> _get_app -> _load_state -> 清理 steps_completed/step_errors/apaas_app_id/suffix 等中间状态 -> commit` |

分步执行支持的内部步骤:

- `create_app`
- `create_roles_dicts`
- `create_model:{idx}`
- `create_form:{idx}`
- `create_workflow:{idx}`
- `configure_permissions`

### 3.8 Coding 模块

| 接口 | 鉴权 | 作用 | 关键入参 | 返回 | 调用链路 |
| --- | --- | --- | --- | --- | --- |
| `GET /api/coding/scenes` | 否 | 获取所有支持的自开发场景 | `category?` | 场景列表 | `coding.list_scenes -> get_all_scenes/get_scenes_by_category -> 返回 SceneInfo 摘要` |
| `POST /api/coding/detect-scene` | Bearer | 根据需求自动识别场景 | `requirement` | `scene_type/scene_name/...` | `coding.detect_scene -> CodingGenerator.detect_scene -> LLMClient.chat_completion -> SceneType -> get_scene` |
| `POST /api/coding/template` | Bearer | 生成指定场景的模板骨架 | `scene_type`, `module_name` | 文件列表 | `coding.generate_template -> SceneType 校验 -> templates.get_project_template` |
| `POST /api/coding/generate` | Bearer | 非流式生成代码文件 | `scene_type?`, `requirement`, `conversation_id?`, `app_id?`, `module_name?` | `CodeGenerationResult` | `coding.generate_code -> 场景识别 -> _get_conversation_history -> _get_app_context -> CodingGenerator.generate -> parse_files_from_response -> validate_generated_code -> 按需保存对话` |
| `POST /api/coding/generate-stream` | Bearer | 流式生成代码，并可挂接工作区上下文 | `scene_type?`, `message`, `conversation_id?`, `app_id?`, `workspace_id?` | SSE 默认 data 事件 | `coding.generate_code_stream -> 场景识别 -> 历史消息 -> _get_app_context -> _build_workspace_context -> 创建或复用 Conversation -> CodingGenerator.generate_stream -> 保存 assistant 消息` |
| `GET /api/coding/conversations` | Bearer | 获取 coding 类型对话列表 | 无 | 对话列表 | `coding.list_coding_conversations -> select Conversation(agent_type='coding')` |
| `GET /api/coding/conversations/{conversation_id}/messages` | Bearer | 获取 coding 对话消息 | `conversation_id` | 消息列表 | `coding.get_coding_messages -> 校验 Conversation 属于当前用户 -> select Message` |
| `POST /api/coding/workspace/create` | Bearer | 创建工作区并生成脚手架 | `project_type`, `project_name` | workspace meta | `coding.create_workspace -> WorkspaceManager.create_workspace -> 写 .workspace.json -> scaffold_* -> list_files` |
| `POST /api/coding/workspace/{ws_id}/install` | Bearer | 安装工作区依赖 | `ws_id` | `{status,message}` | `coding.install_workspace_deps -> WorkspaceManager.install_deps -> asyncio.create_subprocess_exec('npm','install',...)` |
| `POST /api/coding/workspace/{ws_id}/build` | Bearer | 构建工作区项目 | `ws_id` | `{status,message}` | `coding.build_workspace -> WorkspaceManager.build_project -> asyncio.create_subprocess_exec('npm','run','build')` |
| `GET /api/coding/workspace/{ws_id}` | Bearer | 获取工作区信息 | `ws_id` | meta + files | `coding.get_workspace_info -> WorkspaceManager.get_workspace_info` |
| `GET /api/coding/workspace/{ws_id}/files` | Bearer | 列出工作区文件 | `ws_id` | `string[]` | `coding.list_workspace_files -> WorkspaceManager.list_files` |
| `GET /api/coding/workspace/{ws_id}/file` | Bearer | 读取工作区单文件内容 | `ws_id`, `file_path(query)` | `{path,content}` | `coding.read_workspace_file -> WorkspaceManager.read_file -> 路径越界检查` |
| `POST /api/coding/workspace/{ws_id}/file` | Bearer | 写文件到工作区 | `file_path`, `content` | `{status,path}` | `coding.write_workspace_file -> WorkspaceManager.write_file -> 路径越界检查 -> 写磁盘` |
| `GET /api/coding/workspaces` | Bearer | 获取当前用户所有工作区 | 无 | workspace meta 列表 | `coding.list_workspaces -> WorkspaceManager.list_user_workspaces` |
| `GET /api/coding/workspace/{ws_id}/conversation` | Bearer | 获取工作区最近关联对话及消息 | `ws_id` | `{conversation_id,messages}` | `coding.get_workspace_conversation -> 查询最近 Conversation(workspace_id=ws_id) -> select Message` |
| `DELETE /api/coding/workspace/{ws_id}` | Bearer | 删除工作区目录 | `ws_id` | `{status:"ok"}` | `coding.delete_workspace -> WorkspaceManager.delete_workspace -> shutil.rmtree` |

## 4. 关键调用链路拆解

这一部分把最重要的“接口 -> 服务 -> 外部系统”链路按步骤展开。

### 4.1 聊天问答链路

接口:

- `POST /api/chat/send`

执行过程:

1. `get_auth_context` 解析 JWT，拿到用户与租户上下文
2. 查询 `Conversation`，确认该对话属于当前用户和租户
3. 先保存一条 `user` 消息到 `Message`
4. 读取历史消息，组装 `llm_messages`
5. 根据 `agent_type` 选择 system prompt
6. 如果有 `current_config`，只生成配置摘要注入，不把完整 JSON 塞给模型
7. 调用 `LLMClient.chat_completion_stream`
8. 把每个 chunk 通过 SSE 发回前端
9. 流式结束后把完整回复保存为 `assistant` 消息

主要价值:

- 适合需求澄清、多轮补充
- 支持“增量改配置”，避免大 JSON 全量重输

### 4.2 分阶段配置生成链路

接口:

- `POST /api/chat/generate-config`
- `POST /api/applications/upload-doc-with-conversation`

共同核心:

- `config_assembler.assemble_config_streaming`

内部阶段:

1. `skeleton`
   - 用 LLM 抽取应用名、角色、模型名、字典名、流程提示
2. `dicts`
   - 按批次生成字典选项
3. `models`
   - 按批次生成模型字段
4. `workflows`
   - 如果骨架里识别到审批流，再生成流程配置
5. `complete`
   - 汇总为完整 preview JSON
   - 调用 `_fix_field_types`
   - 复用 `ai_doc_parser` 的 `_sanitize_codes/_fill_icons/_dedup_dicts`

两个入口的区别:

- `chat/generate-config`
  - 输入是用户的最终需求描述和对话上下文
  - 输出后会把 preview 作为 `system` 消息保存到已有对话
- `upload-doc-with-conversation`
  - 输入是 `.md` 文档全文
  - 输出后会自动创建一个新的 builder 对话，并保存摘要和 preview

### 4.3 文档解析链路

接口:

- `POST /api/applications/upload-doc`

执行过程:

1. 校验文件扩展名必须是 `.md`
2. 读取文档全文
3. 调用 `ai_doc_parser.parse_doc_with_ai`
4. `parse_doc_with_ai` 内部分两条路:
   - 小文档: `_parse_single`
   - 大文档: `_parse_chunked`
5. `_parse_chunked` 的步骤:
   - `_build_overview_text`
   - LLM 提取 overview
   - `_split_doc_by_sections`
   - 并发解析每段
   - 汇总 models/dicts/roles
6. 最后统一后处理:
   - `_sanitize_codes`
   - `_fill_icons`
   - `_dedup_dicts`
7. 路由层再根据结果生成自然语言摘要返回

主要价值:

- 把需求文档直接转成应用 preview JSON
- 对大文档做了“概览 + 分段 + 合并”处理，避免一次性上下文过大

### 4.4 应用一键生成链路

接口:

- `GET /api/applications/{app_id}/generate`

执行过程:

1. 从 query string 解出 JWT
2. 查 `User` 和 `Application`
3. 读取 `Application.config_preview`
4. 用当前用户保存的 aPaaS token 初始化 `APaaSClient`
5. 如果本地还没有 `apaas_app_id`
   - 先调用 `APaaSClient.create_app`
   - 把 `apaas_app_id` 回写到 `Application`
6. 调用 `generator_v2.run_complete_generation`
7. `run_complete_generation` 内部阶段:
   - Phase 0: 配置解析
   - Phase 1: 创建角色 + 字典 + 字典选项
   - Phase 2: 创建数据模型
   - Phase 3: 创建表单、菜单、字典绑定
   - Phase 4: 配置表单权限
8. 路由层监听阶段事件
   - 完成时把 `Application.status` 更新为 `completed`
   - 报错时更新为 `failed`

注意:

- 这是“完整流水线”
- 当前 `generator_v2` 已覆盖角色、字典、模型、表单、权限，但不负责审批流
- 审批流生成在 Copilot 分步模式里由 `step_executor.execute_create_workflow` 负责

### 4.5 Copilot 分步生成链路

接口:

- `GET /api/applications/{app_id}/steps/status`
- `POST /api/applications/{app_id}/steps/execute`
- `POST /api/applications/{app_id}/steps/reset`

核心状态载体:

- `Application.generation_state`

主要状态字段:

- `steps_completed`
- `step_errors`
- `apaas_app_id`
- `suffix`
- `dict_codes`
- `role_codes`
- `model_info`
- `form_results`

`execute` 的真实下沉点:

- `create_app -> execute_create_app`
- `create_roles_dicts -> execute_create_roles_dicts`
- `create_model:{idx} -> execute_create_model`
- `create_form:{idx} -> execute_create_form`
- `create_workflow:{idx} -> execute_create_workflow`
- `configure_permissions -> execute_configure_permissions`

这一套相比“一键生成”的价值:

- 可恢复
- 可单步重试
- 可局部回滚
- 可单独补审批流

### 4.6 Coding 代码生成链路

接口:

- `POST /api/coding/generate`
- `POST /api/coding/generate-stream`

执行过程:

1. 场景识别:
   - 手动指定 `scene_type`
   - 或 `CodingGenerator.detect_scene` 自动识别
2. 获取辅助上下文:
   - `_get_conversation_history`
   - `_get_app_context`
   - `_build_workspace_context`
3. `CodingGenerator._build_messages`
   - 拼场景 prompt
   - 注入应用模型/字典/菜单上下文
   - 注入工作区文件树和关键 `.vue` 文件
4. 调用 LLM:
   - 非流式: `LLMClient.chat_completion`
   - 流式: `LLMClient.chat_completion_stream`
5. 解析文件:
   - `parse_files_from_response`
6. 校验:
   - `validate_generated_code`
7. 保存对话:
   - `Message(user/assistant)`

流式接口额外行为:

- 首先返回 `scene_detected`
- 中间持续返回 `content`
- 末尾追加 `GENERATION_META`
- 最后返回 `done`

### 4.7 Coding 工作区链路

接口:

- `POST /api/coding/workspace/create`
- `POST /api/coding/workspace/{ws_id}/install`
- `POST /api/coding/workspace/{ws_id}/build`
- `GET/POST /api/coding/workspace/{ws_id}/file`
- `DELETE /api/coding/workspace/{ws_id}`

工作区管理器:

- `WorkspaceManager`

核心能力:

- 生成工作区 ID 和目录
- 写 `.workspace.json`
- 根据 `ProjectType` 生成脚手架:
  - `form-component`
  - `form-page`
  - `form-list`
  - `backend-api`
- 读写文件时做路径逃逸检查
- 安装依赖时起子进程执行 `npm install`
- 构建时起子进程执行 `npm run build`

## 5. 模块职责速查

| 模块 | 职责 |
| --- | --- |
| `app/main.py` | 应用启动、路由挂载、健康检查 |
| `app/auth.py` | 密码哈希、JWT 生成、当前用户解析 |
| `app/deps.py` | 多租户鉴权上下文解析 |
| `app/permissions.py` | 组织权限 + 资源权限双层校验 |
| `app/routes/auth.py` | 注册、登录、选租户、当前用户 |
| `app/routes/conversations.py` | 对话与消息查询 |
| `app/routes/chat.py` | AI 聊天与配置生成 |
| `app/routes/applications.py` | 应用草稿、文档导入、完整生成 |
| `app/routes/apaas.py` | aPaaS 平台连接管理 |
| `app/routes/generation_steps.py` | Copilot 分步生成 |
| `app/routes/coding.py` | 自开发场景、代码生成、工作区 |
| `app/llm_client.py` | OpenAI 兼容协议的 LLM 客户端 |
| `app/apaas_client.py` | 得帆云平台 HTTP 客户端 |
| `app/config_assembler.py` | 分阶段组装 preview 配置 |
| `app/ai_doc_parser.py` | 文档转 preview 配置 |
| `app/generator_v2.py` | 一键生成 aPaaS 应用 |
| `app/step_executor.py` | 单步生成执行器 |
| `app/coding/generator.py` | 代码生成、文件解析、校验 |
| `app/coding/workspace.py` | 工作区与脚手架管理 |

## 6. 建议的阅读顺序

如果你要继续深入这套后端，建议按这个顺序看:

1. `app/main.py`
2. `app/deps.py`
3. `app/routes/auth.py`
4. `app/routes/chat.py`
5. `app/routes/applications.py`
6. `app/config_assembler.py`
7. `app/ai_doc_parser.py`
8. `app/generator_v2.py`
9. `app/routes/generation_steps.py`
10. `app/step_executor.py`
11. `app/routes/coding.py`
12. `app/coding/generator.py`
13. `app/coding/workspace.py`

这样能先看清入口，再看配置生成，再看落地到 aPaaS 的执行链。
