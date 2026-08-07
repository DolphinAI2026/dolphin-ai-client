# Standalone Builder AI Runtime Consumption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Design spec:** `docs/superpowers/specs/2026-08-07-standalone-builder-ai-control-plane-design.md`

**Goal:** 让 standalone Builder 的模型、MCP、Skill 和知识工具全部消费独立 Control Plane 的同一份 tenant runtime catalog，并在该 profile 下彻底禁用旧事实源回退。

**Architecture:** 新增 `backend/app/standalone_ai/**`，由唯一 `StandaloneAiCatalogClient` 通过 tenant-bound Control Plane session token 与内部 service token 获取 ETag catalog。每个新会话和新用户 turn 创建不可变 `StandaloneAiRuntimeSnapshot`，模型 resolver、MCP、Skill、Knowledge 只读取该 snapshot；内置 Builder 工具/Skill 单独合并且优先。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy async、Pydantic v2、httpx、cryptography、pytest/pytest-asyncio、Vue 3、TypeScript、Vitest。

## Global Constraints

- standalone profile 名固定为 `standalone_builder_ai`，并且只连接 standalone Control Plane。
- Control Plane base URL、internal tokenId/token 只来自服务端配置，浏览器不得提交或读取。
- 内部请求同时发送 tenant-bound session token、`X-Builder-Internal-Token-Id` 和 `X-Builder-Internal-Token`。
- runtime cache key 固定为 `tenantId + catalogVersion`，TTL 30 秒；单 turn 使用不可变 snapshot。
- 新对话创建前、每个新用户 turn 前、TTL 到期时重验；不可无限使用 stale cache。
- standalone profile 禁止 DB 模型、模型 env、租户 MCP env、宿主租户 Skill、Builder knowledge 表和公共 catalog client 回退。
- 内置 Builder 工具/Skill 保留并标记 `builtin=true`；同名冲突时内置优先。
- runtime catalog 明文凭据不得写日志、数据库、审计、异常或调试文件。
- Skill 缓存路径必须包含 `tenantId/versionId/checksum`；先临时文件、校验 SHA-256、再原子替换。
- 新增或重构代码文件不得超过 500 行；`agent.py`、`llm_configs.py`、`mcp_bridge.py` 只保留薄接线。
- 只增加本计划列出的专项测试，不扩张为 Builder 全量测试。

---

### Task 1: 建立 standalone profile、Control Plane session bridge 和启动硬门禁

**Files:**
- Create: `backend/app/standalone_ai/__init__.py`
- Create: `backend/app/standalone_ai/config.py`
- Create: `backend/app/standalone_ai/errors.py`
- Create: `backend/app/standalone_ai/session_client.py`
- Create: `backend/app/standalone_ai/session_store.py`
- Create: `backend/app/models/standalone_ai_session.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/database.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/routes/auth/login.py`
- Create: `backend/app/routes/auth/logout.py`
- Modify: `backend/app/routes/auth/__init__.py`
- Create: `backend/tests/test_standalone_ai_profile.py`
- Create: `backend/tests/test_standalone_ai_session_bridge.py`

**Interfaces:**
- Consumes: Builder aPaaS 登录的 username/password/已选择 `apaasTenantId`，standalone Control Plane `/api/auth/**`。
- Produces: `StandaloneAiSettings`；`StandaloneAiSessionStore.require(user_id, apaas_tenant_id)`；服务器端加密的 opaque Control Plane session。

- [ ] **Step 1: 写 profile guard 与 session bridge 失败测试**

```python
class StandaloneAiSettings(BaseModel):
    enabled: bool = False
    control_plane_url: AnyHttpUrl | None = None
    internal_token_id: SecretStr | None = None
    internal_token: SecretStr | None = None
    catalog_ttl_seconds: int = 30
    skill_cache_dir: Path = Path("/data/standalone-ai/skills")
```

测试证明：enabled 时缺 URL/token、URL 指向公共 Control Plane、TTL 不等于 30、复用 `DOLPHIN_CODE_CONTROL_PLANE_URL/TOKEN` 都启动失败；aPaaS 登录完成后服务端建立 standalone session，明文 token 不进入 Builder JWT/响应/日志；logout 删除 session。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && pytest tests/test_standalone_ai_profile.py tests/test_standalone_ai_session_bridge.py -q`

Expected: FAIL，因为 standalone profile 与 session bridge 尚不存在。

- [ ] **Step 3: 实现独立配置和稳定错误**

新增配置字段：

```text
STANDALONE_AI_ENABLED
STANDALONE_AI_CONTROL_PLANE_URL
STANDALONE_AI_INTERNAL_TOKEN_ID
STANDALONE_AI_INTERNAL_TOKEN
STANDALONE_AI_CATALOG_TTL_SECONDS=30
STANDALONE_AI_SKILL_CACHE_DIR=/data/standalone-ai/skills
```

`StandaloneAiError` 固定包含 `code,message,trace_id,status_code`，禁止把 upstream body 或 headers 直接写入 message。

- [ ] **Step 4: 实现登录时 session bridge**

Builder 已验证 aPaaS 登录且已选 tenant 后，`StandaloneAiSessionClient` 获取 login key、RSA 加密同一请求内密码，并调用 Control Plane login（显式传 `apaasTenantId`）。只把 opaque session token、tenant、expiresAt 加密保存到 `standalone_ai_sessions`；不保存密码、不把 token放进浏览器 JWT。

```python
class StandaloneAiSessionStore(Protocol):
    async def put(self, user_id: int, tenant_id: str, token: str, expires_at: datetime) -> None: ...
    async def require(self, user_id: int, tenant_id: str) -> str: ...
    async def revoke(self, user_id: int, tenant_id: str) -> None: ...
```

standalone enabled 时 session bridge 失败必须使登录 fail-closed；不允许继续进入一个无法获取 AI catalog 的半成品 Builder。

- [ ] **Step 5: 运行专项测试并提交**

Run: `cd backend && pytest tests/test_standalone_ai_profile.py tests/test_standalone_ai_session_bridge.py -q`

Expected: PASS。

```bash
git add backend/app/standalone_ai backend/app/models backend/app/database.py \
  backend/app/config.py backend/app/routes/auth/login.py backend/app/routes/auth/logout.py \
  backend/app/routes/auth/__init__.py \
  backend/tests/test_standalone_ai_profile.py backend/tests/test_standalone_ai_session_bridge.py
git commit -m "feat(builder-ai): add standalone runtime profile"
```

### Task 2: 实现唯一 Catalog Client、ETag cache 和不可变 turn snapshot

**Files:**
- Create: `backend/app/standalone_ai/catalog_types.py`
- Create: `backend/app/standalone_ai/catalog_client.py`
- Create: `backend/app/standalone_ai/catalog_cache.py`
- Create: `backend/app/standalone_ai/runtime_snapshot.py`
- Create: `backend/app/standalone_ai/runtime_context.py`
- Create: `backend/tests/test_standalone_ai_catalog_client.py`
- Create: `backend/tests/test_standalone_ai_catalog_cache.py`
- Create: `backend/tests/test_standalone_ai_runtime_snapshot.py`

**Interfaces:**
- Consumes: Task 1 `session_store.require()` 和 internal token settings。
- Produces: `StandaloneAiCatalogClient.fetch(context, etag)`；`StandaloneAiCatalogCache.resolve(context)`；`bind_runtime_snapshot(snapshot)` context manager。

- [ ] **Step 1: 写 ETag、304 缺 cache、TTL 和 tenant 隔离失败测试**

```python
@dataclass(frozen=True)
class StandaloneAiRequestContext:
    user_id: int
    tenant_id: str
    trace_id: str

@dataclass(frozen=True)
class StandaloneAiRuntimeSnapshot:
    tenant_id: str
    catalog_version: int
    default_model_id: str | None
    models: tuple[RuntimeModel, ...]
    mcp_servers: tuple[RuntimeMcpServer, ...]
    skills: tuple[RuntimeSkill, ...]
    conflicts: tuple[RuntimeConflict, ...]
    loaded_at: datetime
```

`RuntimeModel.api_key` 和 MCP 敏感 header 使用 `SecretStr`/自定义 redacted mapping，`repr()` 与 validation error 不得包含明文。覆盖 200、304、ETag mismatch、304 但本地无 tenant/version cache 时无条件重取一次、二次仍 304 报协议错误、TTL 到期 CP 不可达、tenant A/B 不共享、catalog version 更新后新 snapshot、旧 turn snapshot 不变。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && pytest tests/test_standalone_ai_catalog_client.py tests/test_standalone_ai_catalog_cache.py tests/test_standalone_ai_runtime_snapshot.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现 typed client 和双认证 header**

唯一允许路径：

```text
GET /internal/builder-ai/runtime-catalog
GET /internal/builder-ai/skills/{versionId}/artifact
GET /internal/builder-ai/knowledge/manifest
POST /internal/builder-ai/knowledge/search
GET /internal/builder-ai/knowledge/documents/{documentId}
```

每个请求发送 bearer session、内部 tokenId/token、`X-Trace-Id`；不接受 caller 提供 tenantId。httpx 日志 hook 必须删除 Authorization、internal token 和 response body。

- [ ] **Step 4: 实现两级索引的 30 秒 cache**

cache 保存 `latest_etag_by_tenant` 与 `(tenant_id,catalog_version) -> snapshot`；每次 resolve 先按 TTL 判定是否重验。304 命中返回相同 immutable snapshot；200 按 Pydantic 严格校验后原子更新两级索引。Control Plane 不可达且 TTL 已过映射 `BUILDER_AI_RUNTIME_CATALOG_UNAVAILABLE`。

- [ ] **Step 5: 实现 turn context**

使用 `contextvars.ContextVar[StandaloneAiRuntimeSnapshot | None]`；新 turn 开始 bind，结束 finally reset。工具与 resolver 只调用 `require_runtime_snapshot()`，不能自行重新拉 catalog，保证 turn 内一致。

- [ ] **Step 6: 运行专项测试并提交**

Run: `cd backend && pytest tests/test_standalone_ai_catalog_client.py tests/test_standalone_ai_catalog_cache.py tests/test_standalone_ai_runtime_snapshot.py -q`

Expected: PASS。

```bash
git add backend/app/standalone_ai/catalog_types.py backend/app/standalone_ai/catalog_client.py \
  backend/app/standalone_ai/catalog_cache.py backend/app/standalone_ai/runtime_snapshot.py \
  backend/app/standalone_ai/runtime_context.py backend/tests/test_standalone_ai_catalog_client.py \
  backend/tests/test_standalone_ai_catalog_cache.py backend/tests/test_standalone_ai_runtime_snapshot.py
git commit -m "feat(builder-ai): cache immutable standalone catalog snapshots"
```

### Task 3: 替换模型 options、会话选择和所有 standalone 模型 resolver

**Files:**
- Create: `backend/app/standalone_ai/model_resolver.py`
- Create: `backend/app/standalone_ai/turn_runtime.py`
- Modify: `backend/app/routes/llm_configs.py`
- Modify: `backend/app/harness/llm_resolver.py`
- Modify: `backend/app/ai_chat/agent.py`
- Modify: `backend/app/agents/coding/llm_config.py`
- Modify: `backend/app/coding/pipeline.py`
- Modify: `backend/app/models/ai_chat.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/database.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/routes/ai_chat.py`
- Modify: `backend/app/routes/conversations.py`
- Modify: `backend/app/routes/coding.py`
- Modify: `backend/app/routes/code_runtime.py`
- Modify: `frontend/src/api/llmConfig.ts`
- Modify: `frontend/src/api/aiChat.ts`
- Modify: `frontend/src/api/coding.ts`
- Modify: `frontend/src/api/conversation.ts`
- Modify: `frontend/src/types/index.ts`
- Create: `frontend/src/utils/modelSelection.ts`
- Create: `frontend/src/utils/modelSelection.spec.ts`
- Modify: `frontend/src/views/ChatPage.vue`
- Modify: `frontend/src/views/AIChatPage.vue`
- Modify: `frontend/src/views/CodingPage.vue`
- Modify: `frontend/src/views/coding/useCodingModel.ts`
- Create: `backend/tests/test_standalone_ai_model_resolution.py`
- Create: `backend/tests/test_standalone_ai_turn_binding.py`
- Create: `frontend/src/api/llmConfig.standalone.spec.ts`

**Interfaces:**
- Consumes: Task 2 snapshot。
- Produces: `resolve_standalone_model(snapshot, selected_model_id)`；`selected_runtime_model_id: str | null`；兼容的 `/llm-configs/options` 浏览器响应。

- [ ] **Step 1: 写无 DB/env fallback 和字符串模型 ID 失败测试**

Control Plane catalog ID 按规格保留 string，不把 `"model-1"` 哈希为旧整数。测试覆盖默认模型、显式选择 enabled 模型、选择已删除/disabled 时回默认、无默认模型 `BUILDER_AI_MODEL_NOT_CONFIGURED`、catalog unavailable、API Key 不出日志，以及 standalone 下 DB/env resolver spy 调用次数为 0。

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
cd backend && pytest tests/test_standalone_ai_model_resolution.py tests/test_standalone_ai_turn_binding.py -q
cd ../frontend && npm test -- --run src/api/llmConfig.standalone.spec.ts src/utils/modelSelection.spec.ts
```

Expected: FAIL。

- [ ] **Step 3: 增加非破坏性的 runtime model selection 字段**

给 AIChatSession/Conversation 增加 nullable Text `selected_runtime_model_id`，保留旧 `selected_llm_config_id` 供非 standalone profile。API schema 同时返回两者；standalone 请求只读写 string 字段，legacy 行为不变。

```python
class RuntimeModelSelection(BaseModel):
    selected_runtime_model_id: str | None = None
```

前端 `BuilderModelOption.id` 改为 `string | number`，standalone option 使用 string；legacy option 仍是 number。新增 `ModelSelectionId = string | number`、`sameModelSelection(a,b)` 和 `serializeModelSelection(id)`；Chat/AIChat/Coding 选择器按 `String(id)` 比较，不把 standalone ID 转 Number。standalone 请求写 `selected_runtime_model_id`，legacy 请求继续写 `selected_llm_config_id`。

- [ ] **Step 4: 实现 catalog model resolver 与 options projection**

`/llm-configs/options?purpose=builder|coding` 在 standalone profile 从 snapshot 返回：

```json
[{"id":"model-1","config_name":"Default","provider":"standalone","model":"gpt-compatible","purpose":"builder","is_default":true}]
```

CRUD/test/presets 管理接口在 standalone profile 返回 404 `BUILDER_AI_MANAGEMENT_MOVED`，避免 Builder 成为模型事实源。

- [ ] **Step 5: 在新会话和每个新 turn 绑定 snapshot**

`turn_runtime.py` 从已鉴权 user/session 构建 request context，调用 cache.resolve 后 bind context。`ai_chat/agent.py`、coding pipeline 只增加薄 `async with standalone_turn_runtime(...)` 接线；title generation 与正式 turn 都使用各自开始时 snapshot。

- [ ] **Step 6: 切换所有 standalone resolver**

`harness/llm_resolver.py` 和 `agents/coding/llm_config.py` 在 standalone enabled 时直接调用 `resolve_standalone_model`，禁止捕获异常后落入 DB/env；非 standalone 分支保持现状。返回现有调用方需要的 `base_url,api_key,model,max_tokens,temperature` immutable view。

- [ ] **Step 7: 运行专项测试并提交**

Run:

```bash
cd backend && pytest tests/test_standalone_ai_model_resolution.py tests/test_standalone_ai_turn_binding.py -q
cd ../frontend && npm test -- --run src/api/llmConfig.standalone.spec.ts src/utils/modelSelection.spec.ts
```

Expected: PASS。

```bash
git add backend/app/standalone_ai/model_resolver.py backend/app/standalone_ai/turn_runtime.py \
  backend/app/routes/llm_configs.py backend/app/harness/llm_resolver.py backend/app/ai_chat/agent.py \
  backend/app/agents/coding/llm_config.py backend/app/coding/pipeline.py backend/app/models \
  backend/app/database.py backend/app/schemas.py backend/app/routes/ai_chat.py \
  backend/app/routes/conversations.py backend/app/routes/coding.py backend/app/routes/code_runtime.py \
  backend/tests/test_standalone_ai_model_resolution.py backend/tests/test_standalone_ai_turn_binding.py \
  frontend/src/api frontend/src/types/index.ts frontend/src/utils/modelSelection.ts \
  frontend/src/utils/modelSelection.spec.ts frontend/src/views/ChatPage.vue \
  frontend/src/views/AIChatPage.vue frontend/src/views/CodingPage.vue \
  frontend/src/views/coding/useCodingModel.ts
git commit -m "feat(builder-ai): resolve standalone catalog models"
```

### Task 4: 用 snapshot 替换租户 MCP，并保留内置工具优先

**Files:**
- Create: `backend/app/standalone_ai/mcp_runtime.py`
- Modify: `backend/app/ai_chat/mcp_bridge.py`
- Modify: `backend/app/ai_chat/tools.py`
- Create: `backend/tests/test_standalone_ai_mcp_runtime.py`
- Modify: `backend/tests/test_mcp_envelope.py`

**Interfaces:**
- Consumes: current snapshot `mcp_servers` 与 builtin tool schemas/handlers。
- Produces: `StandaloneMcpRuntime.tool_schemas()`；`invoke(tool_name,args)`；冲突中 builtin winner。

- [ ] **Step 1: 写 tools/list、invoke 隔离和无 env fallback 测试**

覆盖 streamable HTTP/SSE `tools/list`、两个 MCP 合并、同名租户工具首个稳定 winner、与 builtin 同名时 builtin winner、单服务 invoke 失败只返回 `BUILDER_AI_MCP_UNAVAILABLE`、其他 MCP 仍可用、日志/header 脱敏；standalone 下 `_configured_base_urls`、`MCP_API_KEYS`、页面配置 key 和 in-process tenant fallback 调用次数为 0。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && pytest tests/test_standalone_ai_mcp_runtime.py tests/test_mcp_envelope.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现 turn-scoped MCP runtime**

每个 snapshot 创建 tool name -> server projection，只在当前 turn 缓存 schemas。调用使用 catalog URL/Headers/timeout，不注入本地 tenant_id/user_id 到租户远程 MCP 参数。错误返回稳定 JSON envelope：

```json
{"ok":false,"error_code":"BUILDER_AI_MCP_UNAVAILABLE","message":"MCP 服务暂时不可用","tool_name":"crm.search","trace_id":"..."}
```

- [ ] **Step 4: 把旧 bridge 降为 profile router**

`mcp_bridge.py` 新增 standalone 分支后立即 return `StandaloneMcpRuntime`，不执行 dotenv、环境 key、公共页面配置或 in-process tenant fallback。非 standalone 分支保持旧行为。`tools.py` 先合并 builtin schemas，再加租户 schemas；已有 builtin handler 永远先执行。

- [ ] **Step 5: 运行专项测试并提交**

Run: `cd backend && pytest tests/test_standalone_ai_mcp_runtime.py tests/test_mcp_envelope.py -q`

Expected: PASS。

```bash
git add backend/app/standalone_ai/mcp_runtime.py backend/app/ai_chat/mcp_bridge.py \
  backend/app/ai_chat/tools.py backend/tests/test_standalone_ai_mcp_runtime.py \
  backend/tests/test_mcp_envelope.py
git commit -m "feat(builder-ai): load standalone tenant mcp tools"
```

### Task 5: 实现 Skill 原子下载、checksum cache 和 builtin 合并

**Files:**
- Create: `backend/app/standalone_ai/skill_runtime.py`
- Create: `backend/app/standalone_ai/skill_cache.py`
- Modify: `backend/app/ai_chat/skills.py`
- Modify: `backend/app/ai_chat/agent.py`
- Modify: `backend/app/ai_chat/tools.py`
- Modify: `backend/app/agents/coding/tools.py`
- Create: `backend/tests/test_standalone_ai_skill_runtime.py`
- Modify: `backend/tests/test_skill_manifest_injection.py`

**Interfaces:**
- Consumes: snapshot skills、catalog client artifact download、现有 builtin/preset Skill registry。
- Produces: `StandaloneSkillRuntime.list()`、`materialize(name)`、`read_skill_md(name)`；原子 cache。

- [ ] **Step 1: 写原子缓存、二次失败和 builtin 冲突测试**

覆盖下载到同目录 `.part-uuid`、header/body SHA-256 一致、校验失败删除并无条件重试一次、二次失败 `BUILDER_AI_SKILL_ARTIFACT_INVALID`、Zip Slip/符号链接/超大展开拒绝、并发同版本只落一份、tenant A/B 分离、builtin 同名优先且 `builtin=true`。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && pytest tests/test_standalone_ai_skill_runtime.py tests/test_skill_manifest_injection.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现 checksum cache 和安全解压**

cache 路径固定：

```text
<skill_cache_dir>/<safeTenantHash>/<versionId>/<sha256>/
```

tenant 目录用不可逆 hash，目录内写 `artifact.zip`、解压内容和 `READY` manifest；完成前不对 reader 可见。锁粒度为 tenant/version/checksum。失败删除临时文件，不记录 ZIP/body。

- [ ] **Step 4: 实现 runtime registry 和现有入口接线**

standalone 时 `SkillRegistry.scan/get/read_skill_md` 委托 runtime registry；禁止扫描 `RUIJING_SKILLS_DIR`、desktop/server tenant skill 目录。平台内置/preset Skill 仍从受信目录读取，先放入 by-name map，租户 Skill 使用 `setdefault`，不能覆盖。

- [ ] **Step 5: 让 use_skill 和 manifest 使用同一 snapshot**

`agent.py` manifest、`ai_chat/tools.py::execute_use_skill`、`agents/coding/tools.py::_use_skill` 全部从当前 turn snapshot 的 runtime registry 取同一版本；materialize 后只复制到当前 workspace，不能修改 cache。

- [ ] **Step 6: 运行专项测试并提交**

Run: `cd backend && pytest tests/test_standalone_ai_skill_runtime.py tests/test_skill_manifest_injection.py -q`

Expected: PASS。

```bash
git add backend/app/standalone_ai/skill_runtime.py backend/app/standalone_ai/skill_cache.py \
  backend/app/ai_chat/skills.py backend/app/ai_chat/agent.py backend/app/ai_chat/tools.py \
  backend/app/agents/coding/tools.py backend/tests/test_standalone_ai_skill_runtime.py \
  backend/tests/test_skill_manifest_injection.py
git commit -m "feat(builder-ai): consume standalone skill artifacts"
```

### Task 6: 用内部 Knowledge API 替换 Builder 知识表

**Files:**
- Create: `backend/app/standalone_ai/knowledge_runtime.py`
- Modify: `backend/app/ai_chat/agent.py`
- Modify: `backend/app/ai_chat/tools.py`
- Modify: `backend/app/knowledge_base.py`
- Modify: `backend/app/routes/knowledge.py`
- Create: `backend/tests/test_standalone_ai_knowledge_runtime.py`
- Modify: `backend/tests/test_knowledge_manifest_inject.py`
- Modify: `backend/tests/test_knowledge_tools.py`

**Interfaces:**
- Consumes: catalog client knowledge manifest/search/document endpoints 与 current snapshot context。
- Produces: prompt manifest；`search_knowledge`、`read_knowledge` 的 standalone 实现。

- [ ] **Step 1: 写 manifest/search/document 和无 DB fallback 测试**

覆盖 manifest 只含 enabled/published 摘要、search query/limit/knowledgeBaseIds、空 hits、稳定 hit 字段、read published document、tenant mismatch 404、服务不可用 `BUILDER_AI_KNOWLEDGE_UNAVAILABLE`；standalone 下 `KnowledgeDoc` repository 调用次数为 0。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && pytest tests/test_standalone_ai_knowledge_runtime.py tests/test_knowledge_manifest_inject.py tests/test_knowledge_tools.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现内部 Knowledge adapter**

```python
class StandaloneKnowledgeRuntime:
    async def manifest(self) -> KnowledgeManifest: ...
    async def search(self, query: str, limit: int = 10,
                     knowledge_base_ids: tuple[str, ...] = ()) -> tuple[KnowledgeHit, ...]: ...
    async def document(self, document_id: str) -> PublishedDocument: ...
```

所有调用复用 Task 2 client headers/trace；无命中返回空 tuple，网络/5xx 映射 unavailable，不把空命中当故障。

- [ ] **Step 4: 切换 prompt 与工具 dispatcher**

standalone 时 `_append_knowledge_manifest` 调内部 manifest；`search_knowledge` 返回 hit 摘要并引导按 `documentId` 读取；`read_knowledge` 接受 `document_id`。工具 schema 在 standalone profile 使用 `document_id`，legacy profile 保持 slug。

- [ ] **Step 5: 冻结 Builder knowledge 写面**

standalone 下 `/knowledge` 管理 CRUD 返回 404 `BUILDER_AI_MANAGEMENT_MOVED`，不读取/写入 Builder knowledge 表；非 standalone 保持现有行为。

- [ ] **Step 6: 运行专项测试并提交**

Run: `cd backend && pytest tests/test_standalone_ai_knowledge_runtime.py tests/test_knowledge_manifest_inject.py tests/test_knowledge_tools.py -q`

Expected: PASS。

```bash
git add backend/app/standalone_ai/knowledge_runtime.py backend/app/ai_chat/agent.py \
  backend/app/ai_chat/tools.py backend/app/knowledge_base.py backend/app/routes/knowledge.py \
  backend/tests/test_standalone_ai_knowledge_runtime.py \
  backend/tests/test_knowledge_manifest_inject.py backend/tests/test_knowledge_tools.py
git commit -m "feat(builder-ai): consume standalone knowledge runtime"
```

### Task 7: 完成全链路错误、秘密 canary、无旧事实回退和部署接线

**Files:**
- Create: `backend/app/standalone_ai/observability.py`
- Create: `backend/app/standalone_ai/startup_guard.py`
- Create: `backend/tests/test_standalone_ai_no_legacy_fallback.py`
- Create: `backend/tests/test_standalone_ai_secret_canary.py`
- Create: `backend/tests/test_standalone_ai_runtime.py`
- Create: `backend/tests/fixtures/standalone_ai_catalog.json`
- Create: `deploy/k8s/standalone-ai/30-builder-statefulset.yaml`
- Create: `deploy/k8s/standalone-ai/40-builder-service.yaml`
- Create: `deploy/k8s/standalone-ai/50-builder-ingress.yaml`
- Create: `deploy/k8s/standalone-ai/kustomization.yaml`
- Create: `deploy/k8s/standalone-ai/README.md`
- Create: `scripts/verify_standalone_ai_runtime.sh`

**Interfaces:**
- Consumes: 完整 standalone client/cache/model/MCP/Skill/Knowledge runtime。
- Produces: 可激活的 standalone Builder 部署、有限基数指标和零 fallback 证据。

- [ ] **Step 1: 写猴子补丁式 no-fallback 和 secret canary 测试**

把 DB model resolver、模型 env、MCP env/page key、in-process tenant MCP、宿主 tenant Skill、Builder knowledge repository、public catalog client 全部替换为“调用即失败”的 spy；运行新会话、两个 turn、模型调用、MCP、Skill、Knowledge，断言 spy 调用次数均为 0。

catalog 中注入 `SECRET_CANARY_BUILDER_AI_20260807` 到 apiKey/header/session token，断言日志、异常、SSE error、数据库 SQL 参数快照、pytest capture 和生成文件均不包含 canary。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && pytest tests/test_standalone_ai_no_legacy_fallback.py tests/test_standalone_ai_secret_canary.py tests/test_standalone_ai_runtime.py -q`

Expected: 初次至少一项 FAIL，直到所有旧回退被 profile router 截断。

- [ ] **Step 3: 统一错误映射和指标**

对外固定映射：

```text
BUILDER_AI_RUNTIME_CATALOG_UNAVAILABLE
BUILDER_AI_MODEL_NOT_CONFIGURED
BUILDER_AI_MCP_UNAVAILABLE
BUILDER_AI_SKILL_ARTIFACT_INVALID
BUILDER_AI_KNOWLEDGE_UNAVAILABLE
```

日志只含 `traceId,tenantIdHash,userIdHash,catalogVersion,operation,outcome`；指标只使用 `outcome/resource_type` 有限枚举，不能用 tenant/model/skill ID 做 label。

- [ ] **Step 4: 实现启动期事实源硬门禁**

`startup_guard.py` 在 standalone enabled 时检查旧 catalog/public Control Plane URL 不得配置为 active，禁止 model/MCP/tenant Skill/knowledge fallback flags；检查 skill cache 可写且不在源码目录；缺内部 token 直接拒绝启动。

- [ ] **Step 5: 接入独立 K8s 配置**

新目录中的 StatefulSet 使用 standalone 专用 ConfigMap/Secret，环境变量只引用 Task 1 的字段；Service/Ingress 不暴露任何 internal token。不得修改现有 `deploy/k8s/30-statefulset.yaml`、`40-service.yaml`、`50-ingress.yaml` 或公共 Builder values。部署文档记录 token rotation 先 next 后 current，不记录值。

- [ ] **Step 6: 编写专项运行脚本**

脚本执行：aPaaS 登录建立 CP session；新会话预取；304 有 cache；304 无 cache 无条件重取；catalog 版本更新后下一 turn 切换；模型真实响应；MCP tools/list + invoke 失败隔离；Skill 下载/use/checksum；Knowledge search/document；Control Plane 停止且 TTL 到期 fail-closed；公共 request sentinel=0。

- [ ] **Step 7: 运行最终专项门禁并提交**

Run:

```bash
cd backend && pytest \
  tests/test_standalone_ai_catalog_client.py \
  tests/test_standalone_ai_catalog_cache.py \
  tests/test_standalone_ai_runtime_snapshot.py \
  tests/test_standalone_ai_model_resolution.py \
  tests/test_standalone_ai_mcp_runtime.py \
  tests/test_standalone_ai_skill_runtime.py \
  tests/test_standalone_ai_knowledge_runtime.py \
  tests/test_standalone_ai_no_legacy_fallback.py \
  tests/test_standalone_ai_secret_canary.py \
  tests/test_standalone_ai_runtime.py -q
cd ../frontend && npm test -- --run src/api/llmConfig.standalone.spec.ts src/utils/modelSelection.spec.ts
bash ../scripts/verify_standalone_ai_runtime.sh --config-only
```

Expected: PASS；配置扫描中公共 URL/旧事实源计数为 0。

```bash
git add backend/app/standalone_ai backend/tests/test_standalone_ai_* \
  backend/tests/fixtures/standalone_ai_catalog.json deploy/k8s scripts/verify_standalone_ai_runtime.sh
git commit -m "feat(builder-ai): gate standalone catalog consumption"
```

## Final Cross-Repository Gate

- [ ] Control Plane 管理面、内部 API、Web Console 六页和 Builder 四类消费同时完成前，standalone Builder route 保持关闭。
- [ ] 使用真实 admin/member/tenant A/B 会话验证 Builder 只能看到当前 tenant catalog。
- [ ] 在单个 turn 中更新 catalog，证明当前 turn 仍用旧 immutable snapshot、下一 turn 使用新版本。
- [ ] 停止公共 Control Plane/Full Workspace，清空 standalone cache 后四类真实链路仍成功；停止 standalone Control Plane 且 TTL 到期后 fail-closed。
- [ ] Secret canary 不出现在 Builder 响应、SSE、日志、数据库、缓存元数据或 workspace 文件。
- [ ] 激活提交独立于功能提交：`git commit -m "deploy(builder-ai): activate standalone runtime catalog"`。
