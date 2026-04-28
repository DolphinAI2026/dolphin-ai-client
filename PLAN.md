# Enterprise Governance Plan

更新时间：2026-04-23

## 目标

把当前 `ai-builder` 从“共享默认租户 + 粗粒度管理页”收口为企业可落地的控制平面，先解决资源裸露和权限边界错误，再逐步落到项目级协作与统一 `AI Builder` 编排。

## 设计主线

1. 内部组织租户和外部低代码平台租户彻底分层。
2. 权限判断统一按 `组织能力 × 项目角色 × 外部租户授权 × 发布策略` 执行。
3. `智能搭建`、`智能开发` 变成内部能力，用户只面对统一 `AI Builder`。
4. 先止血，再重构，不在当前代码上做无边界扩散。

## Phase 0：止血与最小治理闭环

[x] `backend/app/routes/auth.py`, `backend/app/config.py`, `backend/app/seed_data.py`
自注册默认改为 `isolated_tenant`，新用户不再进入共享 `default` 租户；保留 `invite_only` / `shared_default_tenant` 配置位，便于试用环境与企业环境切换。

[x] `backend/app/routes/platform_envs.py`
平台环境相关接口全部收紧为租户管理员可访问，先把环境元信息、远端应用列表和平台 token 出口关掉。

[x] `backend/app/routes/llm_configs.py`, `backend/app/schemas.py`
模型配置详情列表改为租户管理员可见，普通用户仅保留 `/llm-configs/options` 的只读模型选项；`/auth/me` 回传组织权限，给前端路由和导航收口使用。

[x] `frontend/src/router/index.ts`, `frontend/src/components/GlobalNavRail.vue`, `frontend/src/views/CodingPage.vue`
环境管理页增加管理员路由守卫；非管理员隐藏环境管理入口，并在 Coding 场景里给出“联系管理员配置环境”的受控提示。

验收标准：

1. 新注册账号进入独立租户，不再自动看到旧租户的应用、环境和模型配置。
2. 非租户管理员无法打开 `/platform-envs`，也拿不到平台环境和模型配置详情。
3. 普通用户仍可读取模型选项，不影响 Builder/Coding 模型下拉选择。

## Phase 1：APSB Control Plane IAM

[ ] `backend/app/models/tenant.py`, `backend/app/models/__init__.py`, `backend/app/permissions.py`
新增 `groups / group_members / platform_instances / platform_tenants / platform_credentials / platform_access_grants / project_target_bindings`，把内部组织身份、外部平台租户访问和项目绑定彻底拆开。

[ ] `backend/app/routes/*`, `frontend/src/views/PlatformEnvs.vue`
把当前“环境管理”重构为四个域：平台目录、我的连接、访问授权、项目目标绑定。

[ ] `backend/app/routes/auth.py`, 新增用户/组织管理路由
支持邀请制入租户、组织管理员分配角色、组授权和默认权限策略。

验收标准：

1. 张三和李四可属于同一内部组织，但访问不同外部平台租户。
2. 环境元信息可见、环境可使用、环境凭证可见三者分离。
3. 项目绑定 dev/test/prod 目标租户后，发布动作只从绑定目标读取凭证和策略。

## Phase 2：项目级协作与发布治理

[ ] `backend/app/coding/workspace.py`, `backend/app/routes/coding.py`, `backend/app/routes/projects.py`
工作区从 `user-scoped` 提升到 `project-scoped`，统一 `owner / admin / member / viewer / releaser` 权限边界。

[ ] `backend/app/permissions.py`, `backend/app/harness/models.py`
把发布、删除、环境切换、平台写回全部挂到审批和项目角色上。

[ ] `frontend/src/views/ProjectOverview.vue`, `frontend/src/views/CodingPage.vue`
补项目成员、发布审批、共享工作区入口与状态展示。

验收标准：

1. 同项目成员能共享工作区和交付物，但权限动作受角色控制。
2. 发布到测试/生产环境必须走项目角色和审批 gate。
3. 不再存在“项目可见但工作区不可见”的裂缝。

## Phase 3：统一 AI Builder Orchestrator

[ ] `backend/app/harness/profiles/ai_builder.py`
新增总控 profile，统一承接需求理解、技术路由、Builder/Coding 子任务分发、结果整合和上线流程。

[ ] `backend/app/services/{requirements,builder,coding,platform}/`
把核心逻辑从 route 下沉到 service，避免 route 调 route。

[ ] `frontend/src/views/ChatPage.vue` 或新的统一壳页面
把需求分析、搭建预览、开发工作区、审批与发布整合到一个 `AI Builder Shell`。

验收标准：

1. 用户不需要先判断该走搭建还是开发。
2. 总控 AI 能输出 `requirements_brief / solution_plan / execution_graph / release_candidate`。
3. 构建、开发、整合、上线全链路可回放、可审计、可审批。

## 本周开发顺序

1. 先完成 Phase 0 的回归验证和旧租户迁移策略。
2. 然后进入 Phase 1 的表结构和接口设计。
3. 再做 Phase 2 的 project-scoped workspace。
4. 最后落 Phase 3 的统一编排。
