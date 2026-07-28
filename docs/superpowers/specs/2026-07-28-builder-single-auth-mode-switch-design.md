# Builder 配置文件单一登录模式设计

**状态**：已确认，进入实现

**目标仓库**：`apaas-builder-ai`

## 1. 目标

每个客户实例只配置一种 Builder 登录模式：

```env
AUTH_PROVIDER=control_plane
```

或者：

```env
AUTH_PROVIDER=apaas
```

默认值为 `control_plane`。登录页和管理后台都不提供模式切换控件，用户不能在请求中自行选择认证源。

Control Plane 登录用户仍可绑定 aPaaS 账号。该绑定只用于访问 aPaaS 租户、应用和低代码能力，不是第二个登录模式。

## 2. 当前能力

现有运行时已经直接读取 `AUTH_PROVIDER`：

- `/api/auth/login` 根据配置调用 Control Plane 或 aPaaS 登录。
- `/api/auth/captcha` 仅在 Control Plane 模式请求验证码。
- `deploy/customer/deploy.sh` 已校验 `AUTH_PROVIDER` 只能为 `control_plane` 或 `apaas`。
- `deploy/customer/backend.env.template` 已明确单个客户固定一种模式且登录页不暴露切换。

因此不需要新增数据库配置、不需要管理页面，也不需要改写登录流程。

## 3. 最小改动

1. 将 `Settings.auth_provider` 的代码默认值从空字符串改为 `control_plane`。
2. 保留 `AUTH_PROVIDER=local|coding` 的历史兼容解析，但客户部署脚本继续拒绝这两个值。
3. 在 README 中明确：
   - 客户实例通过后端配置文件中的 `AUTH_PROVIDER` 选择唯一登录模式。
   - 修改配置后需要重启后端实例。
   - Control Plane 模式下仍可绑定 aPaaS 能力账号。
4. 增加配置测试，证明未显式设置时默认是 Control Plane，同时显式 `apaas` 可以覆盖默认值。

## 4. 切换流程

```text
修改 backend.env / .env
  -> AUTH_PROVIDER=control_plane 或 apaas
  -> 重启后端 Pod/容器/进程
  -> 新的验证码和登录请求使用新认证源
```

已经签发的 Builder JWT 不会因为修改配置立即失效；用户退出或会话过期后的下一次登录使用新模式。

## 5. aPaaS 绑定边界

本次不修改：

- `POST /users/{user_id}/apaas-binding`
- `User.apaas_*`
- `APaaSUserCredential`
- `UserTenant`
- aPaaS 调用凭据解析链路

Control Plane 登录不以 aPaaS 绑定为前置条件。未绑定用户仍可登录；只有访问依赖 aPaaS 的功能时才需要绑定。

## 6. 验收标准

1. 未配置 `AUTH_PROVIDER` 时，运行时默认值为 `control_plane`。
2. `AUTH_PROVIDER=apaas` 时，现有 aPaaS 登录分派测试继续通过。
3. `AUTH_PROVIDER=control_plane` 时，现有 Control Plane 登录和验证码测试继续通过。
4. 管理端和登录页没有新增模式切换控件。
5. 客户部署模板和校验脚本仍只接受 `control_plane|apaas`。
6. Control Plane 用户绑定 aPaaS 的现有测试无回归。

## 7. 非目标

- 不让数据库配置覆盖 `AUTH_PROVIDER`。
- 不新增登录模式管理 API 或界面。
- 不删除现有 `builder_auth_settings` 兼容代码。
- 不迁移用户、租户、会话或 aPaaS 绑定数据。
- 不强制在线用户立即退出。
