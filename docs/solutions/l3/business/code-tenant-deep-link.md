---
asset_kind: page-interaction
asset_id: page-interaction.code-tenant-deep-link
knowledge_level: L3
source_spec_ref: docs/superpowers/specs/2026-07-20-builder-tenant-url-public-uuid-design.md
source_spec_hash: sha256:f5936354b5aacca01dc239092fad4e2f54749b1a2816926c899a2c4860ad93ed
phase_id: 2026-07-20-builder-tenant-url-public-uuid
revision: 1
source_section_refs:
  - "10. Code 深链接与运行时"
  - "15. 兼容、发布与回滚"
  - "16. 验证策略"
  - "17. 验收标准"
relations:
  - type: supports
    target: business-flow.tenant-url-resolution
---

# Code 租户深链接

## 背景/Context

Code 分享链接同时包含 Builder shell session、租户 UUID 和可选 Agent Runtime session。
首次打开必须先完成 Builder 租户决议，再触发外层会话 API 和 iframe。

## 方案/Solution

Code 页面复用全局 tenant resolver。`agent` 更新保留 `tenantId`，Runtime 上游 URL
不接收租户 UUID。Agent Session 的 create/activate/delete 只走 Builder Bearer API。

## interaction_model

```yaml
schema_version: interaction-model/v1
surface: code-tenant-deep-link
route_role: authenticated-code-workbench
object_refs:
  - tenant-public-identity
  - code-shell-session
  - runtime-agent-session
states:
  - tenant_resolving
  - shell_loading
  - runtime_activating
  - iframe_mounting
  - ready
  - runtime_auth_failed
controls:
  - open_code_session
  - select_agent_session
  - retry_runtime_open
source_refs:
  - "10. Code 深链接与运行时"
  - "16. 验证策略"
url_contract:
  path: /ai-builder/code/<session-public-id>
  required_query:
    - tenantId
  optional_query:
    - agent
request_order:
  - tenant-auth-whitelist
  - builder-code-session-api
  - iframe-mount
agent_session_api:
  allowed_prefix: /api/code/sessions/
  forbidden_activation_prefix: /api/code-runtime/
runtime_contract:
  pass_tenant_id_upstream: false
  require_cookie_prewarm_without_agent: false
build_proof:
  meta_name: builder-build-sha
  required_ancestor_commit: 49a4bef4
```

## 决策依据/Rationale

仓库基线已经包含 Builder Bearer 外层会话修复。本资产把租户 URL 和该既有修复绑定到
同一个首开顺序与发布证据，不重复实现 Runtime 鉴权协议。

## 后续避坑/Lessons

- 不在 tenant resolver 完成前创建 iframe。
- 不把 `tenantId` 传给 Runtime。
- 不用静态资源时间戳代替 Git build SHA。
