---
asset_kind: page-interaction
asset_id: page-interaction.tenant-aware-navigation
knowledge_level: L3
source_spec_ref: docs/superpowers/specs/2026-07-20-builder-tenant-url-public-uuid-design.md
source_spec_hash: sha256:d472f7bb6fdc34913e94de77882d00c404804cfd2eb2d38b46750050e4891232
phase_id: 2026-07-20-builder-tenant-url-public-uuid
revision: 1
source_section_refs:
  - "7. 前端 URL 状态机"
  - "8. 登录与多租户选择"
  - "9. 主动切租户"
  - "10. Code 深链接与运行时"
  - "17. 验收标准"
relations: []
---

# 租户感知导航

## 背景/Context

Builder 的受保护页面需要把当前租户作为可分享、可恢复的显式 URL 上下文。页面必须
先确认 URL 租户与认证上下文一致，再挂载租户业务内容，避免旧 token、旧链接或主动
切换造成跨租户资源误读。

## 方案/Solution

全局路由守卫统一处理 URL 规范化、已授权跨租户切换、非法目标拒绝和登录回跳。
侧边栏主动切租户进入目标模式首页；深链接自动切租户则保留原 path、query 和 hash。
Code 页面只有在通用租户守卫通过后才创建 iframe 或激活 Agent Session。

## interaction_model

```yaml
schema_version: interaction-model/v1
surface: tenant-aware-protected-route
route_role: authenticated-tenant-context
object_refs:
  - tenant-public-identity
states:
  - auth_restoring
  - tenant_url_missing
  - tenant_matched
  - tenant_switching
  - tenant_rejected
  - tenant_switch_failed
  - ready
controls:
  - tenant_menu
  - login_submit
  - tenant_select
  - retry_tenant_navigation
source_refs:
  - "7. 前端 URL 状态机"
  - "8. 登录与多租户选择"
  - "9. 主动切租户"
  - "10. Code 深链接与运行时"
url_contract:
  query_key: tenantId
  value_format: lowercase-hyphenated-uuid
  canonicalization: router-replace
  preserve:
    - path
    - other-query
    - hash
resolution_rules:
  - condition: tenantId-missing
    action: add-current-tenant-public-id
    destination: same-full-path
  - condition: tenantId-equals-current
    action: continue
    destination: requested-page
  - condition: tenantId-is-accessible-other-tenant
    action: switch-token-context-once
    destination: original-full-path
  - condition: tenantId-invalid-or-inaccessible
    action: reject-before-page-mount
    destination: current-mode-home
active_switch_rules:
  preserve_resource_path: false
  destination: target-mode-home
  clear_tenant_scoped_state: true
login_redirect_rules:
  preserve_full_path: true
  auto_select_accessible_target_tenant: true
  reject_inaccessible_target_before_business-load: true
code_deep_link_rules:
  wait_for_tenant_resolution: true
  preserve_agent_query: true
  pass_tenant_id_to_runtime_upstream: false
  require_cookie_prewarm_without_agent: false
feedback:
  invalid_uuid: 租户链接无效
  inaccessible_tenant: 无权访问该租户
  inactive_tenant: 目标租户不可用
  expired_login: 登录状态已失效
  switch_failure: 租户切换失败，请重试
loop_guard:
  max_automatic_attempts: 1
  marker_ttl_seconds: 30
  concurrent_switch_policy: singleflight
```

## 决策依据/Rationale

URL 中的公共 UUID 让租户上下文显性且稳定，但它不承担授权。复用现有全局守卫、
用户 store、登录 redirect 和租户菜单，可以在不引入第二套会话体系的前提下把页面
挂载顺序和切租户行为收敛为一个状态机。

## 后续避坑/Lessons

- 不要在目标租户校验完成前发出页面业务请求。
- 不要把 URL UUID 直接作为可信数据库过滤条件。
- 不要在主动切租户时保留旧租户资源 ID。
- 不要把 `tenantId` 拼入 Runtime 上游 URL。
- 多标签页共享 token 的限制必须保留在验收和用户提示中。
