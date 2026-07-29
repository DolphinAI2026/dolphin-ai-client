# 桌面 Code 输入区工作区上下文实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在桌面 Code 会话输入框底栏展示本地或远程工作区的最后一级目录，并移除顶部重复路径。

**Architecture:** `AIChatPage.vue` 以当前 `workspace_id` 调用现有 `codingApi.getWorkspace`，从 `workspace_type` 和 `disk_path` 派生只读目录上下文。`CodeSessionGitBar.vue` 恢复为纯 Git 工具区；目录展示不进入消息内容，也不改变 Runtime 或工作区绑定。

**Tech Stack:** Vue 3、TypeScript、Element Plus、Vitest、Vite

---

### Task 1: 将工作区目录移动到输入框底栏

**Files:**
- Modify: `frontend/src/views/AIChatPage.vue`
- Modify: `frontend/src/views/coding/CodeSessionGitBar.vue`
- Modify: `frontend/src/views/coding/CodeSessionGitBar.spec.ts`
- Modify: `frontend/src/views/AIChatPage.htmlPreview.spec.ts`

- [ ] **Step 1: 调整现有组件断言**

在 `CodeSessionGitBar.spec.ts` 删除顶部绝对路径断言；在 `AIChatPage.htmlPreview.spec.ts` 增加输入区目录上下文断言：

```ts
expect(src).toContain('codeWorkspaceContext')
expect(src).toContain('本地目录')
expect(src).toContain('远程目录')
expect(src).toContain('code-workspace-context')
```

- [ ] **Step 2: 运行聚焦测试并确认旧实现不满足新位置**

Run: `npm run test -- --run frontend/src/views/coding/CodeSessionGitBar.spec.ts frontend/src/views/AIChatPage.htmlPreview.spec.ts`

Expected: `AIChatPage.htmlPreview.spec.ts` 因输入区尚无 `codeWorkspaceContext` 而失败。

- [ ] **Step 3: 在 AIChatPage 派生工作区上下文**

引入 `codingApi` 和 `WorkspaceInfo`，监听 `codexPanelWsId` 拉取当前工作区；使用跨 Windows/Linux 路径规则提取最后一级目录：

```ts
type CodeWorkspaceContext = {
  sourceLabel: '本地目录' | '远程目录'
  directoryName: string
  fullPath: string
}

function workspaceDirectoryName(path: string): string {
  return path.replace(/\\/g, '/').replace(/\/+$/, '').split('/').pop() || path
}

const codeWorkspaceContext = computed<CodeWorkspaceContext | null>(() => {
  const workspace = codeWorkspaceMeta.value
  const fullPath = String(workspace?.disk_path || '').trim()
  if (!fullPath) return null
  const localTypes = new Set(['external', 'code-local-application', 'local'])
  return {
    sourceLabel: localTypes.has(String(workspace?.workspace_type || '')) ? '本地目录' : '远程目录',
    directoryName: workspaceDirectoryName(fullPath),
    fullPath,
  }
})
```

目录请求失败时清空展示，不能影响输入、Git 或会话加载。

- [ ] **Step 4: 在 UnifiedChatComposer 底栏渲染目录**

在 `#footer-left` 的模型选择器前渲染只读上下文：

```vue
<span
  v-if="codeWorkspaceContext"
  class="code-workspace-context"
  :data-source="codeWorkspaceContext.sourceLabel === '本地目录' ? 'local' : 'remote'"
  :title="`${codeWorkspaceContext.sourceLabel}：${codeWorkspaceContext.fullPath}`"
>
  <AppIcon name="folder" :size="13" />
  <span class="code-workspace-context-label">{{ codeWorkspaceContext.sourceLabel }}</span>
  <span aria-hidden="true">·</span>
  <span class="code-workspace-context-name">{{ codeWorkspaceContext.directoryName }}</span>
</span>
```

样式限制最大宽度并对目录名使用省略号，不添加当前不可用的下拉箭头或点击事件。

- [ ] **Step 5: 删除 CodeSessionGitBar 的路径职责**

删除 `localWorkspacePath`、`refreshWorkspace`、路径模板与样式；`refresh` 只调用 Git 状态刷新。保留工作区名称、分支、连接 Git、Push/Pull 的现有行为。

- [ ] **Step 6: 运行聚焦测试和前端构建**

Run: `npm run test -- --run frontend/src/views/coding/CodeSessionGitBar.spec.ts frontend/src/views/AIChatPage.htmlPreview.spec.ts`

Expected: 两个测试文件通过。

Run: `npm run build`

Expected: Vite 构建成功并更新桌面前端资源。

### Task 2: 更新 Windows 桌面 sidecar

**Files:**
- Rebuild: `backend/dist/ruijing-sidecar.exe`

- [ ] **Step 1: 同步当前源码到 Windows staging 并构建**

使用现有 Python 3.12 PyInstaller staging，保留已确认的 `greenlet==3.2.4`，生成 `backend/dist/ruijing-sidecar.exe`。

- [ ] **Step 2: 替换部署文件并启动客户端**

停止 `app.exe`、`ruijing-sidecar.exe` 和 `agent-runtime.exe`，校验 staging 产物 SHA-256 后替换 `C:\Users\Administrator\dolphin-code-win\ruijing-sidecar.exe`，再启动 `app.exe`。不执行桌面自动点击验证。

