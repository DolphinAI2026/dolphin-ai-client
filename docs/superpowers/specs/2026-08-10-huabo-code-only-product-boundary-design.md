# 华宝 Code-only 产品边界与登录链路修复设计

## 背景

华宝部署只开放 Dolphin Code，配置为：

```text
BUILDER_PRODUCT_BUILDER_ENABLED=false
BUILDER_PRODUCT_CODE_ENABLED=true
BUILDER_AUTH_DEFAULT_LOGIN_PROVIDER=platform
BUILDER_AUTH_ENABLED_LOGIN_PROVIDERS=platform
```

现网曾通过 nginx CSS 隐藏 Builder 标签，但 `/`、Logo、登录恢复和旧链接仍可进入
Builder 页面。工作区打开时还出现 GitLab 用户名被识别为 `admin`，导致
`GIT_CREDENTIAL_REFRESH_FAILED`。验证码能力未部署时，前端也会因验证码接口失败而
阻断登录。

## 目标

1. 产品开关同时约束可见入口、默认首页、直接路由和后端产品 API。
2. Code-only 部署的所有通用入口稳定进入 `/code/apps`。
3. 用户 Bearer token 与可信 AI Builder 委托身份可以同时传递。
4. GitLab 保留用户名继续映射为稳定、安全的用户名。
5. 验证码未启用或暂时不可用时不阻断无验证码登录。

## 非目标

- 不修改 Control Plane 的租户、角色或 Bearer token 校验规则。
- 不改变 Builder/Code 同时启用时的现有入口和路由。
- 不处理 GitLab TLS、PAT 有效期、默认 seed、模型 Secret 初始化。
- 不在本阶段定位通用的 `WORKSPACE_PROVISION_FAILED`。

## 方案选择

### 方案 A：继续通过 CSS 隐藏

改动最小，但直接 URL、Logo 和登录恢复仍能进入 Builder，后端也不受约束。不采用。

### 方案 B：仅增加前端重定向

可以修复用户可见路径，但 Builder API 仍然开放，产品开关成为纯展示配置。不采用。

### 方案 C：前后端共享同一产品配置语义

前端从公开配置计算启用产品和默认首页，路由守卫收敛禁用产品；后端在产品路由入口
执行同一开关校验。该方案能形成完整产品边界，采用此方案。

## 设计

### 1. 前端产品能力状态

新增轻量产品能力模块，加载 `GET /api/auth/settings/public`，归一化为：

```ts
type ProductAvailability = {
  builder: boolean
  code: boolean
}
```

配置模型保证至少启用一个产品。请求失败时保持兼容默认值
`{ builder: true, code: true }`，避免公共配置短暂故障把已有部署锁死。

能力模块提供：

- `enabledModes()`：按 `Builder -> Code` 的稳定顺序返回启用模式。
- `defaultHome()`：返回第一个启用模式的首页。
- `redirectForDisabledProduct(path)`：禁用产品路由映射到默认首页。

### 2. 路由与导航

- Web 侧 Rail 使用 `enabledModes()`，不再固定使用 `MODE_ORDER`。
- 路由守卫在认证和租户状态就绪后检查产品边界。
- Builder 禁用时，`/`、`/ai-chat/**`、`/chat/**`、`/apps`、Builder 工作区和
  Builder 管理页面重定向到 `/code/apps`。
- Code 禁用时，`/code/**` 重定向到 Builder 首页。
- 登录成功没有服务端 `entry_path` 时，使用 `defaultHome()`，不再固定 `/`。
- Logo、租户切换和认证状态恢复统一使用当前启用产品首页。
- Builder/Code 同时启用时保持现有行为，根路由仍为 Builder。

产品路由分类采用显式 route meta，而不是用“非 `/code` 都是 Builder”的隐式判断。
登录、租户选择和桌面设置等公共路由不属于任何产品，不参与重定向。

### 3. 后端产品边界

复用 `get_builder_auth_config()` 的产品开关，在 Builder 和 Code 的顶层 API 路由增加
依赖校验。禁用时返回：

```json
{
  "detail": "product is disabled",
  "code": "PRODUCT_DISABLED"
}
```

HTTP 状态为 `404`，避免对未开放产品暴露可调用能力。认证、公开配置和健康检查不受
产品 guard 影响。

### 4. Control Plane 委托身份

`_control_plane_headers()` 保留原 Bearer token 选择逻辑，但委托身份不再受
`has_user_bearer` 阻断：

```text
Authorization: Bearer <current token>
X-AI-Builder-Delegation-Secret: <shared secret>
X-AI-Builder-Delegated-User-Id: <delegated user>
X-AI-Builder-Delegated-Username: <safe GitLab username>
X-AI-Builder-Delegated-Display-Name-B64: <display name>
```

只有存在 `delegated_context` 时才增加委托头；远程请求必须同时配置共享 Secret。
Control Plane 现有规则只允许管理员身份消费可信委托头，普通用户 Bearer 会忽略委托
身份，因此不扩大权限。

`admin`、`root` 继续映射为：

```text
ai-builder-<reserved-name>-<local-user-id>
```

### 5. 无验证码登录

- 后端保持：验证码能力未启用或上游没有返回完整验证码时 `required=false`。
- 前端验证码请求失败时同样按 `required=false` 处理，不显示无法完成的验证码输入。
- 登录接口如果实际要求验证码，仍返回自身错误；前端展示该错误，不伪造验证码。

## 兼容与回退

- 双产品部署默认行为不变。
- 公共配置请求失败时回退双产品，避免故障放大。
- 删除新产品能力守卫即可恢复旧路由行为；数据库和 API 契约没有迁移。
- 委托身份修复可通过恢复原条件判断回退，不改变 header 名称。

## 验证

1. 单元测试覆盖 Code-only、Builder-only、双产品和公共配置失败。
2. 路由测试覆盖 `/`、Logo、登录回退、直接访问禁用产品和公共路由。
3. 后端测试覆盖禁用产品 API 返回 `PRODUCT_DISABLED`。
4. Header 测试覆盖 Bearer 与委托头并存、共享 Secret、保留用户名映射。
5. 登录测试覆盖验证码接口失败不阻断提交。

## 当前状态

用户已在 2026-08-10 的根因与方案说明后授权按推荐方案推进。本设计只承接 AI Builder
第一批修复；Control Plane 部署初始化另行设计和实施。
