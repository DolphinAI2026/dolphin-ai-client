---
asset_kind: page-interaction
asset_id: page-interaction.tenant-aware-auth-entry
knowledge_level: L3
source_spec_ref: docs/superpowers/specs/2026-07-20-builder-tenant-url-public-uuid-design.md
source_spec_hash: sha256:6acee24aea52edeece77b33dcc438eb3f1e1af00594a9bca69a8070d0e6878c4
phase_id: 2026-07-20-builder-tenant-url-public-uuid
revision: 1
source_section_refs:
  - "6. API 契约"
  - "8. 登录与多租户选择"
  - "16. 验证策略"
relations:
  - type: supports
    target: business-flow.tenant-url-resolution
---

# 租户感知登录入口

## 背景/Context

未登录用户打开带 `tenantId` 的深链接时，登录页和多租户选择页必须保留完整目标
地址，并使用服务端返回的可访问租户 UUID 决定是否自动选择。

## 方案/Solution

登录页只接受站内 redirect。单租户登录完成后由 `/auth/me` 恢复当前 UUID；多租户
登录响应通过 `TenantOption.tenant_public_id` 映射目标租户并调用现有选择接口。

## interaction_model

```yaml
schema_version: interaction-model/v1
surface: tenant-aware-auth-entry
route_role: public-authentication-entry
object_refs:
  - tenant-public-identity
states:
  - login_idle
  - login_submitting
  - tenant_selection_required
  - target_tenant_selected
  - target_tenant_rejected
  - redirecting
controls:
  - login_submit
  - tenant_select
  - retry_login
source_refs:
  - "6. API 契约"
  - "8. 登录与多租户选择"
forms:
  - form_code: login-deep-link
    submitted_fields:
      - username
      - password
      - captcha_id
      - captcha_code
    preserved_client_state:
      - redirect
      - target_tenant_public_id
    validation:
      captcha_required_when_server_requests: true
      redirect_must_be_same_origin_path: true
    failure_states:
      - invalid_credentials
      - captcha_required_or_invalid
      - target_tenant_inaccessible
    success:
      direct_token: validate_me_then_redirect
      tenant_selection_required: map_target_uuid_from_response
    output: LoginResponse
  - form_code: multi-tenant-selection
    submitted_fields:
      - selection_token
      - tenant_id
    derived_client_fields:
      tenant_id: LoginResponse.tenants[].tenant_id
      tenant_public_id: LoginResponse.tenants[].tenant_public_id
    preserved_client_state:
      - redirect
      - target_tenant_public_id
    validation:
      target_uuid_must_map_to_returned_tenant: true
    failure_states:
      - selection_token_expired
      - target_tenant_inaccessible
    success:
      token: call_me_then_redirect
    output: Token
redirect_contract:
  preserve:
    - path
    - query
    - hash
  allowed_origin: same-origin-path-only
  rejected_prefixes:
    - "//"
    - /login
    - /tenant-select
selection_rules:
  target_uuid_present_and_accessible: auto-select
  target_uuid_missing: use-existing-default-or-user-choice
  target_uuid_inaccessible: reject-and-enter-current-home
```

## 决策依据/Rationale

现有登录与 tenant-select 已有 redirect 和 selection token 契约，本 phase 只增加 UUID
映射和失败关闭，不引入第二套登录会话。

## 后续避坑/Lessons

- 不从 URL UUID 推导数字 ID，只能使用登录响应中的租户列表。
- 不允许绝对 URL、协议相对 URL 或编码绕过进入 redirect。
- 登录响应的直接 token 分支不伪造 user snapshot，统一由 `/auth/me` 恢复。
