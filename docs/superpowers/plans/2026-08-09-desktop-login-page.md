# 桌面登录页优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复桌面登录服务切换入口，并优化登录卡片的视觉层级与响应式表现。

**Architecture:** 继续使用 `Login.vue` 的现有认证逻辑；仅在服务切换边界增加网页预览路由跳转，Tauri 保持原生命令。视觉调整集中在登录页模板和 scoped CSS。

**Tech Stack:** Vue 3、TypeScript、Vue Router、Element Plus Icons。

## Global Constraints

- 不修改登录 API、验证码接口、租户选择和认证数据结构。
- 不新增依赖，不引入第二套登录状态。
- Tauri 正式包继续调用 `desktop_enter_login_setup`。
- 桌面预览使用 `/desktop-setup` 路由，不使用 localhost 直连或外部窗口。

---

### Task 1: 修复服务切换行为

**Files:**
- Modify: `frontend/src/views/Login.vue`
- Test: `frontend/src/router/desktopGuard.spec.ts`（只补充现有源码断言需要的核心行为）

**Interfaces:**
- Consumes: `isDesktop`, `enterDesktopLoginSetup`, `useRouter`。
- Produces: `changeDesktopService()` 在预览和 Tauri 两种环境下都有后续动作。

- [ ] 在 `changeDesktopService()` 中保留登出和切换锁定。
- [ ] 预览环境使用 `router.replace('/desktop-setup')`，原生环境调用 `enterDesktopLoginSetup()`。
- [ ] 捕获失败时恢复切换状态并显示现有错误提示。
- [ ] 运行 `npm run build` 验证类型和构建。

### Task 2: 优化登录卡片入口与布局

**Files:**
- Modify: `frontend/src/views/Login.vue`

**Interfaces:**
- Consumes: `desktopService` 摘要和 `desktopServiceChangeAllowed` 状态。
- Produces: 卡片右上角带 tooltip 的图标入口，服务摘要和登录表单保持原有数据绑定。

- [ ] 用设置/切换图标按钮替换横向文字按钮，补充 `title`、`aria-label` 和禁用态。
- [ ] 调整卡片标题区、服务摘要、表单间距，确保摘要可折行且不挤压表单。
- [ ] 降低背景装饰对比度，强化卡片边界和主操作按钮。
- [ ] 补齐深色主题和窄屏样式，保持验证码区域不溢出。
- [ ] 运行 `npm run build:desktop` 和 `git diff --check`。

### Task 3: 轻量回归检查

- [ ] 从网页桌面预览进入登录页，点击右上角服务切换图标，确认进入 `/desktop-setup`。
- [ ] 确认 Tauri 分支仍只调用原生 `desktop_enter_login_setup`。
- [ ] 记录现有测试中与旧版向导源码断言相关的历史失败，不为本次 UI 改动扩展无关测试。
