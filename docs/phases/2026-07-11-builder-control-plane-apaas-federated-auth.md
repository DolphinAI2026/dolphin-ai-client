# Builder Control Plane 与 aPaaS 联邦认证 Phase

Design spec: `docs/superpowers/specs/2026-07-11-builder-control-plane-apaas-federated-auth-design.md`

## 阶段目标

将 Builder 当前 `platform/local/coding` 混合登录路径收敛为 `control_plane` 和 `apaas` 两个可配置入口。两种登录最终都取得 Control Plane 用户 token；Builder 保留本地 session 和资源投影，但不再自行决定 aPaaS 与 Control Plane 账号绑定事实。

## 范围

- 扩展现有 Builder auth settings，支持两种登录源及两种 binding mode。
- 用 `/api/builder-auth/**` 替换旧 `/api/auth/**` Control Plane 调用。
- aPaaS 登录后调用 Control Plane exchange，处理自动绑定或二次验证 challenge。
- 新增加密 Control Plane credential store，迁移明文 `coding_access_token` / `coding_refresh_token`。
- 用户业务请求使用当前用户 Control Plane token、`X-Tenant-Id`、`X-Auth-Provider`。
- 登录页和 store 支持绑定中间态、refresh、revoke 和错误码分流。

## 不做范围

- 不在 Builder 本地按用户名创建绑定事实。
- 不让浏览器保存 Control Plane refresh token。
- 不用全局 Control Plane service token 兜底用户业务请求。
- 不恢复旧 Control Plane `/api/auth/**` 登录。
- 不在 tenant switch 时调用旧 `switch-tenant`。

## 依赖

- SDK 完成 external identity federation。
- Control Plane 完成 `/api/builder-auth/**` 和 `builder-control-plane` Provider 路由。
- 执行前必须保护当前工作区已有未提交认证改动，不得覆盖或回退。

## 验收

- 两种入口按配置显示，默认源可切换。
- `verify_control_plane` 和 `username_auto` 均通过。
- refresh、revoke、非法 tenant 和 Provider 不可达有稳定行为。
- Control Plane token 加密保存，旧明文字段停止写入。
- 配置模板写清可选值、默认值和生效条件。
