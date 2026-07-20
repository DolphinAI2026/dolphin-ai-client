---
asset_kind: business-flow
asset_id: business-flow.tenant-url-resolution
knowledge_level: L3
source_spec_ref: docs/superpowers/specs/2026-07-20-builder-tenant-url-public-uuid-design.md
source_spec_hash: sha256:f5936354b5aacca01dc239092fad4e2f54749b1a2816926c899a2c4860ad93ed
phase_id: 2026-07-20-builder-tenant-url-public-uuid
revision: 1
source_section_refs:
  - "5. 数据模型"
  - "6. API 契约"
  - "7. 前端 URL 状态机"
  - "8. 登录与多租户选择"
  - "9. 主动切租户"
  - "10. Code 深链接与运行时"
  - "14. 可观测性"
  - "15. 兼容、发布与回滚"
  - "16. 验证策略"
relations:
  - type: depends_on
    target: page-interaction.tenant-aware-navigation
  - type: depends_on
    target: page-interaction.tenant-aware-auth-entry
  - type: depends_on
    target: page-interaction.code-tenant-deep-link
---

# 租户 URL 解析与切换流程

## 背景/Context

该流程把租户公共 UUID 的数据库准备、认证投影、路由决议、上下文切换、诊断和发布
证据连接为一个可实施、可回滚的闭环。

## 方案/Solution

服务启动先确保所有租户具有稳定公共 UUID。浏览器登录后以 URL UUID 和可访问租户
列表决议目标，必要时通过原子 switch response 更新上下文。Code 页面在同一守卫后
启动，发布时用前端 build SHA 证明已包含既有鉴权修复。

## flow_model

```yaml
schema_version: flow-model/v1
flow_code: tenant-url-resolution
flow_type: authenticated-navigation
trigger: protected-route-navigation
actors:
  - authenticated-user
  - builder-router
  - builder-auth-api
source_refs:
  - "5. 数据模型"
  - "6. API 契约"
  - "7. 前端 URL 状态机"
operations:
  - operation_id: tenant-public-id.ensure
    trigger: application-startup
    source_sections:
      - "5. 数据模型"
    api_contract:
      status: not_applicable
      evidence: init_db internal startup operation
    client_contract:
      status: not_applicable
      evidence: no browser client before readiness
    table_contract:
      status: covered
      evidence: tenants.public_id strict add, deterministic backfill, validation, unique index
    test_contract:
      status: covered
      evidence: SQLite reentry plus MySQL and PostgreSQL DDL/concurrency tests
    rollback_contract:
      status: covered
      evidence: retain public_id column and values; never regenerate or delete
    audit_contract:
      status: covered
      evidence: backfill totals, failures, conflict numeric tenant IDs
  - operation_id: auth.tenant-context-project
    trigger: login, select tenant, me, or tenant list response
    source_sections:
      - "6. API 契约"
    api_contract:
      status: covered
      evidence: UserInfo, TenantOption, TenantSwitchResponse endpoint matrix
    client_contract:
      status: covered
      evidence: typed frontend User, TenantOption, TenantSwitchResponse
    table_contract:
      status: covered
      evidence: project Tenant.public_id while preserving numeric tenant_id
    test_contract:
      status: covered
      evidence: endpoint schema, nullability, active tenant, compatibility tests
    rollback_contract:
      status: covered
      evidence: old clients ignore additive fields; switch token-only response rejected by new client
    audit_contract:
      status: covered
      evidence: request ID shared by response header, body, and switch log
  - operation_id: tenant-url.resolve
    trigger: navigation to a tenantContext required or none route
    source_sections:
      - "7. 前端 URL 状态机"
    api_contract:
      status: covered
      evidence: auth request whitelist and tenant URL event endpoint
    client_contract:
      status: covered
      evidence: route metadata, canonicalization, rejection, loop and storage-event rules
    table_contract:
      status: not_applicable
      evidence: route resolution has no business persistence
    test_contract:
      status: covered
      evidence: table-driven state machine and complete router.getRoutes classification
    rollback_contract:
      status: covered
      evidence: old frontend ignores tenantId query; tenantless routes remove it
    audit_contract:
      status: covered
      evidence: sampled non-normal tenant_url_resolution event
  - operation_id: tenant-context.switch
    trigger: accessible URL target or tenant menu action
    source_sections:
      - "6. API 契约"
      - "9. 主动切租户"
    api_contract:
      status: covered
      evidence: POST /auth/switch-tenant returns candidate token and user snapshot
    client_contract:
      status: covered
      evidence: switchTenantContext validates before atomic storage commit
    table_contract:
      status: covered
      evidence: active Tenant and UserTenant membership validation
    test_contract:
      status: covered
      evidence: inactive, token-only, UUID mismatch, timeout, and cross-tab cases
    rollback_contract:
      status: covered
      evidence: switch endpoint does not mutate current_app; rejected candidate leaves source token, user, URL, and server slot untouched
    audit_contract:
      status: covered
      evidence: tenant_switch structured log and low-cardinality metrics
  - operation_id: code-auth-fix.publish
    trigger: production frontend release
    source_sections:
      - "10. Code 深链接与运行时"
      - "15. 兼容、发布与回滚"
    api_contract:
      status: covered
      evidence: /api/code/sessions create, activate, and delete use Builder Bearer
    client_contract:
      status: covered
      evidence: Code URL preserves tenantId and agent after tenant resolution
    table_contract:
      status: not_applicable
      evidence: existing Code session persistence contract is unchanged
    test_contract:
      status: covered
      evidence: Playwright forbids /api/code-runtime activation and asserts zero 401
    rollback_contract:
      status: covered
      evidence: frontend-only rollback keeps tenant public IDs and backend additive fields
    audit_contract:
      status: covered
      evidence: builder-build-sha equals deployment revision containing 49a4bef4
```

## 决策依据/Rationale

把 operation contract 放在一个 durable flow 中，可以让实施计划直接拆分数据库、API、
前端守卫、切换和发布任务，同时保持未来无 reload Phase 2 的所有权边界。

## 后续避坑/Lessons

- 不能把 URL UUID 当授权。
- 不能先保存候选 token 再验证目标 snapshot。
- 不能让租户关键迁移走 best-effort DDL。
- 不能让两个标签页自动按各自旧 URL 反向切换。
