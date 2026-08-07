# Standalone Builder AI Control Plane 设计

**Spec ID**: 2026-08-07-standalone-builder-ai-control-plane

状态：用户已于 2026-08-07 书面确认；三仓 Implementation Plan 已下发；尚未进入应用源码实现

正式设计源：

- `product-design/docs/superpowers/specs/2026-08-07-standalone-builder-ai-control-plane-design.md`

实现仓快照与计划下发路径：

- `control-plane/docs/superpowers/specs/2026-08-07-standalone-builder-ai-control-plane-design.md`
- `web-console/docs/superpowers/specs/2026-08-07-standalone-builder-ai-control-plane-design.md`
- `apaas-builder-ai/docs/superpowers/specs/2026-08-07-standalone-builder-ai-control-plane-design.md`

关联设计：

- `control-plane: docs/superpowers/specs/2026-07-14-ai-coding-legacy-service-freeze-design.md`
- `product-design: docs/superpowers/specs/2026-07-11-builder-control-plane-apaas-federated-auth-design.md`

## 1. 背景与目标

当前 Builder-only standalone 环境已经能够通过 aPaaS 账号进入，但 AI 模型、MCP、Skill 和知识库仍混杂在三条历史链路中：

- Builder 自己的数据库、环境变量或宿主文件系统配置。
- 公共 Control Plane 的旧管理接口。
- `/api/platform-catalog/**` 对 Full Workspace 的只读代理。

这些链路无法形成独立、可管理、按 aPaaS 租户隔离的 standalone 产品。本设计新增一套独立 standalone Control Plane，统一承接认证、租户映射、权限、审计和四类 AI 能力事实；Builder 只消费已发布运行目录并执行。

首版必须满足：

- 不依赖 Full Workspace。
- 不读取公共 Control Plane 数据、缓存或配置。
- 不复活已冻结的 legacy Knowledge、Skill、MCP 和 Model 写链路。
- 模型、MCP、Skill、知识库均具备真实管理和 Builder 使用链路，不用 mock 替代线上能力。
- 所有数据按当前登录的 aPaaS 租户严格隔离。
- aPaaS 租户管理员可管理，普通用户只读并使用。
- 当前公共 Control Plane、Web Console 和 Builder 部署不受影响。

## 2. 总体方案与边界

### 2.1 采用方案

在现有 `control-plane` 代码库中新增独立 `builder-ai` 领域和 `standalone-builder-ai` profile，但使用独立 Deployment、数据库、Redis namespace、加密 Secret 和入口。

```text
aPaaS
  -> standalone Control Plane 认证与 tenant-bound session
  -> standalone Web Console 管理 AI 目录
  -> standalone Builder 按当前会话租户读取运行目录
  -> 模型 / MCP / Skill / 知识检索真实执行
```

standalone Control Plane 是唯一事实源。Builder 允许保留有期限、有版本的运行缓存，但不得成为配置事实源。

### 2.2 明确禁止

- 不调用 `/api/platform-catalog/**`、Full Workspace catalog/auth 或公共 Control Plane API。
- 不连接公共 Control Plane 数据库或 Redis DB 0。
- 不从公共数据库复制 schema、登录 key、业务数据或租户配置。
- 不让 Builder 回退本地 `llm_configs`、模型环境变量、租户 MCP 环境变量、宿主 Skill 目录或 Builder 知识库表。
- 不把旧 controller、旧表或旧 API 直接改造成 standalone 写入口。

平台内置 Builder 工具和内置 Skill 可以继续存在，但必须标记 `builtin=true`，不属于租户配置事实，租户资源不得覆盖同名内置资源。

## 3. 正式源、三仓职责与现有成果处置

### 3.1 三仓职责

| 仓库 | 职责 | 不负责 |
| --- | --- | --- |
| `control-plane` | aPaaS 认证、租户与角色校验、四类事实、内部运行目录、加密、审计、迁移、standalone 部署 | Builder 对话执行和页面交互 |
| `web-console` | standalone 路由 allowlist、六个页面、管理 API adapter、管理员写与成员只读体验 | 自行推导权限、直连 aPaaS/Full Workspace |
| `apaas-builder-ai` | `StandaloneAiCatalogClient`、缓存、模型/MCP/Skill/Knowledge 真实消费、旧事实源禁用 | 保存四类租户事实或从公共服务回退 |

正式设计、跨仓契约和执行状态总账只在 `product-design` 维护。三个实现仓必须使用内容一致的快照；模块 plan 不得自行修改跨仓合同，发现偏差先回写正式设计。

### 3.2 现有 worktree 处置

| 现有成果 | 状态 | 允许复用 | 必须拒绝或重写 |
| --- | --- | --- | --- |
| `control-plane/standalone-apaas-control-plane`，提交 `eed39674`、`dcbfd158` | 已提交候选部署骨架 | 独立入口、Deployment、Service、Ingress、独立数据库命名和 aPaaS 直连探索 | `k8s` 通用 profile、Full Workspace URL、公共 schema/login-key 复制、共享 Redis DB 0、非 standalone controller 暴露 |
| `control-plane/tenant-ai-catalog` | 9 个修改文件、2 个未跟踪文件，未提交 | 只读审计其中的租户过滤、MCP/Skill 读取和模型持久化思路 | 禁止整分支、整 diff 或 `/api/platform-catalog/**` 直接混入；`tenantId=null` 全局查询、旧 `om_ai_*` 表扩写和 Full Workspace client 必须拒绝 |

实施前必须形成逐文件 disposition：`reuse`、`extract`、`rewrite` 或 `reject`。来源不明的未提交改动不得作为实现基线，不得清理或覆盖，由其所有者单独保留。

### 3.3 强制复用与隔离矩阵

| 能力 | 必须复用 | 必须新建或隔离 |
| --- | --- | --- |
| 模型 | 现有领域校验、OpenAI Compatible connectivity gateway、Web Console 视觉组件 | tenant-scoped 表、repository binding、`/api/builder-ai` controller/DTO |
| MCP | `McpConfigValidator`、规范化 JSON checksum、远程 HTTP/SSE client 基础 | 租户表、独立 CRUD、runtime projection；不复用通用 Capability 写面 |
| Skill | `SkillArtifactValidator`、ZIP 安全校验、`AdminFileStorageClient` | standalone 治理元数据、版本/启用状态和内部下载 API；ZIP 字节不存 PostgreSQL |
| 知识库 | 安全上传组件、通用文件类型校验和确定性文本工具 | 新 tenant-scoped 文档/分块事实；不复用 legacy Knowledge BFF 或 Full Workspace |
| 基础设施 | Liquibase runner、审计 port、Spring HTTP client、Web Console shared `httpClient` | standalone changelog、profile wiring 和 API adapter |
| 凭据 | 抽取并统一现有 cipher/key-provider 模式 | `builder-ai` 密文 envelope 和独立 K8s Secret；禁止四个子域各写一套加密 |

## 4. 产品范围与路由

standalone Web Console 只挂载：

- 首页 `/`
- 模型 `/ai/models`
- MCP `/ai/mcp`
- Skill `/ai/skills`
- 知识库 `/ai/knowledge-bases/**`
- aPaaS 接入 `/platform/apaas-access`

登录后用户区域只显示用户名，不显示租户、组织、角色、能力中心或平台管理入口。

其他菜单必须移除，路由组件不得挂载。直接访问非 allowlist 路由时跳转首页并显示“当前版本未提供此功能”，且不得发出旧 API、公共 Control Plane 或 Full Workspace 请求。

## 5. aPaaS 认证、租户与权限合同

### 5.1 登录状态机

standalone 只提供 aPaaS 登录，不提供本地账号密码：

| 操作 | 合同 |
| --- | --- |
| `GET /api/auth/login-key` | 返回 standalone RSA 公钥，`PUBLIC` |
| `POST /api/auth/login` | 请求 `username`、RSA 加密 `password`、可选 `apaasTenantId`；直接调用配置的 aPaaS，不调用 Full Workspace |
| `POST /api/auth/select-tenant` | 当用户可访问多个租户且登录未指定租户时，使用一次性 `selectionToken + apaasTenantId` 完成选择 |
| `GET /api/auth/me` | 返回 `userId`、`username`、当前 `apaasTenantId`、内部 `role`；Web Console 只展示 `username` |
| `POST /api/auth/logout` | 撤销当前 session 和 tenant selection token |

登录规则：

- 无可访问租户返回 `BUILDER_AI_TENANT_REQUIRED`。
- 只有一个租户时自动选择。
- 多个租户且未指定时返回 HTTP 409、`BUILDER_AI_TENANT_SELECTION_REQUIRED`、最长 5 分钟的一次性 `selectionToken` 和可选租户列表；此时不签发业务 session。
- 首版不提供登录后租户切换。访问另一租户必须注销并重新登录/选择，避免隐式改变当前事实范围。
- session 必须绑定 aPaaS tenant ID、user ID、username、role、issuedAt 和 expiresAt；客户端 header/body/query 不能覆盖 session tenant。

### 5.2 角色与撤销

- `tenant_admin`：当前租户全部 AI 能力与 aPaaS 接入可读写。
- `member`：当前租户全部 AI 能力只读，可在 Builder 中使用。
- membership 和 role 由 aPaaS 结果决定，本地只保存身份镜像和短 TTL 校验缓存，不保存本地密码。
- 每个请求必须校验 active session 和 tenant；管理写请求还必须重验管理员资格。aPaaS 校验缓存最长 5 分钟，撤销后最迟 5 分钟失效。
- aPaaS 不可达且缓存过期时失败关闭：读写均返回 `BUILDER_AI_IDENTITY_UNAVAILABLE`，不得沿用过期管理员权限。
- controller、application service 和 repository 三层都必须拒绝空 tenant；数据库 `tenant_id` 全部 `NOT NULL`。`NULL` 不得表示全局范围。

### 5.3 权限资源分类

- 登录、tenant selection：`PUBLIC`。
- `/api/builder-ai/**` 管理 API：稳定 `operationId` 和 permission metadata；当前阶段服务端仍以 `tenant_admin/member` guard 为执行事实，不宣称 Permission Core 已完成。
- `/internal/builder-ai/**`：`SYSTEM_INTERNAL`，不进入管理端权限资源。
- Web Console 隐藏按钮只负责体验，不能替代后端 403。

## 6. 数据、约束与资源状态

### 6.1 固定表

| 表 | 职责 |
| --- | --- |
| `om_builder_ai_users` | aPaaS 身份镜像和短 TTL 角色缓存 |
| `om_builder_ai_providers` | 租户级 Provider 与密文凭据 |
| `om_builder_ai_models` | 租户级模型与默认模型 |
| `om_builder_ai_mcp_servers` | MCP 配置、健康状态和密文 Headers |
| `om_builder_ai_skills` | Skill 逻辑身份和当前启用版本 |
| `om_builder_ai_skill_versions` | SDK file ref、checksum、校验状态和版本 |
| `om_builder_ai_knowledge_bases` | 知识库主数据 |
| `om_builder_ai_knowledge_documents` | 文档、版本和发布指针 |
| `om_builder_ai_knowledge_chunks` | 当前可检索分块 |
| `om_builder_ai_catalog_versions` | 每租户运行目录版本，初始 `0` |
| `om_builder_ai_apaas_access` | 租户级 aPaaS 服务接入密文 |

所有业务表包含 `tenant_id`、创建/更新审计字段、`deleted_at` 和 `object_version_number`。唯一约束必须带 `tenant_id`；查询、更新和删除必须在 SQL 条件中包含 tenant。

显示名称在同租户未删除记录中唯一，软删除后允许复用；稳定 ID、artifact checksum 和历史版本 ID 永不复用。

### 6.2 模型状态

- Provider 和 Model 均为 `enabled|disabled`，健康状态独立为 `unknown|healthy|unhealthy`。
- 新租户允许暂时没有默认模型；Builder 使用时返回 `BUILDER_AI_MODEL_NOT_CONFIGURED`。
- 一旦存在可运行模型，当前租户必须且只能有一个 `enabled` 默认模型，由数据库部分唯一索引和同事务行锁保证。
- 禁用或删除当前默认模型必须先设置另一个默认模型，否则返回 `BUILDER_AI_DEFAULT_MODEL_REQUIRED`。
- `set-default` 在一个事务中锁定 tenant catalog row、清除旧默认、设置新默认并递增 `catalog_version`。

### 6.3 MCP 状态

- 配置状态 `enabled|disabled`；健康状态 `unknown|checking|healthy|unhealthy`。
- 连通性检查执行真实 `tools/list`，记录最近检查时间、工具数量和脱敏错误。
- 启用要求最近 24 小时内检查成功；运行期单次工具失败只影响该工具调用，不自动禁用配置。
- 租户 MCP 工具与内置工具同名时，内置工具优先，目录返回冲突列表并记录审计/指标。

### 6.4 Skill 状态

版本状态闭环：

```text
uploading -> validating -> ready -> deleting -> deleted
                    \-> failed -> deleting -> deleted
```

- 上传先创建 `uploading` 元数据，再通过 `AdminFileStorageClient` 保存 ZIP，随后校验并转为 `ready`。
- 校验或持久化失败转 `failed`；失败/孤儿对象由清理 worker 在 24 小时后删除，最多重试 3 次，间隔 1 分钟、5 分钟、30 分钟。
- 只有 `ready` 版本可以启用；同一 Skill 同时只能有一个启用版本，切换在同一事务完成并递增目录版本。
- 平台内置 Skill 名称不可被租户包覆盖，比较使用 trim 后大小写不敏感规范名。

### 6.5 知识文档状态

```text
uploaded -> indexing -> published -> disabled -> indexing
                    \-> index_failed -> indexing
```

- 首版支持 `.md`、`.markdown`、`.txt` 和 `.json`，单文件默认上限 20 MB。
- 发布和重新索引使用 `Idempotency-Key`，返回 HTTP 202；同一文档版本重复处理必须得到相同 chunks checksum。
- worker 最多重试 3 次，间隔 1 秒、5 秒、30 秒；仍失败转 `index_failed` 并告警。
- 新版本索引成功前，旧 `published` 版本继续可检索；成功事务原子切换发布指针、分块集合并递增目录版本。
- 只有 `published` 版本进入 Builder manifest/search/document；`index_failed` 不进入运行目录。
- 知识库必须先禁用且无 published 文档才能删除，否则返回 `BUILDER_AI_RESOURCE_IN_USE`。

## 7. `catalogVersion`、并发与缓存合同

### 7.1 目录版本

以下 runtime-visible 变更必须与业务状态在同一数据库事务中递增当前 tenant 的 `catalog_version`：

- Provider/Model 的启停、启用资源配置变更、默认模型切换和删除。
- MCP 的启停、启用配置变更和删除。
- Skill 启用版本切换、停用和删除。
- 文档发布指针切换、停用、删除，知识库启停。

disabled 草稿编辑、健康检查、失败上传和 `index_failed` 不改变运行目录，因此不递增。

所有更新使用 `object_version_number` 乐观锁；冲突返回 HTTP 409 `BUILDER_AI_CONCURRENT_MODIFICATION`。数据库唯一约束是最终并发防线，不能只依赖 service 查询。

### 7.2 ETag 与 Builder 缓存

- `runtime-catalog` 返回 `ETag: "builder-ai:<catalogVersion>"`。
- Builder 发送 `If-None-Match`；版本一致返回 304、空 body 和同一 ETag。
- 缓存键固定为 `tenantId + catalogVersion`，内存 TTL 30 秒；Skill 解压缓存额外包含 checksum。
- 新对话创建前、每个新用户 turn 前和 TTL 到期时重验目录。单个 turn 使用开始时解析出的不可变快照，下一 turn 才切换新版本。
- TTL 内可使用当前版本缓存；TTL 到期且 Control Plane 不可达时返回 `BUILDER_AI_RUNTIME_CATALOG_UNAVAILABLE`，不得无限使用 stale 数据或回退其它事实源。
- 收到 304 但本地没有对应 tenant/version cache 时视为协议错误，立即无条件重取一次；仍失败则报错。

## 8. 管理 API 合同

### 8.1 通用规则

- Base path：`/api/builder-ai`。
- tenant 只来自 session。
- 列表统一返回 `{items, page, pageSize, total}`，默认 `page=1`、`pageSize=20`、最大 100。
- 创建返回 201，查询/动作返回 200，异步发布/重索引返回 202，删除返回 204。
- `PATCH`、启停、设默认和删除必须携带 `If-Match: "<objectVersionNumber>"`；缺失返回 428，冲突返回 409。
- 管理响应永不返回 API Key、密码、token 或完整敏感 Headers；使用 `credentialConfigured`/`secretFields` 表示已配置。

### 8.2 稳定操作表

| 资源 | method/path | operationId | 管理行为 |
| --- | --- | --- | --- |
| 首页 | `GET /summary` | `builder-ai.summary.get` | 当前租户四类摘要 |
| Provider | `GET/POST /providers` | `builder-ai.provider.list/create` | 列表、创建 |
| Provider | `GET/PATCH/DELETE /providers/{id}` | `builder-ai.provider.get/update/delete` | 详情、更新、删除 |
| Provider | `POST /providers/{id}/enable|disable|check` | `builder-ai.provider.enable/disable/check` | 启停和真实连通检查 |
| Model | `GET/POST /models` | `builder-ai.model.list/create` | 列表、创建 |
| Model | `GET/PATCH/DELETE /models/{id}` | `builder-ai.model.get/update/delete` | 详情、更新、删除 |
| Model | `POST /models/{id}/enable|disable|set-default` | `builder-ai.model.enable/disable/set-default` | 启停、设默认 |
| MCP | `GET/POST /mcp-servers` | `builder-ai.mcp.list/create` | 列表、创建 |
| MCP | `GET/PATCH/DELETE /mcp-servers/{id}` | `builder-ai.mcp.get/update/delete` | 详情、更新、删除 |
| MCP | `POST /mcp-servers/{id}/enable|disable|check` | `builder-ai.mcp.enable/disable/check` | 启停、`tools/list` |
| Skill | `GET/POST /skills` | `builder-ai.skill.list/create` | 列表；首次 multipart ZIP 上传 |
| Skill | `GET/PATCH/DELETE /skills/{id}` | `builder-ai.skill.get/update/delete` | 详情、元数据更新、删除 |
| Skill 版本 | `GET/POST /skills/{id}/versions` | `builder-ai.skill-version.list/create` | 版本列表、multipart ZIP 上传 |
| Skill 版本 | `POST /skills/{id}/versions/{versionId}/enable` | `builder-ai.skill-version.enable` | 原子切换启用版本 |
| Skill 版本 | `GET /skills/{id}/versions/{versionId}/artifact` | `builder-ai.skill-version.download` | 管理员/成员下载，`application/zip` |
| 知识库 | `GET/POST /knowledge-bases` | `builder-ai.knowledge-base.list/create` | 列表、创建 |
| 知识库 | `GET/PATCH/DELETE /knowledge-bases/{id}` | `builder-ai.knowledge-base.get/update/delete` | 详情、更新、删除 |
| 知识库 | `POST /knowledge-bases/{id}/enable|disable` | `builder-ai.knowledge-base.enable/disable` | 启停 |
| 文档 | `GET/POST /knowledge-bases/{id}/documents` | `builder-ai.document.list/upload` | 列表、multipart 上传 |
| 文档 | `GET/DELETE /knowledge-bases/{id}/documents/{documentId}` | `builder-ai.document.get/delete` | 详情、删除 |
| 文档 | `POST /knowledge-bases/{id}/documents/{documentId}/publish|disable|reindex` | `builder-ai.document.publish/disable/reindex` | 发布、停用、重新索引 |
| aPaaS 接入 | `GET/PATCH /apaas-access` | `builder-ai.apaas-access.get/update` | 查询、更新服务账号 |
| aPaaS 接入 | `POST /apaas-access/check` | `builder-ai.apaas-access.check` | 真实登录和租户校验 |

`tenant_admin` 可执行全部操作；`member` 只允许所有 GET 和在 Builder 中使用，写操作统一 403 `BUILDER_AI_ROLE_FORBIDDEN`。

### 8.3 核心请求字段

| 表单 | 字段与约束 |
| --- | --- |
| Provider | `name` 1..80；`apiBaseUrl` HTTPS 或明确允许的内网 HTTP；`apiKey` 创建必填，编辑留空表示保留，`clearApiKey=true` 仅在禁用且无模型依赖时允许 |
| Model | `providerId`、`name` 1..80、`modelCode` 1..120、`type=chat|completion|embedding`；Builder 首版只用 chat/completion |
| MCP | `name` 1..80、`url`、`transport=streamable_http|sse`、`headers` object、`timeoutMs` 1000..120000、`description` 最大 500；敏感 header 留空保留，显式 `clearSecretHeaders` 清除 |
| Skill | `name` 1..80、`description` 最大 500、`version` SemVer、`artifact` ZIP；默认上限 200 MB，包内必须有合法 `SKILL.md` |
| 知识库 | `name` 1..80、`description` 最大 500、`enabled`；文档包含 `file`、可选 `title`、`tags` 最多 20 个 |
| aPaaS 接入 | `baseUrl`、`apaasTenantId` 必须等于当前 session tenant、`username`、可选新 `password`；密码留空保留，不能读取明文 |

依赖阻断：Provider 有未删除 Model 时不可删除；启用 Provider/Model/MCP 前必须满足本节状态规则；危险操作保留原状态直到服务端成功，失败时只展示错误，不做前端乐观删除。

## 9. Builder 内部 API 与运行合同

### 9.1 服务认证

内部 API 同时要求：

- `Authorization: Bearer <standalone tenant-bound session token>`，tenant 从 token 派生，URL/body 不接受 `tenantId`。
- `X-Builder-Internal-Token-Id` 和 `X-Builder-Internal-Token`，只允许 standalone Builder Service 使用。

内部 service token 在 K8s Secret 中维护 `current` 和 `next` 两组 `tokenId/token`，使用常量时间比较。轮换时先发布 `next`，最长双读 24 小时，再提升为 `current`；撤销和校验失败写审计。Ingress 不暴露内部 path，NetworkPolicy 只允许 standalone Builder。

### 9.2 内部端点

| method/path | 主要合同 |
| --- | --- |
| `GET /internal/builder-ai/runtime-catalog` | 返回当前 tenant 的 `catalogVersion`、默认模型、enabled models、MCP、Skill 和冲突摘要；支持 ETag/304 |
| `GET /internal/builder-ai/skills/{skillVersionId}/artifact` | 返回 `application/zip`、`X-Artifact-Sha256`、`ETag`，服务端校验版本属于当前 tenant 且 enabled |
| `GET /internal/builder-ai/knowledge/manifest` | 返回 enabled 知识库和 published 文档摘要 |
| `POST /internal/builder-ai/knowledge/search` | 请求 `query` 1..4000、`limit` 1..20、可选 `knowledgeBaseIds`；返回按权重排序的 hits |
| `GET /internal/builder-ai/knowledge/documents/{documentId}` | 返回当前 tenant published 文档的标题、标签、版本和正文 |

`runtime-catalog` 核心响应：

```json
{
  "catalogVersion": 12,
  "defaultModelId": "model-1",
  "models": [{
    "id": "model-1",
    "name": "Default",
    "modelCode": "gpt-compatible",
    "type": "chat",
    "provider": {"apiBaseUrl": "https://...", "apiKey": "runtime-only-secret"}
  }],
  "mcpServers": [{
    "id": "mcp-1",
    "name": "crm",
    "transport": "streamable_http",
    "url": "https://...",
    "headers": {"Authorization": "runtime-only-secret"},
    "timeoutMs": 30000
  }],
  "skills": [{"id": "skill-1", "versionId": "sv-1", "name": "crm", "version": "1.0.0", "sha256": "..."}],
  "conflicts": [{"type": "mcp_tool", "name": "read_file", "winner": "builtin"}]
}
```

明文运行凭据只出现在内部响应，禁止缓存到日志、审计或持久化调试文件。

Knowledge search hit 固定包含 `knowledgeBaseId`、`documentId`、`chunkId`、`title`、`snippet`、`score`、`documentVersion`。关键词检索按标题、标签、摘要、正文权重排序；同分使用 `documentId + chunkIndex` 稳定排序。

### 9.3 Builder 替换链路

Builder 新增单一 `StandaloneAiCatalogClient`：

1. 从当前 Builder 会话取得 tenant-bound standalone token。
2. 读取/重验 runtime catalog。
3. 模型 resolver 只用目录中的默认或用户选择模型。
4. MCP bridge 只加载目录中的租户远程 MCP，并与内置工具合并。
5. Skill loader 原子下载到临时文件、校验 SHA-256、解压到 `tenantId/versionId/checksum` 缓存；校验失败删除坏缓存并重试一次。
6. Knowledge 工具只调用 manifest/search/document。

standalone profile 下必须禁用以下旧事实源：Builder 数据库模型配置、模型环境变量 fallback、租户 MCP 环境变量、本地租户 Skill 扫描/写入、Builder 知识主表和公共 catalog client。内置 Builder 工具/Skill 不受影响。

错误映射：

- Control Plane/目录不可用：`BUILDER_AI_RUNTIME_CATALOG_UNAVAILABLE`。
- 模型未配置：`BUILDER_AI_MODEL_NOT_CONFIGURED`。
- MCP 单服务不可达：本次工具调用 `BUILDER_AI_MCP_UNAVAILABLE`，其他 MCP 不受影响。
- Skill checksum 二次失败：`BUILDER_AI_SKILL_ARTIFACT_INVALID`。
- 知识无命中返回空 `hits`，服务不可用返回 `BUILDER_AI_KNOWLEDGE_UNAVAILABLE`，不得混淆。

## 10. Web Console 页面与交互合同

### 10.1 通用状态

六个页面统一支持：首次加载 skeleton、空态、局部提交 loading、整页失败与重试、未知状态中性展示。成员可进入详情但所有写按钮隐藏；直接构造写请求仍由服务端 403。

列表统一单行密度、服务端分页、名称关键字筛选和状态筛选。删除、禁用、设默认、启用 Skill 版本、发布/停用/重索引必须二次确认；请求进行中禁用重复操作，成功后只刷新受影响资源和首页摘要。

### 10.2 页面台账

| 页面 | 主要展示 | 管理员操作 | 成员行为 |
| --- | --- | --- | --- |
| 首页 | enabled 模型数/默认模型、MCP 数/异常数、Skill 数、知识库/已发布/失败数 | 点击摘要进入管理页 | 同样可查看摘要 |
| 模型 | Provider 与 Model 两个页签；名称、状态、健康、类型、默认标记 | 新建/编辑/启停/检查/删除/设默认 | 只读 |
| MCP | 名称、transport、URL 脱敏展示、状态、健康、工具数、最近检查 | 新建/编辑/启停/检查/删除 | 只读 |
| Skill | 名称、启用版本、状态、更新时间；详情内版本列表 | 上传、编辑、启用版本、下载、删除 | 查看和下载 |
| 知识库 | 知识库列表和文档子页；发布/索引状态、版本、标签 | 新建/编辑/启停/删除、上传、发布、停用、重索引 | 查看 |
| aPaaS 接入 | Base URL、tenant ID/名称、服务账号、验证状态/时间 | 更新、验证 | 只读 |

敏感输入编辑时永不回填明文，显示“已配置”；留空保存表示保留。只有显式清除开关且依赖规则允许时才能删除凭据。

## 11. 错误、审计与可观测性

统一错误包含 `code`、`message`、`traceId`。除前文错误外，至少包含：

- `BUILDER_AI_IDENTITY_UNAVAILABLE`
- `BUILDER_AI_TENANT_SELECTION_REQUIRED`
- `BUILDER_AI_ROLE_FORBIDDEN`
- `BUILDER_AI_CONCURRENT_MODIFICATION`
- `BUILDER_AI_RESOURCE_IN_USE`
- `BUILDER_AI_MCP_UNAVAILABLE`
- `BUILDER_AI_SKILL_ARTIFACT_INVALID`
- `BUILDER_AI_KNOWLEDGE_INDEX_FAILED`
- `BUILDER_AI_RUNTIME_CATALOG_UNAVAILABLE`

Web Console 生成或透传 `X-Trace-Id`，Control Plane 返回并向 aPaaS、模型、MCP、文件存储传播；Builder 在目录读取和真实调用中继续传播同一 trace。

结构化日志至少包含 `traceId`、`tenantIdHash`、`userIdHash`、`operationId`、`resourceType`、`resourceId`、`catalogVersion` 和 `outcome`。不得记录密码、token、API Key、完整 Headers、Skill ZIP、文档全文或内部 runtime catalog body。

核心指标使用有限基数：

- `builder_ai_catalog_version_change_total{resource_type}`
- `builder_ai_runtime_catalog_request_total{outcome}`
- `builder_ai_mcp_check_total{outcome}`
- `builder_ai_skill_validation_total{outcome}`
- `builder_ai_knowledge_index_total{outcome}`
- `builder_ai_worker_backlog{worker}`

以下操作写审计：登录、tenant selection、退出、aPaaS 接入更新/验证、凭据变更、CRUD、启停、默认模型变更、MCP 检查、Skill 版本启用、文档发布/停用/重索引、内部 token 轮换/拒绝。

健康检查覆盖数据库、Redis、加密 current key、文件存储和 worker。外部模型/MCP/aPaaS 的故障记录为资源健康，不阻断 Control Plane readiness；缺少数据库、加密 key 或 standalone profile 隔离失败必须阻断 readiness。

## 12. 部署、迁移、密钥与回滚

### 12.1 独立资源

- `builder-standalone-control-plane`
- `builder-standalone-web-console`
- standalone Builder
- 独立 PostgreSQL database/user
- 独立 Redis DB 和固定 key prefix `builder-standalone-ai:`
- 独立 AES 和内部 service token Secret

`standalone-builder-ai` profile 必须启动失败于以下情况：配置 Full Workspace URL、启用 `platform-catalog`/legacy catalog bean、缺少独立数据库标识、Redis namespace 为空、使用默认加密 key。

standalone Spring surface 只装配 auth、builder-ai、health/common error 和必需文件存储组件；非 allowlist controller 不注册。部署和 contract test 必须枚举实际 route，证明旧业务 route 不可达。

### 12.2 数据库迁移

- 空数据库只通过仓库内版本化 Liquibase changelog 建立，禁止 `pg_dump` 公共 schema/data。
- 迁移采用 expand/contract：同一版本只新增表/列/索引或兼容读，不在首次上线删除旧结构。
- N 与 N-1 Control Plane 在滚动窗口内都能读取当前 schema；破坏性收缩必须在后续独立版本执行。
- 迁移失败停止 rollout；回滚应用镜像不得回滚已成功的 additive schema。

### 12.3 AES-GCM 密钥

密文 envelope 固定为 `v1:keyId:nonce:ciphertext`。Secret 同时提供 `current` 和可选 `previous` key；写只用 current，读可用 current/previous。轮换先发布新 key、后台重加密并统计剩余旧 key 行，剩余为 0 后才删除 previous。失败时保留双读，不得令历史凭据不可解密。

### 12.4 零公共依赖证据

验收必须同时证明：

- 渲染后的 Deployment 不含 Full Workspace/public Control Plane URL。
- standalone ApplicationContext 不存在相关 client bean 和 `/api/platform-catalog/**` route。
- 公共服务请求计数 sentinel 为 0。
- 公共数据库 canary 账号无连接记录。
- 停止公共 Control Plane/Full Workspace 后，清空 standalone 缓存并重新执行四类真实链路仍成功。

## 13. 实施阶段与激活门槛

保持一个产品规格，但实现按以下阶段交付：

1. 审计现有 worktree，完成复用 disposition、正式源和三仓快照。
2. 完成 standalone profile、aPaaS tenant-bound auth、独立部署/迁移/密钥和 route allowlist。
3. 完成 tenant 数据底座、`catalogVersion`、内部认证和 runtime catalog 骨架。
4. 按模型、MCP、Skill、Knowledge 四个纵向切片分别完成管理 API、Builder 消费和专项测试。
5. 完成 Web Console 六页、成员只读和管理员操作。
6. 断开公共依赖，执行 N/N-1、缓存、秘密 canary 和真实 E2E。

standalone 新入口默认不可路由。只有 auth、管理 API、内部 API、Builder 消费、Web Console 和本阶段专项测试同时完成，才打开对应 capability；不得出现“页面可写但 Builder 不消费”或“Builder 切换但管理面未就绪”的中间产品状态。

## 14. 专项验证合同

不运行三仓全量测试，只保留下列高价值专项门禁。

| 层次 | 必须覆盖 |
| --- | --- |
| Control Plane domain/repository | tenant 必填、跨租户无副作用、默认模型唯一、Skill 单启用版本、知识发布指针、乐观锁、catalog 同事务递增、密文脱敏 |
| Control Plane controller/profile | 管理员写/成员 403、operationId、内部双认证、非 allowlist route 404、无 Full Workspace bean/config |
| Web Console | 六页 loading/empty/error/read-only、表单敏感值保留/清除、危险操作确认、隐藏路由零旧 API 请求 |
| Builder | 无旧事实源 fallback、ETag/304、tenant/version cache、模型真实调用、MCP `tools/list`+工具调用、Skill 下载/校验/缓存/use、Knowledge search+document |
| K8s E2E | aPaaS 登录无循环、跨租户、独立库/Redis、四类真实链路、公共依赖 sentinel=0、N/N-1 rollout/rollback |

建议聚焦命令，implementation plan 可按最终文件名收窄，不能删除对应断言：

```bash
# control-plane
bash scripts/mvn-fast -Dtest='*BuilderAi*Test,*Standalone*ContractTest' test

# web-console
npm run test:fast -- src/features/builder-ai src/app/standalone
npm run typecheck:fast
npm run build:fast

# apaas-builder-ai
cd backend && pytest tests/test_standalone_ai_catalog_client.py tests/test_standalone_ai_runtime.py
cd ../frontend && npm test -- --run src/features/standalone-ai
```

真实 E2E fixtures 必须包含：管理员、member、tenant A/B、已撤销管理员、可用/不可用 Provider、MCP `tools/list` 成功但 invoke 失败、合法/非法 Skill ZIP、知识新版本索引失败、秘密 canary、304 无本地 cache、catalog 并发更新和公共依赖 sentinel。

秘密 canary 必须证明管理响应、错误响应、日志、审计和前端 DOM 均不包含明文 API Key/password/token/header；内部 runtime 响应只在受控测试进程内断言，不落盘。

## 15. 非目标

首版不包含：

- 公共 Control Plane 数据迁移、双写或兼容回退。
- Full Workspace 兼容。
- 本地桌面 SQLite 模型配置。
- MCP 本地进程 transport。
- Skill 在线编辑器和自动生成。
- 向量数据库、embedding 检索、PDF/DOCX 解析。
- 跨租户共享 AI 能力。
- standalone 用户、角色或租户切换管理页面。
- AI 用量计费、配额、模型 fallback 或账号池。

## 16. 完成标准

- 用户从 standalone 入口使用 aPaaS 账号登录，不发生循环跳转；多租户选择失败关闭。
- 登录后只出现约定导航和用户名，隐藏路由不可直接访问且不产生旧 API 请求。
- 四类 AI 能力均能真实创建、持久化、按租户读取并被 Builder 使用。
- member 只读，tenant admin 可管理；角色撤销最长 5 分钟生效。
- 所有 tenant 查询和写入 fail-closed，不存在 `tenantId=null` 全局语义。
- `catalogVersion`、ETag、缓存和四类资源状态闭环通过并发/失败恢复验证。
- standalone 不装配 Full Workspace/public Control Plane client，不连接其数据库/Redis。
- 凭据不出现在管理响应、错误、日志、审计或前端 DOM。
- N/N-1 rollout、应用回滚和 AES key 轮换有专项证据。
- 当前公共部署功能和数据保持不变。

## 17. 下发 Phase / Plan 与状态总账

| 模块 | Spec 快照 | Implementation Plan | 计划分支与基线 | 当前状态 |
| --- | --- | --- | --- | --- |
| `control-plane` | `docs/superpowers/specs/2026-08-07-standalone-builder-ai-control-plane-design.md` | `docs/superpowers/plans/2026-08-07-standalone-builder-ai-control-plane.md` | `plan/2026-08-07-standalone-builder-ai`，基线 `25a13fc7` | 已下发，待选择执行方式 |
| `web-console` | `docs/superpowers/specs/2026-08-07-standalone-builder-ai-control-plane-design.md` | `docs/superpowers/plans/2026-08-07-standalone-builder-ai-web-console.md` | `plan/2026-08-07-standalone-builder-ai`，基线 `456fe2a` | 已下发，待选择执行方式 |
| `apaas-builder-ai` | `docs/superpowers/specs/2026-08-07-standalone-builder-ai-control-plane-design.md` | `docs/superpowers/plans/2026-08-07-standalone-builder-ai-builder.md` | `plan/2026-08-07-standalone-builder-ai`，基线 `98df769a` | 已下发，待选择执行方式 |

任何实现偏差必须先回写本节，并重新同步三个快照。当前仅完成正式规格确认和 implementation plan 下发；在用户选择执行方式前，不修改三仓应用源码。
