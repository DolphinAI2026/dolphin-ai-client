# AI Coding bound 会话「先读应用上下文再写 SPEC」设计 spec

> **状态**:设计已与大明哥对齐(2026-06-02,选定 **3b 局部 tool-loop**)。待 review → 出实施计划。
> **缘由**:分场景入口选了「在应用上定制」的目标应用后,codegen 首轮直接凭 userprompt 脑补 SPEC(如「设计一个首页」→ 通用「工作台首页」),**完全没读所选应用的真实模型/菜单** →「选了应用等于白选」。目标:让 bound 首轮**先调读工具了解所选应用**,再基于「应用信息 + 用户需求」写 SPEC 和后续代码。

## 现状:app_id 被丢 3 层 + SPEC 步骤非 tool

1. 前端已发 `app_id`(上一轮 boundAppId 修复),但 `CodingPipelineRequest`([harness.py:157](../../../backend/app/routes/harness.py))**无 `app_id` 字段** → Pydantic 在 API 边界丢掉。
2. `PipelineParams`([pipeline.py:56](../../../backend/app/coding/pipeline.py))**无 `app_id` 字段** → 管线只认 `project_id`(场景入口为空)。
3. `run_coding_pipeline` 首轮 brainstorm(pipeline.py `elif not is_iteration and scene_type in BRAINSTORM_SCENES:`)调 `_generate_brainstorm_proposal` —— **单次 LLM 调用、不带工具** → agent 没法自己「先调获取应用的工具」。

**现成可复用(关键):**
- [`read_query.py`](../../../backend/app/coding/read_query.py)(v2 读路径)已是完整范式:**LLM + apaas 读工具 + tool-loop(`tool_choice:auto` → 解析 `tool_calls` → 执行 → 喂回)+ 工具白名单 + emit 步骤事件**。bound grounding 就是「read_query 式的循环 + 末轮输出 SPEC」。
- [`apaas_tools.py`](../../../backend/app/coding/apaas_tools.py):`_list_apaas_app_models` / `_list_apaas_app_menus`(签名 `(args, platform_env_id, db)`,args 带 `apaas_app_id`)+ `call_apaas_with_relogin`(token 自愈)。
- `load_coding_llm_config(tenant_id, selected_model)`(`app/agents/coding/llm_config.py`)拿 base_url/api_key/model。
- harness `app_id` 透传路径:`CodingPipelineRequest` → `metadata` dict → `HarnessManager.create_thread(metadata=…)` → coding profile runner 构造 `PipelineParams`(现 `project_id` 即走此路)。

## 已对齐决策

1. **落法 = 3b**(在 bound brainstorm 加局部 tool-loop),**不接 v2 `BrainstormAgent`**(它没接进老管线;接 = 把 v2 agent 栈塞进缠绕的老管线,牵连面大)。
2. **范围**:只在 **bound(app_id 解析到平台应用)+ build 场景 + 首轮**做;改稿轮 / lib / read 路径**不动**。
3. **解析不到应用**(没部署/没环境/缺字段)→ **优雅退回现状**(走旧 `_generate_brainstorm_proposal`),不硬报错。
4. **apaas_app_id 锁定**:grounding 工具的 `apaas_app_id` 由后端注入为解析到的值,agent **不能查别的应用**(安全 + 正确性)。

## 设计

### ① 透传 app_id(3 层接线)
- `CodingPipelineRequest` + `IDECodingPipelineRequest`([harness.py](../../../backend/app/routes/harness.py))加 `app_id: str | None = None`。
- `coding_pipeline` 的 `metadata` dict 加 `"app_id": req.app_id`(与现有 `project_id` 并列)。
- coding profile runner [`app/harness/profiles/coding.py:78`](../../../backend/app/harness/profiles/coding.py) 构造 `PipelineParams` 处加 `app_id=meta.get("app_id")`(与 `project_id=meta.get("project_id")` 并列,line 85)。
- `PipelineParams`([pipeline.py:56](../../../backend/app/coding/pipeline.py))加 `app_id: Optional[str] = None`。
> 前端 `buildPipelineRequest` 已带 `app_id`,**请求侧无需再改**。

### ② 解析应用句柄
新 helper `_resolve_bound_app(tenant_id, app_id, db) -> Optional[tuple[str, int, str]]`:
- 查 `Application`(`id == app_id` 且租户作用域)→ 取 `platform_app_id`(= apaas_app_id)、`platform_env_id`、应用名。
- 缺 `platform_app_id` 或 `platform_env_id` → 返回 `None`(调用方退回现状)。

### ③ bound 首轮 grounding tool-loop(核心)
分支点:首轮 brainstorm 分支内,先判 `params.app_id` + `_resolve_bound_app`:
- **解析不到** → 走现有 `_generate_brainstorm_proposal`(完全不变)。
- **解析到** → 走新 `_grounded_brainstorm(params, scene_type, apaas_app_id, platform_env_id, app_name, db)`(async generator,复用 read_query tool-loop 范式):
  - `messages`:system =「你在给应用「{app_name}」做自开发。**先调用读工具**了解它的数据模型 / 菜单(必要时更多),再**只输出**结构化开发 SPEC(沿用现有 SPEC 模板的章节格式)。」+ user(`params.message`)。
  - `tools` = `list_apaas_app_models` / `list_apaas_app_menus` 的薄封装,**`apaas_app_id` 预锁定**(executor 注入固定 `apaas_app_id` + `platform_env_id`,工具 schema 不暴露 app 入参)。
  - 循环 ≤ `_GROUNDING_MAX_TURNS`(= 4):LLM(`tool_choice:auto`)→ 有 `tool_calls` 就经 `call_apaas_with_relogin` 执行并把结果喂回,**每次 emit** `{"type":"step","step":"read_app_context","status":"running"/"done","data":{...}}`;无 `tool_calls` → `content` 即 SPEC,结束。
  - 工具白名单(同 read_query):agent 调白名单外工具 → 返回拒绝串,不执行。
  - 返回 SPEC markdown → 下游 `_parse_brainstorm_metadata` / `save_coding_message` / `effective_requirement` 注入 codegen **全不变**。
  - **兜底**:循环跑完没拿到 SPEC / LLM 抛错 → 退回 `_generate_brainstorm_proposal`。

### ④ codegen 也带应用上下文
grounding 期间拉到的模型/菜单**摘要**,附进 `effective_requirement`(现把 SPEC 注入 codegen 的同一处),让 `generate` 步也基于真实模型/接口。(generate agent 若本就挂了 apaas 读工具,可按需深挖;此处保底注入摘要。)

### ⑤ 可见步骤(对齐「进来第一件事是读应用」)
前端 `useCodingPipeline.ts` 的 `STEP_HANDLERS` 加 `read_app_context`(running「正在读取应用「X」上下文…」/ done「已读取 N 模型 / M 菜单」),位置在 `detect_scene` 之后、`brainstorm` 之前。

## 错误处理
- 应用解析不到 / 无 env / 读工具全失败 → 不阻断,退回现状 SPEC + `logger.warning`(可选 emit 一条「未能读取应用上下文,按通用方式生成」)。
- token 失效 → `call_apaas_with_relogin` 自愈(复用)。
- LLM 不支持 tools / 调用报错 → 退回 `_generate_brainstorm_proposal`。
- 循环上限保护,防 agent 死读。

## 测试(pytest,`backend/tests/`)
- `_resolve_bound_app`:有 `platform_app_id`+`platform_env_id` → 返回三元组;缺任一 → `None`;app 不属本租户 → `None`。
- app_id 透传:`CodingPipelineRequest` 带 `app_id` → metadata 带上(端点级 mock,断言 metadata["app_id"])。
- `_grounded_brainstorm`(mock LLM 响应 + mock apaas 执行器):
  - 首响应带 `tool_calls`(list_app_models)→ 执行器被调且 `apaas_app_id` 为锁定值 → 结果喂回 → 次响应无 `tool_calls` 输出 SPEC → 返回该 SPEC,且 emit 过 `read_app_context` running/done。
  - 白名单:agent 调非白名单工具 → 被拒,不执行。
  - 兜底:LLM 始终不出 SPEC / 抛错 → 回退 `_generate_brainstorm_proposal` 被调用。
- 分支:`app_id` 解析不到 → 走旧 `_generate_brainstorm_proposal`,不进 grounding(断言 grounding 未触发)。

## 范围外(本 spec 不做)
- 不接 v2 `BrainstormAgent`(3a)。
- 不改 read / lib / 改稿轮路径。
- 不做应用上下文缓存(首轮现读;后续可加 conversation 级缓存)。
- 不强制首轮全拉接口/枚举/角色(agent 按需调,不一次性塞)。
- mcp-server twin 的 pipeline 是否同源同改 → 本 spec 只动主后端;twin 作为实施后跟进项单独评估。

## 关键文件
- 改:`backend/app/routes/harness.py`(请求模型 + metadata + app_id 透传)、`backend/app/harness/profiles/coding.py:78`(`meta.get("app_id")` → `PipelineParams.app_id`)、`backend/app/coding/pipeline.py`(`PipelineParams.app_id` + 首轮分支 + `_grounded_brainstorm` + `_resolve_bound_app` + `effective_requirement` 注入)。
- 复用:`backend/app/coding/read_query.py`(tool-loop 范式)、`backend/app/coding/apaas_tools.py`(读执行器 + `call_apaas_with_relogin`)、`app/agents/coding/llm_config.py`、`Application` model。
- 前端:`frontend/src/views/coding/useCodingPipeline.ts`(`STEP_HANDLERS` 加 `read_app_context`;app_id 已带,请求不改)。
- 测试:`backend/tests/test_coding_bound_app_grounding.py`(新)。

## 风险 / 约束
- **老 run_coding_pipeline 缠绕**:改动严格局部在「首轮 brainstorm 分支」,不碰 detect_scene / 工作区创建 / codegen 主体。
- **首轮变慢**:多 1 个 LLM round-trip + 1-2 次 apaas 读 → 首轮稍慢(有上限,可接受)。
- **跨应用读防护**:`apaas_app_id` 必须后端锁定,严防 agent 读到别的应用。
- **LLM 工具支持**:依赖租户 coding LLM 支持 function-calling(codegen 已在用 → 成立);不支持时兜底回退。
