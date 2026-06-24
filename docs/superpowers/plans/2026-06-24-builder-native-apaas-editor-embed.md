# Builder 配置工作区内嵌 apaas 原生编辑器 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Builder 配置工作区从「自渲染只读面板」改成「菜单目录 + 内嵌 apaas 原生编辑器 iframe + AI 助手」,删掉所有 apaas 自渲染面板与 SPEC/体检/日志/数据源 tab;另修 Builder 设计稿 HTML 预览多页能切。

**Architecture:** 新建共享组件 `InAppBrowser.vue`(地址栏 + iframe + 刷新 + 系统浏览器兜底,两种 sandbox 模式)。ChatPage「设计」tab 的 MODEL 菜单内容体换成 `InAppBrowser`(trusted-url,加载 `getEditorUrl` 返回的真实编辑器 URL);CUSTOM 菜单仍走 `CustomPagePreviewPanel`。删除其余自渲染面板与多余 tab,迁移 `ConfigWorkspacePanel`。

**Tech Stack:** Vue 3 SFC + Vite + Pinia + vitest;Tauri 桌面(`__DESKTOP__`)。后端 FastAPI(本计划基本不动后端,复用现成 `GET /applications/{id}/editor-url`)。

## Global Constraints

- 前端命令一律在 `frontend/` 下跑。测试:`npx vitest run <spec路径>`(或全量 `npm run test`)。构建自检:`npm run build:nocheck`(完整 `npm run build` 走 vue-tsc,仓库**预存坏**,不用它判定本任务成败)。
- **安全不变量(硬性)**:任何渲染不可信 AI HTML 的 iframe 必须 `sandbox="allow-scripts ..."` 且**绝不含** `allow-same-origin`(两者同给 = 沙箱逃逸,脚本可读父页 token)。加载可信外站(apaas 真实 URL,跨源)的 iframe 不加 sandbox。
- 测试惯例 = **源码文本断言**:`import src from './X.vue?raw'` + `expect(src).toContain(...)` / `.not.toContain(...)` / `.toMatch(...)`(vitest 无 DOM,不渲染组件)。沿用现有 `RunDebugPanel.spec.ts` / `ConfigWorkspacePanel.spec.ts` 写法。
- 工作树有大量**无关未提交改动**(Codex UI/PTY 等)。每个任务 `git add` **只加本任务涉及的文件**,绝不 `git add -A`。
- 桌面端判断用编译期常量 `__DESKTOP__`(`vite.config.ts` 由 `VITE_DESKTOP` 注入)。
- 编辑器 URL 接口:`getEditorUrl(appId, { menu_type, menu_id, form_id })` → `Promise<{ ok: boolean; url?: string; entry_url?: string; message?: string }>`(`@/api/editorUrl`)。

---

### Task 1: Builder 设计稿 HTML 预览 — 放开脚本让多页能切（独立、可单独发）

修 `AIChatPage.vue` 设计稿 HTML 产物预览 iframe 的 sandbox:`allow-same-origin allow-popups` → `allow-scripts allow-popups`。opaque origin 下脚本可跑、多页导航能切,且读不到父页 token。此任务与其余任务解耦。

**Files:**
- Modify: `frontend/src/views/AIChatPage.vue`(HTML 产物 iframe,搜 `class="art-preview-frame"`,约 378–385 行)
- Test: `frontend/src/views/AIChatPage.htmlPreview.spec.ts`(新建)

**Interfaces:**
- Consumes: 无
- Produces: 无(纯属性修正)

- [ ] **Step 1: 写失败测试**

```ts
// frontend/src/views/AIChatPage.htmlPreview.spec.ts
import { describe, expect, it } from 'vitest'
import src from './AIChatPage.vue?raw'

describe('AIChatPage 设计稿 HTML 预览', () => {
  it('HTML 产物 iframe 放开脚本(allow-scripts)让多页能切', () => {
    const frame = src.slice(src.indexOf('art-preview-frame'))
    const sandbox = frame.match(/sandbox="([^"]*)"/)?.[1] || ''
    expect(sandbox).toContain('allow-scripts')
  })
  it('安全: 放开脚本时绝不同时给 allow-same-origin(防读父页 token)', () => {
    const frame = src.slice(src.indexOf('art-preview-frame'))
    const sandbox = frame.match(/sandbox="([^"]*)"/)?.[1] || ''
    if (sandbox.includes('allow-scripts')) {
      expect(sandbox).not.toContain('allow-same-origin')
    }
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/views/AIChatPage.htmlPreview.spec.ts`
Expected: FAIL(当前 sandbox 含 `allow-same-origin`、无 `allow-scripts`)

- [ ] **Step 3: 改 iframe sandbox**

把 `art-preview-frame` 那个 iframe 的属性 `sandbox="allow-same-origin allow-popups"` 改为 `sandbox="allow-scripts allow-popups"`。同时把上方注释里「sandbox 不给 allow-scripts…」那段说明改成新理由(opaque origin 安全 + 多页可切)。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/views/AIChatPage.htmlPreview.spec.ts`
Expected: PASS

- [ ] **Step 5: 构建自检**

Run: `cd frontend && npm run build:nocheck`
Expected: 构建成功(无新增报错)

- [ ] **Step 6: 提交**

```bash
git add frontend/src/views/AIChatPage.vue frontend/src/views/AIChatPage.htmlPreview.spec.ts
git commit -m "fix(builder): 设计稿HTML预览放开脚本(allow-scripts)→多页可切"
```

---

### Task 2: 共享组件 `InAppBrowser.vue`

地址栏 + iframe + 刷新 + 「用系统浏览器打开」兜底。两种模式:`trusted-url`(`<iframe :src>` 无 sandbox,给 apaas 真实 URL)/ `untrusted-html`(`<iframe :srcdoc sandbox="allow-scripts allow-popups">`,给不可信 HTML)。

**Files:**
- Create: `frontend/src/components/common/InAppBrowser.vue`
- Test: `frontend/src/components/common/InAppBrowser.spec.ts`

**Interfaces:**
- Consumes: `openExternal` from `@/utils/desktop`
- Produces: 组件 `InAppBrowser`,props:
  - `mode: 'trusted-url' | 'untrusted-html'`(必填)
  - `url?: string`(trusted-url 用)
  - `srcdoc?: string`(untrusted-html 用)
  - `showAddress?: boolean`(默认 `mode==='trusted-url'`)
  - `title?: string`
  - 暴露方法 `reload()`(`defineExpose`),供父组件刷新。

- [ ] **Step 1: 写失败测试**

```ts
// frontend/src/components/common/InAppBrowser.spec.ts
import { describe, expect, it } from 'vitest'
import src from './InAppBrowser.vue?raw'

describe('InAppBrowser 共享内嵌浏览器', () => {
  it('trusted-url 模式: iframe 用 :src 且不加 sandbox', () => {
    expect(src).toMatch(/mode\s*===?\s*'trusted-url'/)
    expect(src).toMatch(/<iframe[\s\S]*:src=/)
  })
  it('untrusted-html 模式: srcdoc + sandbox=allow-scripts(不含 allow-same-origin)', () => {
    expect(src).toContain(':srcdoc')
    const m = src.match(/sandbox="([^"]*allow-scripts[^"]*)"/)
    expect(m).toBeTruthy()
    expect(m![1]).not.toContain('allow-same-origin')
  })
  it('reload 用 key 强制重挂 iframe', () => {
    expect(src).toMatch(/:key="reloadKey"/)
    expect(src).toContain('function reload')
    expect(src).toContain('defineExpose')
  })
  it('提供「用系统浏览器打开」兜底', () => {
    expect(src).toContain('openExternal')
    expect(src).toContain('用系统浏览器打开')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/components/common/InAppBrowser.spec.ts`
Expected: FAIL(文件不存在)

- [ ] **Step 3: 写组件**

```vue
<!-- frontend/src/components/common/InAppBrowser.vue
     共享内嵌浏览器: 地址栏 + iframe + 刷新 + 系统浏览器兜底。
     trusted-url: 加载可信外站(apaas 真实编辑器 URL, 跨源), 不加 sandbox。
     untrusted-html: 渲染不可信 HTML(AI 设计稿), srcdoc + 仅 allow-scripts(opaque origin)。 -->
<template>
  <div class="inapp-browser">
    <div class="iab-toolbar" v-if="showAddressBar">
      <input
        v-if="mode === 'trusted-url'"
        v-model="address"
        class="iab-address"
        type="text"
        spellcheck="false"
        placeholder="输入地址"
        @keydown.enter="go"
      />
      <span v-else class="iab-name">{{ title || '预览' }}</span>
      <button class="iab-btn" :disabled="!currentSrc" @click="reload" title="刷新">刷新</button>
      <button class="iab-btn" :disabled="!externalUrl" @click="openOutside" title="用系统浏览器打开">用系统浏览器打开</button>
    </div>
    <div class="iab-body">
      <iframe
        v-if="mode === 'trusted-url' && currentSrc"
        :key="reloadKey"
        :src="currentSrc"
        class="iab-frame"
        referrerpolicy="no-referrer"
        :title="title || '内嵌浏览器'"
      />
      <iframe
        v-else-if="mode === 'untrusted-html'"
        :key="reloadKey"
        :srcdoc="srcdoc || ''"
        class="iab-frame"
        sandbox="allow-scripts allow-popups"
        referrerpolicy="no-referrer"
        :title="title || '预览'"
      />
      <div v-else class="iab-empty"><slot name="empty">无内容</slot></div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { openExternal } from '@/utils/desktop'

const props = withDefaults(defineProps<{
  mode: 'trusted-url' | 'untrusted-html'
  url?: string
  srcdoc?: string
  showAddress?: boolean
  title?: string
}>(), { url: '', srcdoc: '', title: '' })

const reloadKey = ref(0)
const address = ref(props.url || '')
const currentSrc = ref(props.url || '')

const showAddressBar = computed(() => props.showAddress ?? props.mode === 'trusted-url')
// 「用系统浏览器打开」只对 trusted-url 有意义(srcdoc 无 URL 可外开)。
const externalUrl = computed(() => (props.mode === 'trusted-url' ? currentSrc.value : ''))

function normalizeUrl(u: string): string {
  const s = (u || '').trim()
  if (!s) return ''
  return /^https?:\/\//i.test(s) ? s : 'http://' + s
}
function go() {
  const u = normalizeUrl(address.value)
  if (!u) return
  address.value = u
  currentSrc.value = u
  reloadKey.value++
}
function reload() { reloadKey.value++ }
function openOutside() { if (externalUrl.value) void openExternal(externalUrl.value) }

// 父组件改 url(选别的菜单)→ 同步加载。
watch(() => props.url, (u) => {
  if (props.mode !== 'trusted-url') return
  address.value = u || ''
  currentSrc.value = u || ''
  reloadKey.value++
})
// 父组件改 srcdoc → 重挂。
watch(() => props.srcdoc, () => { if (props.mode === 'untrusted-html') reloadKey.value++ })

defineExpose({ reload })
</script>

<style scoped>
.inapp-browser { display: flex; flex-direction: column; height: 100%; min-width: 0; }
.iab-toolbar { display: flex; align-items: center; gap: 8px; padding: 6px 10px; border-bottom: 1px solid var(--line, #e5e7eb); flex: 0 0 auto; }
.iab-address { flex: 1; min-width: 0; background: var(--surface, #fff); border: 1px solid var(--line, #e5e7eb); border-radius: 8px; color: var(--text-1, #222); font-family: ui-monospace, monospace; font-size: 12px; padding: 5px 10px; outline: none; }
.iab-address:focus { border-color: var(--brand, #2f6bff); }
.iab-name { flex: 1; font-size: 13px; color: var(--text-2, #666); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.iab-btn { font-size: 12.5px; padding: 4px 10px; border: 1px solid var(--line, #e5e7eb); border-radius: 6px; background: var(--surface, #fff); color: var(--text-2, #666); cursor: pointer; white-space: nowrap; }
.iab-btn:hover:not(:disabled) { border-color: var(--brand, #2f6bff); color: var(--brand, #2f6bff); }
.iab-btn:disabled { opacity: .5; cursor: not-allowed; }
.iab-body { flex: 1; display: flex; min-height: 0; }
.iab-frame { flex: 1; width: 100%; border: 0; display: block; background: #fff; }
.iab-empty { flex: 1; display: flex; align-items: center; justify-content: center; color: var(--text-3, #888); font-size: 13px; padding: 20px; text-align: center; }
</style>
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/components/common/InAppBrowser.spec.ts`
Expected: PASS

- [ ] **Step 5: 构建自检**

Run: `cd frontend && npm run build:nocheck`
Expected: 成功

- [ ] **Step 6: 提交**

```bash
git add frontend/src/components/common/InAppBrowser.vue frontend/src/components/common/InAppBrowser.spec.ts
git commit -m "feat(builder): 新增共享内嵌浏览器 InAppBrowser(两种 sandbox 模式)"
```

---

### Task 3: ChatPage「设计」tab — MODEL 菜单内容体换成内嵌原生编辑器

把 `topTab === 'design' && selectedApaasMenuId`(非 CUSTOM)那个 designer shell 块(`class="...mdsh"`,含 `mdsh-subnav` 的 DESIGNER_SUBS 与 `mdsh-body` 的 6 个自渲染面板 + `OpenLowcodeBackendButton`)整块替换为 `InAppBrowser`(trusted-url),URL 来自 `getEditorUrl`。CUSTOM 分支(`CustomPagePreviewPanel`)与空态保留。`dev`/`health` 两个子页本步先临时保留入口(下个任务处理)。

**Files:**
- Modify: `frontend/src/views/ChatPage.vue`(模板约 178–273 行的 mdsh 块;script 加编辑器 URL 拉取 + 刷新接线)
- Test: `frontend/src/views/ChatPage.embed.spec.ts`(新建)

**Interfaces:**
- Consumes: `InAppBrowser`(Task 2),`getEditorUrl`(`@/api/editorUrl`)
- Produces: ChatPage 暴露内部 ref `embeddedEditorUrl: Ref<string>`、函数 `loadEmbeddedEditorUrl()`、模板 ref `editorBrowserRef`(给刷新调用 `.reload()`)。

- [ ] **Step 1: 写失败测试**

```ts
// frontend/src/views/ChatPage.embed.spec.ts
import { describe, expect, it } from 'vitest'
import src from './ChatPage.vue?raw'

describe('ChatPage 内嵌原生编辑器', () => {
  it('设计 tab 用 InAppBrowser 内嵌编辑器', () => {
    expect(src).toContain('InAppBrowser')
    expect(src).toMatch(/mode="trusted-url"/)
  })
  it('编辑器 URL 来自 getEditorUrl', () => {
    expect(src).toContain('getEditorUrl')
    expect(src).toContain('embeddedEditorUrl')
  })
  it('CUSTOM 菜单仍走 CustomPagePreviewPanel', () => {
    expect(src).toContain('CustomPagePreviewPanel')
  })
  it('助手 refresh-iframe 接到内嵌编辑器 reload', () => {
    expect(src).toContain('editorBrowserRef')
    expect(src).toMatch(/editorBrowserRef[\s\S]{0,40}reload/)
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/views/ChatPage.embed.spec.ts`
Expected: FAIL

- [ ] **Step 3: script — 加编辑器 URL 拉取 + 刷新接线**

在 `<script setup>` 内(`onApaasMenuSelected` 附近)加:

```ts
import InAppBrowser from '@/components/common/InAppBrowser.vue'
import { getEditorUrl } from '@/api/editorUrl'
import { ref } from 'vue'

const embeddedEditorUrl = ref<string>('')
const embeddedEditorMsg = ref<string>('')
const editorBrowserRef = ref<InstanceType<typeof InAppBrowser> | null>(null)

async function loadEmbeddedEditorUrl() {
  embeddedEditorUrl.value = ''
  embeddedEditorMsg.value = ''
  if (!existingAppId.value || !selectedApaasMenuId.value) return
  if (selectedApaasMenuType.value === 'CUSTOM') return  // 自开发走 CustomPagePreviewPanel
  try {
    const resp = await getEditorUrl(existingAppId.value, {
      menu_type: selectedApaasMenuType.value || 'MODEL',
      menu_id: selectedApaasMenuId.value || '',
      form_id: selectedApaasMenuFormId.value || '',
    })
    if (resp?.ok && resp.url) embeddedEditorUrl.value = resp.url
    else embeddedEditorMsg.value = resp?.message || '应用尚未部署到 aPaaS，无法打开配置页'
  } catch (e: any) {
    embeddedEditorMsg.value = e?.message || '加载配置页失败'
  }
}
```

在 `onApaasMenuSelected` 末尾追加 `void loadEmbeddedEditorUrl()`。

找到 `@refresh-iframe="refreshPlatformAndSidebar"`,把 `refreshPlatformAndSidebar` 内(或新建一个包装)加上 `editorBrowserRef.value?.reload()`。若 `refreshPlatformAndSidebar` 不便改,改成 `@refresh-iframe="onAssistantRefresh"` 并定义:

```ts
function onAssistantRefresh() {
  editorBrowserRef.value?.reload()
  // 保留原刷新菜单目录的逻辑(若原 refreshPlatformAndSidebar 有, 调它)
  try { refreshPlatformAndSidebar?.() } catch { /* noop */ }
}
```

- [ ] **Step 4: template — 替换 mdsh 块**

把 `<div v-else-if="topTab === 'design' && existingAppId && selectedApaasMenuId" class="platform-iframe-container mdsh"> ... </div>`(整个 mdsh 块,含 subnav + body 的 Form/List/Process/Event/Data/Perm 面板 + OpenLowcodeBackendButton;**暂留** AppDevWorkspacePanel/AppHealthPanel 见 Task 4)替换为:

```vue
<div
  v-else-if="topTab === 'design' && existingAppId && selectedApaasMenuId"
  class="platform-iframe-container mdsh"
>
  <InAppBrowser
    v-if="embeddedEditorUrl"
    ref="editorBrowserRef"
    mode="trusted-url"
    :url="embeddedEditorUrl"
    :title="selectedApaasMenuName || '配置'"
  />
  <div v-else class="mdsh-empty">
    <div class="mdsh-empty-icon"><AppIcon name="wrench" :size="32" /></div>
    <h3>{{ embeddedEditorMsg || '正在加载配置页…' }}</h3>
  </div>
</div>
```

(CUSTOM 分支 `CustomPagePreviewPanel`、未选菜单空态保持不动。)

- [ ] **Step 5: 跑测试 + 构建**

Run: `cd frontend && npx vitest run src/views/ChatPage.embed.spec.ts && npm run build:nocheck`
Expected: PASS + 构建成功

- [ ] **Step 6: 提交**

```bash
git add frontend/src/views/ChatPage.vue frontend/src/views/ChatPage.embed.spec.ts
git commit -m "feat(builder): 设计tab MODEL菜单内容体换成内嵌apaas原生编辑器+助手刷新接线"
```

---

### Task 4: ChatPage — 删多余 tab/面板/子页,收敛到「配置 + 自开发」

删 `topTab` 的 `data`/`logic`/`perm`/`log`/`spec`/`datasource` 分支及其面板;删 designer 残留(`DESIGNER_SUBS` 中 form/list/process/event/data/perm + `OpenLowcodeBackendButton` + `AppHealthPanel`/health 子页);保留 `AppDevWorkspacePanel`(自开发)与 `CustomPagePreviewPanel`;`AppAssistantPanel` 去掉 `topTab !== 'spec'` 与 `:designer-sub` 等失效条件。

**Files:**
- Modify: `frontend/src/views/ChatPage.vue`(模板 + script + 顶部 tab 定义)
- Modify: `frontend/src/views/ChatPage.styles.css`(删 RoleManagePanel/SpecDesignPanel 相关样式)
- Test: `frontend/src/views/ChatPage.cleanup.spec.ts`(新建)

**Interfaces:**
- Consumes: Task 3 的内嵌编辑器
- Produces: ChatPage 顶部 tab 收敛为「配置(design)+ 自开发」两项(自开发承载 `AppDevWorkspacePanel`)

- [ ] **Step 1: 写失败测试**

```ts
// frontend/src/views/ChatPage.cleanup.spec.ts
import { describe, expect, it } from 'vitest'
import src from './ChatPage.vue?raw'

describe('ChatPage 收敛: 删自渲染面板与多余 tab', () => {
  const gone = [
    'FormDesignerPanel', 'ListDesignerPanel', 'ProcessDesignerPanel',
    'DataSchemaEditor', 'FormPermPanel', 'BusinessEventPanel',
    'DataModelDetailPanel', 'DictEditorPanel', 'RoleManagePanel',
    'AppDatasourcePanel', 'SpecDesignPanel', 'LogsPanel', 'AppHealthPanel',
    'OpenLowcodeBackendButton',
  ]
  it('不再引用任何自渲染配置面板/深链按钮', () => {
    for (const c of gone) expect(src).not.toContain(c)
  })
  it('保留: 菜单目录 + 内嵌编辑器 + 助手 + 自开发', () => {
    expect(src).toContain('ApaasMenuSidebar')
    expect(src).toContain('InAppBrowser')
    expect(src).toContain('AppAssistantPanel')
    expect(src).toContain('AppDevWorkspacePanel')
    expect(src).toContain('CustomPagePreviewPanel')
  })
  it('助手不再依赖已删的 spec/designer-sub 条件', () => {
    expect(src).not.toContain(':designer-sub')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/views/ChatPage.cleanup.spec.ts`
Expected: FAIL

- [ ] **Step 3: 删模板分支**(逐个删除以下 `v-else-if`/块)

- `SpecDesignPanel`(topTab==='spec')、`LogsPanel`(topTab==='log')。
- `ProcessDesignerPanel`(topTab==='logic')、`DataModelDetailPanel`(topTab==='data'&&models)、`DictEditorPanel`(data&&dicts)、`RoleManagePanel`(perm&&roles)、`AppDatasourcePanel`(datasource)。
- 末尾「非原生 tab」`lowcode-deeplink-placeholder` 占位块(含 `OpenLowcodeBackendButton`)。
- Task 3 暂留的 `AppHealthPanel`/health 子页。
- `AppAssistantPanel`:去掉条件里的 `&& topTab !== 'spec'`,删 `:designer-sub="..."` 这一行 prop。

保留 `AppDevWorkspacePanel`:把它从 designer sub-tab 提为顶部「自开发」入口(见 Step 4)。

- [ ] **Step 4: 顶部 tab 收敛 + script 清理**

- 找到顶部 tab 的定义/渲染(搜 `topTab` 按钮渲染与 tab 列表常量,如 `SECTION_TO_TOP_TAB` 附近),把 tab 列表收敛为两项:`配置`(code=`design`)、`自开发`(code=`dev`)。`自开发` tab 内容体渲染 `<AppDevWorkspacePanel :app-id="existingAppId" />`。
- 删 import:`FormDesignerPanel/ListDesignerPanel/ProcessDesignerPanel/DataSchemaEditor/FormPermPanel/BusinessEventPanel/DataModelDetailPanel/DictEditorPanel/RoleManagePanel/AppDatasourcePanel/SpecDesignPanel/LogsPanel/AppHealthPanel/OpenLowcodeBackendButton` 及 `DESIGNER_SUBS`。
- 删随之失效的 script 符号(随删随 grep):`designerSub`、`currentSubTabsForTop` 中已删 tab、`showSpecArtifactPanel`/`PhaseBar`(若仅 SPEC 用)、SPEC/log/datasource 相关 ref。删一处 build:nocheck 一次,按报错继续清,直到干净。
- 删 `ChatPage.styles.css` 里 `RoleManagePanel`/`SpecDesignPanel` 相关选择器。

- [ ] **Step 5: 跑测试 + 构建(反复清到干净)**

Run: `cd frontend && npx vitest run src/views/ChatPage.cleanup.spec.ts src/views/ChatPage.embed.spec.ts && npm run build:nocheck`
Expected: PASS + 构建成功、无未定义符号

- [ ] **Step 6: 提交**

```bash
git add frontend/src/views/ChatPage.vue frontend/src/views/ChatPage.styles.css frontend/src/views/ChatPage.cleanup.spec.ts
git commit -m "refactor(builder): ChatPage 收敛到配置+自开发, 删自渲染面板与SPEC/日志/数据/流程/权限/数据源"
```

---

### Task 5: 迁移 `ConfigWorkspacePanel` 到内嵌编辑器

`/workspace/:id` 的 `WorkspaceShell` 经 `views/workspace/panels.ts` 注册了 `ConfigWorkspacePanel`,它复用了待删面板。改成同样的「菜单目录 + InAppBrowser 内嵌编辑器」。

**Files:**
- Modify: `frontend/src/views/workspace/panels/ConfigWorkspacePanel.vue`
- Modify: `frontend/src/views/workspace/panels/ConfigWorkspacePanel.spec.ts`
- Test: 同上 spec

**Interfaces:**
- Consumes: `InAppBrowser`、`getEditorUrl`、`ApaasMenuSidebar`

- [ ] **Step 1: 改测试(red)**

```ts
// frontend/src/views/workspace/panels/ConfigWorkspacePanel.spec.ts
import { describe, expect, it } from 'vitest'
import src from './ConfigWorkspacePanel.vue?raw'

describe('ConfigWorkspacePanel 内嵌编辑器', () => {
  it('用 ApaasMenuSidebar + InAppBrowser 内嵌, 不再引用自渲染面板', () => {
    expect(src).toContain('ApaasMenuSidebar')
    expect(src).toContain('InAppBrowser')
    expect(src).toContain('getEditorUrl')
    for (const c of ['FormDesignerPanel','DataSchemaEditor','ProcessDesignerPanel','FormPermPanel','OpenLowcodeBackendButton']) {
      expect(src).not.toContain(c)
    }
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/views/workspace/panels/ConfigWorkspacePanel.spec.ts`
Expected: FAIL

- [ ] **Step 3: 改组件**

`ConfigWorkspacePanel.vue` 模板:左 `ApaasMenuSidebar`(`:app-id="appId"`,`@menu-selected` 存选中)+ 右 `InAppBrowser mode="trusted-url" :url="editorUrl"`;script 复刻 Task 3 的 `getEditorUrl` 拉取逻辑(用本组件的 appId/选中菜单)。删 4 个 designer 面板 + 深链按钮 import 与 sub-tab 切换。CUSTOM 菜单分支:若本面板原不处理 CUSTOM,可保持只对 MODEL 菜单内嵌(其余给空态提示)。

- [ ] **Step 4: 跑测试 + 构建**

Run: `cd frontend && npx vitest run src/views/workspace/panels/ConfigWorkspacePanel.spec.ts && npm run build:nocheck`
Expected: PASS + 构建成功

- [ ] **Step 5: 提交**

```bash
git add frontend/src/views/workspace/panels/ConfigWorkspacePanel.vue frontend/src/views/workspace/panels/ConfigWorkspacePanel.spec.ts
git commit -m "refactor(builder): ConfigWorkspacePanel 改用内嵌apaas原生编辑器"
```

---

### Task 6: 删孤儿组件文件 + 支撑模块 + 旧测试 + CSS

Task 4/5 之后,以下面板已无引用,删文件本体与其专属支撑模块/测试。

**Files（Delete）:**
- 面板组件:`components/v3/FormDesignerPanel.vue`、`ListDesignerPanel.vue`、`ProcessDesignerPanel.vue`、`DataSchemaEditor.vue`、`FormPermPanel.vue`、`BusinessEventPanel.vue`、`DataModelDetailPanel.vue`、`DictEditorPanel.vue`、`RoleManagePanel.vue`、`AppDatasourcePanel.vue`、`SpecDesignPanel.vue`、`LogsPanel.vue`、`AppHealthPanel.vue`、`OpenLowcodeBackendButton.vue`(均在 `frontend/src/components/v3/` 或对应目录)。
- 专属支撑模块/测试:`components/v3/processNodeRegistry.ts`、`logsPanelData.ts`、`formPreviewLayout.spec.ts`、`AppHealthPanel.spec.ts`,以及上述组件各自的 `.spec.ts`。
- **不删** `api/editorUrl.ts`(内嵌仍用 `getEditorUrl`)、`SpecChatPanel.vue`(先确认是否还被别处用,grep 后定)。

- [ ] **Step 1: grep 确认零引用**

Run:
```bash
cd frontend/src && for c in FormDesignerPanel ListDesignerPanel ProcessDesignerPanel DataSchemaEditor FormPermPanel BusinessEventPanel DataModelDetailPanel DictEditorPanel RoleManagePanel AppDatasourcePanel SpecDesignPanel LogsPanel AppHealthPanel OpenLowcodeBackendButton; do echo "$c:"; grep -rln "$c" . | grep -v "/$c.vue\|/$c.spec"; done
```
Expected: 每个仅剩自身文件(或被同批删除的兄弟面板互引)。若有外部引用,先回到 Task 4/5 清掉。

- [ ] **Step 2: 删文件**

```bash
cd frontend/src/components/v3 && git rm FormDesignerPanel.vue ListDesignerPanel.vue ProcessDesignerPanel.vue DataSchemaEditor.vue FormPermPanel.vue BusinessEventPanel.vue DataModelDetailPanel.vue DictEditorPanel.vue RoleManagePanel.vue AppDatasourcePanel.vue SpecDesignPanel.vue LogsPanel.vue AppHealthPanel.vue OpenLowcodeBackendButton.vue processNodeRegistry.ts logsPanelData.ts
# 各自 .spec.ts / formPreviewLayout.spec.ts / AppHealthPanel.spec.ts 一并 git rm（按实际存在的文件名）
```
（路径以 grep 实测为准;`ProcessDesignerPanel` 若在 v3 外，按真实路径删。）

- [ ] **Step 3: 构建 + 全量测试**

Run: `cd frontend && npm run build:nocheck && npm run test`
Expected: 构建成功;测试无「找不到模块」红;原本预存的无关失败不计本任务账(与改前一致)。

- [ ] **Step 4: 提交**

（Step 2 的 `git rm` 已暂存删除;若 Task 4/5 还有未提交的 import 清理,在此显式 `git add` 那几个具体文件,勿用 `git add -A`。）

```bash
git status --porcelain   # 核对暂存区只含本批删除/相关清理
git commit -m "chore(builder): 删除已无引用的自渲染配置面板与支撑模块"
```

---

### Task 7（可选，最后做）: `RunDebugPanel` 复用 `InAppBrowser`

Code 侧 `RunDebugPanel` 的地址栏 + iframe 与 `InAppBrowser` 重复。让它内部复用 `InAppBrowser`(trusted-url)承载浏览器壳,自身只保留「启动预览 / dev server / 运行时报错」。**Codex UI 较脆**:若 `RunDebugPanel.spec.ts` 绿不了或行为有任何偏差,**放弃本任务、还原**,不影响整体功能。

**Files:**
- Modify: `frontend/src/views/coding/RunDebugPanel.vue`
- Test: 现有 `frontend/src/views/coding/RunDebugPanel.spec.ts` 必须保持全绿

- [ ] **Step 1: 改造前跑基线**

Run: `cd frontend && npx vitest run src/views/coding/RunDebugPanel.spec.ts`
Expected: 全 PASS(基线)

- [ ] **Step 2: 重构为复用 InAppBrowser**

把地址栏 + iframe 部分替换为 `<InAppBrowser mode="trusted-url" :url="current" ref=... />`,`startServe`/`activePreview`/`postMessage` 报错逻辑保留;`useDevUrl`/`devUrl` 改成给 InAppBrowser 喂 `url`。

- [ ] **Step 3: 跑测试**

Run: `cd frontend && npx vitest run src/views/coding/RunDebugPanel.spec.ts && npm run build:nocheck`
Expected: 全 PASS + 构建成功。**任何一项不过 → `git checkout` 还原本文件,跳过本任务。**

- [ ] **Step 4: 提交（仅当全绿）**

```bash
git add frontend/src/views/coding/RunDebugPanel.vue
git commit -m "refactor(coding): RunDebugPanel 复用 InAppBrowser 浏览器壳"
```

---

## 真机验收（用户，全部任务后）

1. 桌面 app 内打开某个已部署 app 的配置工作区,点左侧菜单 → 右侧 iframe 出 apaas 登录页 → 登一次。
2. 逐菜单(表单/不同 menu_type)点开,确认原生编辑器渲染稳定、可编辑保存、不崩回首页。
3. AI 配置助手对话改一处配置 → 确认刷新后内嵌编辑器显示新配置。
4. 点 CUSTOM(自开发)菜单 → 仍走我们自己的页面渲染。
5. 设计稿 HTML 预览(Task 1)多页能切。
6. 某 app 编辑器若在 iframe 内抽风 → 「用系统浏览器打开」兜底可用。

## 自查记录（写计划后）

- Spec 覆盖:内嵌编辑器(T3)、删自渲染+多余 tab(T4)、ConfigWorkspacePanel(T5)、删文件(T6)、设计稿预览修复(T1)、共享组件(T2)、RunDebugPanel 复用(T7 可选)—— 对齐 spec 第 3/4/6 节。
- 类型一致:`InAppBrowser` props(`mode/url/srcdoc/showAddress/title`)与 `reload()` 在 T2 定义、T3/T5/T7 消费,一致。`getEditorUrl` 签名/返回各处一致。
- 占位扫描:无 TBD;删除类步骤给了 grep 守卫与「删一处 build 一次」的具体清理法,非空泛「处理边缘情况」。
