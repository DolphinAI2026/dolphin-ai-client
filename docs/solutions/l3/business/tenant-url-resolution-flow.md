---
asset_kind: business-flow
asset_id: business-flow.tenant-url-resolution
knowledge_level: L3
source_spec_ref: docs/superpowers/specs/2026-07-20-builder-tenant-url-public-uuid-design.md
source_spec_hash: sha256:a535c11062500a4d7d88b0ba45bf25fc44dc2465012e2abefa356db7b26887b6
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

服务启动和发布后 reconciliation 确保所有租户具有稳定公共 UUID。浏览器登录后以 URL
UUID 和可访问租户列表决议目标，必要时签发候选 token、显式调用 `/auth/me` 校验，
再提交浏览器上下文。Code 页面在同一守卫后启动，发布时用单镜像 revision 和前端
build SHA 证明已包含既有鉴权修复。

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
  - operation_id: tenant-public-id.expand-reconcile
    trigger: application-startup
    source_sections:
      - "5. 数据模型"
      - "15. 兼容、发布与回滚"
    implementation_anchors:
      - backend/app/models/tenant.py::Tenant.public_id
      - backend/app/database.py::_ensure_tenant_public_ids
      - backend/app/tenant_public_id.py::main
      - tests/integration/run_tenant_public_id_dialects.sh
    api_contract:
      status: not_applicable
      evidence: init_db internal startup operation
    client_contract:
      status: not_applicable
      evidence: no browser client before readiness
    table_contract:
      status: covered
      evidence: nullable expand, UUID v4 current writer, UUID v5 NULL reconciliation, unique index
    test_contract:
      status: covered
      evidence: SQLite reentry, old-writer NULL insertion, MySQL/PostgreSQL DDL and concurrency
    rollback_contract:
      status: covered
      evidence: retain nullable column and values; rollback frontend with backend; reconcile next upgrade
    audit_contract:
      status: covered
      evidence: scan, fill, null, failure totals and conflict numeric tenant IDs
  - operation_id: auth.tenant-public-id-project
    trigger: login, select tenant, me, or tenant list response
    source_sections:
      - "6. API 契约"
    depends_on:
      - tenant-public-id.expand-reconcile
    implementation_anchors:
      - backend/app/schemas.py::UserInfo
      - backend/app/schemas.py::TenantOption
      - backend/app/routes/auth/login.py
      - backend/app/routes/auth/tenants_admin.py
    api_contract:
      status: covered
      evidence: additive UserInfo and TenantOption UUID fields; existing Token remains unchanged
    client_contract:
      status: covered
      evidence: typed frontend User and TenantOption; no parallel switch DTO
    table_contract:
      status: covered
      evidence: project Tenant.public_id while preserving numeric tenant_id
    test_contract:
      status: covered
      evidence: endpoint schema, projection fill, nullability, active tenant and old-client tests
    rollback_contract:
      status: covered
      evidence: old clients ignore additive fields; new client tolerates rollout-time missing UUID by failing closed
    audit_contract:
      status: covered
      evidence: reconciliation and switch structured logs exclude credentials
  - operation_id: auth.candidate-token-verify
    trigger: accessible URL target or tenant menu action
    source_sections:
      - "6. API 契约"
      - "9. 主动切租户"
    depends_on:
      - auth.tenant-public-id-project
    implementation_anchors:
      - frontend/src/api/auth.ts::authApi.getMeWithToken
      - frontend/src/utils/request.ts::request-interceptor
      - frontend/src/stores/user.ts::switchTenantContext
    api_contract:
      status: covered
      evidence: existing POST /auth/switch-tenant Token then explicit candidate GET /auth/me
    client_contract:
      status: covered
      evidence: source state retained until numeric ID and public UUID both match
    table_contract:
      status: covered
      evidence: active Tenant and UserTenant membership validation remains server-side
    test_contract:
      status: covered
      evidence: explicit auth precedence, candidate mismatch, timeout and missing UUID tests
    rollback_contract:
      status: covered
      evidence: response DTO unchanged across old and new backend revisions
    audit_contract:
      status: covered
      evidence: existing switch structured log; current_app excluded as browser authority
  - operation_id: tenant-url.classify
    trigger: navigation to a tenantContext required or none route
    source_sections:
      - "7. 前端 URL 状态机"
    implementation_anchors:
      - frontend/src/router/index.ts::route-meta
      - frontend/src/router/tenantUrlGuard.ts::classifyTenantTarget
    api_contract:
      status: covered
      evidence: pre-mount auth request whitelist
    client_contract:
      status: covered
      evidence: route metadata, UUID canonicalization, required/none classification and rejection
    table_contract:
      status: not_applicable
      evidence: route resolution has no business persistence
    test_contract:
      status: covered
      evidence: table-driven classification and complete router.getRoutes coverage
    rollback_contract:
      status: covered
      evidence: old frontend ignores tenantId query; tenantless routes remove it
    audit_contract:
      status: covered
      evidence: deterministic unit and browser network evidence; no new event endpoint
  - operation_id: tenant-context.commit-and-navigate
    trigger: candidate token validation succeeds
    source_sections:
      - "7. 前端 URL 状态机"
      - "9. 主动切租户"
    depends_on:
      - auth.candidate-token-verify
      - tenant-url.classify
    implementation_anchors:
      - frontend/src/stores/user.ts::switchTenantContext
      - frontend/src/router/tenantUrlGuard.ts::resolveTenantUrl
      - frontend/src/components/v2/RailSidebar.vue
      - frontend/src/stores/mode.ts::MODE_META
    api_contract:
      status: covered
      evidence: consumes verified candidate UserInfo without changing backend DTO
    client_contract:
      status: covered
      evidence: commit token/user then reload original deep link or target mode home
    table_contract:
      status: covered
      evidence: active Tenant and UserTenant membership validation
    test_contract:
      status: covered
      evidence: deep-link preservation, active-menu reset, loop marker and failure cases
    rollback_contract:
      status: covered
      evidence: rejected candidate leaves browser source token, user and URL untouched
    audit_contract:
      status: covered
      evidence: navigation state assertions; no duplicate metrics registry
  - operation_id: cross-tab.align
    trigger: localStorage token storage event
    source_sections:
      - "12. 并发、失败与恢复"
    depends_on:
      - auth.tenant-public-id-project
    implementation_anchors:
      - frontend/src/stores/user.ts::storageAlignmentGeneration
      - frontend/src/api/auth.ts::authApi.getMeWithToken
    api_contract:
      status: covered
      evidence: explicit event token GET /auth/me
    client_contract:
      status: covered
      evidence: latest generation and current storage token must both match before navigation
    table_contract:
      status: not_applicable
      evidence: no persistence mutation
    test_contract:
      status: covered
      evidence: two-token out-of-order response and abort tests
    rollback_contract:
      status: covered
      evidence: legacy single-tab flow remains usable
    audit_contract:
      status: covered
      evidence: no token value is logged
  - operation_id: code-auth-fix.verify-release
    trigger: existing production release entrypoint
    source_sections:
      - "10. Code 深链接与运行时"
      - "15. 兼容、发布与回滚"
      - "16. 验证策略"
    depends_on:
      - tenant-public-id.expand-reconcile
      - tenant-context.commit-and-navigate
    implementation_anchors:
      - deploy/docker/Dockerfile
      - .gitlab-ci.yml::build_release_image
      - .gitlab-ci.yml::release_and_update_server
      - scripts/deploy_online_latest_kubesphere.sh
      - scripts/verify_builder_tenant_url_smoke.sh
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
      evidence: self-contained Chromium/Edge fixture and post-rollout Edge smoke
    rollback_contract:
      status: covered
      evidence: single historical image rollback retains nullable UUID column and values
    audit_contract:
      status: covered
      evidence: CI SHA meta, per-Pod image/imageID, reconciliation and 49a4bef4 ancestry
```

## 决策依据/Rationale

把 operation contract 拆到文件和 owner symbol 粒度，可以让实施计划直接生成数据库、
API、候选验证、路由、跨标签页和发布任务，同时保持未来无 reload Phase 2 的所有权
边界。

## 后续避坑/Lessons

- 不能把 URL UUID 当授权。
- 不能先保存候选 token 再用它显式验证目标 snapshot。
- 不能让租户关键迁移走 best-effort DDL。
- 不能让两个标签页自动按各自旧 URL 反向切换。
- 不能用 `current_app` 的单进程 slot 证明多 worker 租户一致性。
