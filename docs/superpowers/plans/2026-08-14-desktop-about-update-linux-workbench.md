# 桌面端关于更新与 Linux 工作台修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在桌面设置中提供版本和更新入口，并保证 Linux 桌面包内置真实 Builder 前端，使 Code iframe 能发送 `builder.ready`。

**Architecture:** 桌面设置继续复用编译常量 `__APP_VERSION__` 和现有 `checkAndPromptUpdate`。Linux appliance 构建与最终 AppImage 校验都把 `agent-runtime/web/builder/dist` 作为必需资源，避免再次生成返回占位 HTML 的包。

**Tech Stack:** Vue 3、TypeScript、Vitest、Bash、Tauri 2、Go agent-runtime。

## Global Constraints

- 不新增更新后端或协议。
- 不修改已正常的 Runtime manager 启动、锁和会话逻辑。
- 不新增测试文件，只扩展现有专项测试。
- 当前工作区包含既有未提交改动，本轮不创建提交。

---

### Task 1: Linux appliance 带入 Builder 前端

**Files:**
- Modify: `scripts/prepare-local-runtime-appliance-linux.sh`
- Modify: `scripts/build-desktop.sh`

**Interfaces:**
- Consumes: `AGENT_RUNTIME_REPO/web/builder/dist/index.html`
- Produces: `src-tauri/resources/agent-runtime/web/builder/dist/index.html` 和最终 AppImage 中相同路径的资源

- [ ] **Step 1: 证明当前失败**

Run:

```bash
test -f src-tauri/resources/agent-runtime/web/builder/dist/index.html
```

Expected: FAIL，因为当前 Linux appliance 没有 Builder dist。

- [ ] **Step 2: 在 appliance 构建时校验并复制 Builder dist**

在 `prepare-local-runtime-appliance-linux.sh` 中解析 `${AGENT_RUNTIME_REPO}/web/builder/dist`，要求 `index.html` 存在，然后复制到 `${APPLIANCE_DIR}/web/builder/dist`。

- [ ] **Step 3: 在 Linux 出包前后增加资源校验**

在 `build-desktop.sh` 中：

```bash
test -f "$ROOT/src-tauri/resources/agent-runtime/web/builder/dist/index.html"
```

重新封装 AppImage 后，从最终包提取 `resources/agent-runtime/web/builder/dist/index.html`，并断言其中存在 `id="root"` 和 JavaScript module 引用。

- [ ] **Step 4: 运行脚本专项检查**

Run:

```bash
bash -n scripts/prepare-local-runtime-appliance-linux.sh scripts/build-desktop.sh
```

Expected: PASS。

---

### Task 2: 桌面设置新增关于与更新

**Files:**
- Modify: `frontend/src/views/DesktopSettings.vue`
- Modify: `frontend/src/router/desktopGuard.spec.ts`

**Interfaces:**
- Consumes: `__APP_VERSION__`、`__DESKTOP__`、`__DESKTOP_WEB_PREVIEW__`、`checkAndPromptUpdate({ silentIfNone: false })`
- Produces: `SettingsSection = 'about'` 及“关于与更新”设置页面

- [ ] **Step 1: 写失败断言**

在现有 `desktopGuard.spec.ts` 的桌面设置源码断言中增加：

```ts
expect(desktopSettingsSource).toContain("label: '关于与更新'")
expect(desktopSettingsSource).toContain('当前版本')
expect(desktopSettingsSource).toContain('__APP_VERSION__')
expect(desktopSettingsSource).toContain('checkAndPromptUpdate({ silentIfNone: false })')
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
npm test -- --run src/router/desktopGuard.spec.ts
```

Expected: FAIL，缺少“关于与更新”。

- [ ] **Step 3: 实现最小页面**

在 `DesktopSettings.vue` 中新增菜单、元数据和 about 模板；桌面端按钮调用现有 updater，Web 预览按钮禁用并显示“仅桌面客户端可用”。

- [ ] **Step 4: 运行专项测试与桌面构建**

Run:

```bash
npm test -- --run src/router/desktopGuard.spec.ts
npm run build:desktop
```

Expected: PASS。

---

### Task 3: Linux 包专项验收

**Files:**
- Verify only: `src-tauri/target/release/bundle/appimage/*.AppImage`

**Interfaces:**
- Consumes: Task 1 与 Task 2 的构建结果
- Produces: 可启动的 Linux AppImage

- [ ] **Step 1: 重新准备 appliance 并构建 Linux 包**

Run:

```bash
bash scripts/prepare-local-runtime-appliance-linux.sh
bash scripts/build-desktop.sh
```

- [ ] **Step 2: 验证最终包资源**

提取 AppImage 后确认：

```text
resources/agent-runtime/web/builder/dist/index.html
resources/agent-runtime/codex/bin/codex
```

均存在，Builder HTML 不是 217 字节占位页。

- [ ] **Step 3: 启动客户端并检查真实入口**

启动新 AppImage，打开本地 Code 会话，确认代理 Builder HTML 后续加载 JS/CSS，并触发 `builder.ready`，不再停留在“正在打开 Code 工作台”。
