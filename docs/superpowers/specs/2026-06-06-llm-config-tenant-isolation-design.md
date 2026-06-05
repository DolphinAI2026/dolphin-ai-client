# LLM 配置租户隔离 — 设计文档

日期: 2026-06-06
分支: dev
状态: 待评审

## 背景

`llm_configs` 表用 `tenant_id`(FK→`tenants.id`, not null, indexed)标记每条配置归属的租户。当前全库 4 条配置,分属租户 1/57/39/60,都是 dolphin gpt-5.5(2 条 https / 2 条 http),且 4 条 `is_default` 全为 1。

问题:虽然 `tenant_id` 列存了真实租户,但**所有读取路径都不按它过滤**。

- admin 列表 `GET /llm-configs`([llm_configs.py:186](../../backend/app/routes/llm_configs.py))直接 `select(LLMConfig)` 全表拉,无租户过滤。
- 解析函数 `get_llm_config_for_purpose` / `list_llm_configs_for_purpose` / `get_active_llm_config_by_id*` / `_clear_defaults` / `_assign_replacement_default` 全部**收了 `tenant_id` 参数但 WHERE 里没用**。
- 连命名带 tenant 的 `_list_tenant_coding_model_configs`([coding.py:543](../../backend/app/routes/coding.py))也只是转调 `list_llm_configs_for_purpose`,照样不过滤。

实际效果:全库 69 个租户共用这 4 条的同一个池子。任何租户的 Builder/Coding/ai_chat 会话解析模型时,拿到的是这 4 条里"最新"那条(`created_at desc, id desc`),与自己的 tenant_id 无关。`create_llm_config` 的注释自己也写明 `tenant_id 仅用于兼容现有表结构;LLM 配置按平台级读取和解析`——这是一次没做完的"按租户 → 平台全局"迁移留下的半截子状态。

补充:还有一条非租户的"兜底"路径——`harness/llm_resolver.py` 的 `stream_with_config(config=None)` 在无配置时悄悄回退到 env 变量的 `LLMClient()`([llm_resolver.py:77](../../backend/app/harness/llm_resolver.py))。这不是跨租户借 key,但属于"兜底"行为。

## 决策(已与用户确认)

1. **严格隔离、不兜底**:每个租户只能用自己 `tenant_id` 名下的模型。没配 → 明确报错"请去平台管理配置模型",绝不借别的租户、也不悄悄回退 env 默认。与此前 Coding/Builder 的 A 方案一致。
2. **平台管理员代配 + 租户选择器**:模型配置管理页给 platform_admin 加租户下拉,可切换任意租户为其配模型;tenant_admin 锁定自己租户,只看/只管本租户。

## 改动设计(按层)

### 1. 解析层(真正堵漏)— `routes/llm_configs.py`

给所有 SELECT 加 `LLMConfig.tenant_id == tenant_id` 过滤。调用点签名不变(它们早已传 `ctx.tenant_id`),只改函数内部 WHERE。

- `get_llm_config_for_purpose(db, tenant_id, purpose)`:三段查询(精确 purpose / `purpose="all"` / 兜底任选 active)全部加租户过滤。加过滤后,最后那段兜底自然只在本租户内生效,不再跨租户。
- `list_llm_configs_for_purpose(db, tenant_id, purpose)`:加租户过滤。
- `get_active_llm_config_by_id(db, tenant_id, config_id)` 和 `get_active_llm_config_by_id_for_purpose(...)`:**按 id 查的两个函数必须加 `tenant_id == tenant_id`**,否则租户 A 传租户 B 的 `config_id` 即可借用(会话级 `selected_llm_config_id` 校验路径)。
- `_clear_defaults(db, tenant_id, purpose)`:加租户过滤——"默认唯一"语义从"平台唯一"改为"每租户唯一"。
- `_assign_replacement_default(db, tenant_id, purpose, exclude_id)`:加租户过滤。

### 2. 端点层授权 — `routes/llm_configs.py`

- `GET /llm-configs`:加可选 query `tenant_id`。
  - platform_admin:用 `tenant_id` 过滤指定租户;不传时默认 caller 的 effective tenant。
  - tenant_admin:**忽略入参,强制用自己租户**。
- `POST /llm-configs`(create):`LLMConfigCreate` body 新增可选字段 `tenant_id`。
  - platform_admin:用 body 里的 `tenant_id`(必填校验;指向的租户须存在且活跃)。
  - tenant_admin:服务端强制覆盖为自己的租户,忽略 body 里的 `tenant_id`。
  - 不再无脑 `resolve_effective_tenant_id`。
  - 统一约定:list 走 query `?tenant_id=`,create 走 body 字段,二者都经同一授权 helper 校验。
- `PUT` / `DELETE` / `POST /{id}/test` / `POST /{id}/set-default` / `POST /{id}/status`:**加租户归属校验**——查出 config 后校验 `config.tenant_id` 在 caller 允许范围内(platform_admin 任意;tenant_admin 必须 == 自己),否则返回 404(不泄漏存在性)。这是安全要点,缺了隔离只是视觉的。
- `GET /llm-configs/options`(普通用户只读列表):已走 `resolve_effective_tenant_id` + `list_llm_configs_for_purpose`,解析层加过滤后自动隔离,无需额外改。

授权辅助:抽一个小 helper 判定 caller 对某 `tenant_id` 是否有权(platform_admin → 任意;tenant_admin → 仅自己),供 create/list/mutation 复用。

### 3. 不兜底收口 — `harness/llm_resolver.py` 及 user-facing 链路

按"不兜底",user-facing 的 Builder(run_agent)/ Coding(pipeline)/ ai_chat 在解析返回 None(本租户无模型)时应**明确报错**"请去平台管理配置模型",而非悄悄用 env `LLMClient()`。

- **先核实再改**:memory 提示 Builder/Coding 之前已去过 env 兜底。实现前先确认这三条链路在"无模型"时各自的现状,只改还在悄悄兜底的那几处。
- **scope 边界**:系统内部、非租户会话的任务(如 `ai_doc_parser`、`module_standardizer` 等文档/平台级处理)若依赖 env 默认模型,**保留**——这些不是租户会话,不在"租户隔离"范围内。改动只针对租户用户发起的对话链路。

### 4. 前端 admin 页 — `admin-spa/src/views/LlmConfigs.vue`

- 顶部加租户选择器(`el-select`),数据来自 `GET /auth/tenants`(platform-admin gated,现成,返回 `TenantAdminItem`)。
- `loadConfigs()` 带上选中 `tenant_id`;create/保存 带上 `tenant_id`。
- 选择器默认选平台管理员自己的租户(或第一个活跃租户)。
- 头部"默认: xxx"文案改为"当前租户默认: xxx"。
- (admin-spa 已是 platform_admin 控制台,选择器对所有进入者可见即可;无需额外区分 tenant_admin——tenant_admin 自服务入口若存在则走主前端,本设计的选择器只在 admin-spa。)

## 不做 / 边界

- **不动 schema**:`tenant_id` 列已是 not null + FK,正好用上。
- **无需数据迁移**:存量 4 条各自 `is_default=1`,隔离后"每租户一条 = 一个默认"自动正确。
- 其余 65 租户保持空,登录后 Builder/Coding 提示配模型(符合不兜底)。
- 不做"平台默认池被租户继承"那套(用户已否决兜底)。
- 不做主前端的 tenant_admin 自服务模型配置页(本轮只收口 admin-spa 平台管理页;若未来要 tenant_admin 自服务再单开)。

## 测试

解析层(单测,SQLite StaticPool 共享内存库):

- 租户 A 的 `get_llm_config_for_purpose` / `list_llm_configs_for_purpose` 查不到租户 B 的 config。
- `get_active_llm_config_by_id*` 传跨租户 id 返回 None。
- `_clear_defaults(tenant_id=A)` 只清 A 的默认,不动 B 的。
- 本租户无 config 时 `resolve_llm_config_for_purpose` 返回 None。

端点(集成):

- tenant_admin 列表只见自己租户;带别租户 `tenant_id` 入参被忽略。
- tenant_admin PUT/DELETE 别租户 config → 404。
- platform_admin 带 `tenant_id` 列表/创建落到正确租户。
- platform_admin 切换租户能看到对应租户的配置。

链路:

- 无模型租户发起 Builder/Coding/ai_chat → 返回清晰错误文案,不静默 env 兜底。

## 风险 / 注意

- 后端 `backend/run.py` reload=False,改后端必重启 preview backend 进程才生效。
- 本地 DB 是 SQLite(`/tmp/fb_demo.db`)。
- 第 3 层(env 兜底收口)是最易扩大 scope 的部分,必须先核实现状、只动 user-facing 租户链路,别误伤平台级系统任务。
