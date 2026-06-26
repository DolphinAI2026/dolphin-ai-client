# 后台配置 tab — 内嵌 apaas 应用管理后台 设计

日期: 2026-06-26
分支: dev
状态: 已确认, 待 writing-plans

## 1. 背景与目标

Builder 应用工作区顶部现有两个 tab:「配置」(`design`) 和「自开发」(`dev`)，定义在
`frontend/src/views/ChatPage.vue` 的 `CONFIG_TOP_TABS`。

「配置」tab 负责单个菜单的表单/列表/流程/页面设计；「自开发」tab 负责二次开发。但有一类
**应用级**的信息只能在低代码平台的应用管理后台维护（应用基本信息、发布、角色权限等），
现在睿鲸里没有入口，用户得自己去 apaas 后台找。

目标: 加第三个顶部 tab「后台配置」，点进去直接内嵌 apaas 原生的应用管理后台页
(`app-store/edit-app`)，和用户日常用的那条链接一致:

```
{平台环境域名}/platform/{platform_tenant_id}/admin/app-store/edit-app?appId={apaas_app_id}
```

> 域名**不写死**。`{平台环境域名}` 来自应用绑定的 `PlatformEnv.base_url`，随接入的低代码环境
> 动态变化 (apaas-trial / 生产 / 私有化部署各不同)。下文出现的 `apaas-trial.definesys.cn`
> 仅为举例。

## 2. 复用现成基建 (本功能后端零改动)

这套「内嵌 apaas 原生页面」的能力在 2026-06-24「配置工作区内嵌原生编辑器」那轮已经全部落地，
本功能纯前端复用:

- 内嵌组件: `frontend/src/components/common/InAppBrowser.vue`
  - `mode="trusted-url"` + `:url` → 不加 sandbox 直接 `<iframe :src>` 真实 apaas URL。
  - 自带地址栏、刷新、「在系统浏览器打开」兜底；暴露 `reload()`。
  - 免登: apaas 登录态写在它自己 origin 的 localStorage，登一次免登；生产挂在低代码后台下本就是已登录态。

- 取 URL 的后端接口: `GET /applications/{app_id}/editor-url`
  (`backend/app/routes/applications/section_content.py`)。
  **不传 menu 时**，它经 `backend/app/apaas_editor_url.py: build_editor_path` 返回的正好是应用管理总览路径:
  ```
  /platform/{tid}/admin/app-store/edit-app?appId={apaas_app_id}&currentStepIndex=0
  ```
  - `host` = 应用绑定环境 `PlatformEnv.base_url` 去掉 `/backend`
  - `tid`  = `PlatformEnv.platform_tenant_id`
  - `appId`= `Application.apaas_app_id`
  - 未部署/未绑环境时返回 `{ ok: false, error_code: "APP_NOT_DEPLOYED" | "ENV_NOT_BOUND", message }`。

- 前端 client: `frontend/src/api/editorUrl.ts: getEditorUrl(appId, { menu_type?, menu_id?, form_id? })`。
  本功能调用时三个参数全空 → 命中后端默认值 → 返回 admin 总览 URL。

## 3. 方案 (方案 A: 复用 editor-url, 零后端改动)

只改 `frontend/src/views/ChatPage.vue`。

### 3.1 顶部 tab

`CONFIG_TOP_TABS` 增加一项:

```ts
const CONFIG_TOP_TABS = [
  { code: 'design', label: '配置' },
  { code: 'dev', label: '自开发' },
  { code: 'admin', label: '后台配置' },
] as const
```

切 tab 沿用现有 `@click="topTab = tab.code"`，无需动 `normalizeTopTab`
(它只决定初始值，恒落 `design`)。

### 3.2 状态 + 取数 (镜像现有 `loadEmbeddedEditorUrl`)

```ts
const adminEditorUrl = ref<string>('')
const adminEditorMsg = ref<string>('')
const adminBrowserRef = ref<InstanceType<typeof InAppBrowser> | null>(null)
let adminLoadedForAppId: number | null = null

async function loadAdminEditorUrl() {
  if (!existingAppId.value) return
  // 同一应用已加载过就不重复拉, 避免重复进 admin tab 时 iframe 闪重载
  if (adminLoadedForAppId === existingAppId.value && adminEditorUrl.value) return
  adminEditorUrl.value = ''
  adminEditorMsg.value = ''
  try {
    const resp = await getEditorUrl(existingAppId.value, {})  // 不传 menu → admin 总览
    if (resp?.ok && resp.url) {
      adminEditorUrl.value = resp.url
      adminLoadedForAppId = existingAppId.value
    } else {
      adminEditorMsg.value = resp?.message || '应用尚未部署到平台, 无法打开后台配置'
    }
  } catch (e: any) {
    adminEditorMsg.value = e?.message || '加载后台配置失败'
  }
}
```

懒加载触发 (切进 admin tab 或绑定应用变化时):

```ts
watch([topTab, existingAppId], ([t]) => {
  if (t === 'admin') void loadAdminEditorUrl()
})
```

(切换应用时 `adminLoadedForAppId` 与新 `existingAppId` 不等 → 重新拉。)

### 3.3 模板 (在「自开发」分支与「配置」分支之间插一段)

现状: `v-if topTab==='dev'` → 自开发; `v-else` → 配置行。
改为三段: dev / admin / (else) design。

```html
<!-- 后台配置 tab: 内嵌 apaas 应用管理后台 -->
<div
  v-else-if="existingAppId && topTab === 'admin'"
  class="platform-shell-row"
>
  <div class="platform-iframe-container admin-shell">
    <InAppBrowser
      v-if="adminEditorUrl"
      ref="adminBrowserRef"
      mode="trusted-url"
      :url="adminEditorUrl"
      title="后台配置"
    />
    <div v-else class="mdsh-empty">
      <div class="mdsh-empty-icon"><AppIcon name="wrench" :size="32" /></div>
      <h3>{{ adminEditorMsg || '正在加载后台配置…' }}</h3>
      <p v-if="adminEditorMsg">应用需先部署到平台并绑定环境, 才能打开后台配置。</p>
    </div>
  </div>
</div>
```

「配置」行保持原 `v-else` 作为兜底分支。复用现有 `.platform-iframe-container` / `.mdsh-empty` 样式,
`.admin-shell` 仅作占位 class (无新样式或仅补 100% 高度)。

### 3.4 AI 助手

现有 `AppAssistantPanel` 渲染在「配置」(`v-else`) 行内 → admin tab 天然不带助手。
符合预期 (在 apaas 自己的后台里, 不需要配置助手), 无需额外处理。

## 4. 边界与降级

- **未部署 / 未绑环境**: `editor-url` 返回 `APP_NOT_DEPLOYED` / `ENV_NOT_BOUND`,
  admin tab 显示引导空态 (不白屏)。
- **草稿应用 (无 `existingAppId`)**: 顶部 tab 整行 `v-if="existingAppId"` 不渲染 → admin tab 也不出现。
- **apaas 引擎崩**: 复用 `InAppBrowser` 的「在系统浏览器打开」兜底。

## 5. 已知小风险 / 后续可选 (方案 B)

`build_editor_path` 不传 menu 时固定追加 `currentStepIndex=0`，而用户参考链接不带该参数。
绝大概率 apaas 默认就是这一页 (step 0)，真机验收一看即知。若落错步骤, 再补方案 B 的小开关:
给 `editor-url` 加一个可选 `step_index` (或专门 admin-url 路径) 精确匹配。本期默认不做 (YAGNI)。

## 6. 测试与验收

- 前端 build 通过 (`npm run build:nocheck`; 全量 `npm run build` 为预存坏, 见 CLAUDE.md)。
- 若有 ChatPage 相关单测则跑过；本改动以模板/状态为主, 主要靠真机验收。
- **真机验收 (用户)**: 登录态下打开一个已部署应用 → 点「后台配置」→ 内嵌出 apaas
  应用管理后台 (app-store/edit-app), 免登、可操作；未部署应用显示引导空态。

## 7. 影响面

- 改动文件: `frontend/src/views/ChatPage.vue` (1 处常量 + ~15 行 script + ~18 行 template)。
- 后端: 无改动。
- 复用: `InAppBrowser.vue`、`editorUrl.ts`、`section_content.py: editor-url`、`apaas_editor_url.py`。
