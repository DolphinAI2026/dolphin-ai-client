# 后台配置 tab — 内嵌 apaas 应用管理后台 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Builder 应用工作区顶部加第三个 tab「后台配置」，点进去内嵌 apaas 原生的应用管理后台页 (`app-store/edit-app`)。

**Architecture:** 纯前端复用 2026-06-24 已落地的内嵌基建 —— `InAppBrowser`(trusted-url 内嵌真实 apaas URL) + `getEditorUrl`(不传 menu 即返回 admin 总览 URL，host/tid/appId 全来自应用绑定的 `PlatformEnv`，动态)。把响应→展示态的映射抽成纯函数单测，再接进 `ChatPage.vue`。后端零改动，仅补一条端点契约测试守住「动态 host + admin URL」。

**Tech Stack:** Vue 3 + TypeScript (Vite/vitest), Python FastAPI + pytest(async)。

## Global Constraints

- **域名/host 不写死**：admin URL 的 host 来自应用绑定的 `PlatformEnv.base_url`(去 `/backend`)，随接入的低代码环境动态变化。前端只用后端返回的整条 URL，**不得**在前端拼任何 apaas 域名。
- **tab 文案**「后台配置」，内部 code `admin`。
- **复用**：`InAppBrowser.vue`、`@/api/editorUrl` 的 `getEditorUrl`、`/applications/{app_id}/editor-url`、`app/apaas_editor_url.py`。**不新建**任何后端 URL 构建逻辑。
- **前端构建**：用 `npm run build:nocheck`(vite build) 作通过门；全量 `npm run build`(vue-tsc) 为仓库预存坏，不作门，只确认本改动不引入**新**类型错。
- **设计文档**：`docs/superpowers/specs/2026-06-26-backend-config-tab-embed-design.md`。

---

### Task 1: 后端端点契约测试 — 不传 menu 返回 host-absolute 的 admin 总览 URL

> 说明：后端**不改代码**。`build_editor_path` 的「无 menu → admin 总览」已被 `test_apaas_editor_url.py::test_no_menu_id_goes_to_overview` 覆盖；端点的 host-absolute 拼装被 `test_editor_url_builds_host_absolute` 覆盖(但用的是 menu 分支)。本任务补的是**端点 + 已部署 + 无 menu** 这条「后台配置」tab 唯一依赖、当前没测到的组合，作为回归守卫，并显式断言 host 来自绑定环境(不是写死域名)。该测试**写完即过**(无源码改动)，这是预期的——它锁契约，不引入新行为。

**Files:**
- Modify: `backend/tests/test_editor_url_endpoint.py` (在文件末尾追加一个测试函数)

**Interfaces:**
- Consumes: `app.routes.applications.section_content.get_editor_url(app_id, ctx, db, menu_type, menu_id, form_id)`，以及同文件已有的 `_ctx` / `_seed_app` 辅助、`PlatformEnv` 模型、`db_session` fixture。
- Produces: 无(测试)。

- [ ] **Step 1: 追加契约测试**

在 `backend/tests/test_editor_url_endpoint.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_editor_url_no_menu_returns_admin_overview(db_session):
    """「后台配置」tab 依赖：不传 menu → app-store/edit-app 总览，host 来自绑定环境(非写死域名)。"""
    from app.models import PlatformEnv
    env = PlatformEnv(
        tenant_id=7, env_name="prod", base_url="https://my-apaas.example.cn/backend",
        platform_tenant_id="TID42", token="tok",
    )
    db_session.add(env)
    await db_session.flush()
    user, app = await _seed_app(db_session, tenant_id=7, apaas_app_id="AP777", env_id=env.id)
    await db_session.commit()

    out = await get_editor_url(app.id, _ctx(user, 7), db_session,
                               menu_type="", menu_id="", form_id="")
    assert out["ok"] is True
    # host 跟随绑定环境 base_url(去 /backend) —— 换个域名也照样拼对，证明不写死
    assert out["url"] == (
        "https://my-apaas.example.cn/platform/TID42/admin/app-store/edit-app"
        "?appId=AP777&currentStepIndex=0"
    )
```

- [ ] **Step 2: 跑测试，确认通过**

Run: `cd backend && python -m pytest tests/test_editor_url_endpoint.py::test_editor_url_no_menu_returns_admin_overview -v`
Expected: PASS（无源码改动，锁的是既有契约）。

- [ ] **Step 3: 跑整个端点测试文件，确认没拖坏邻居**

Run: `cd backend && python -m pytest tests/test_editor_url_endpoint.py tests/test_apaas_editor_url.py -v`
Expected: 全 PASS。

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_editor_url_endpoint.py
git commit -m "test(editor-url): lock no-menu admin overview URL contract (后台配置 tab 依赖)"
```

---

### Task 2: 前端纯函数 `resolveAdminEditorState` + 单测

把「editor-url 响应 → 后台配置 tab 展示态」的分支逻辑抽成纯函数，单测覆盖。镜像仓库既有
`platformAdminEmbedState.ts` / `.spec.ts` 的「views 下纯函数 + vitest」模式。

**Files:**
- Create: `frontend/src/views/backendConfigTab.ts`
- Test: `frontend/src/views/backendConfigTab.spec.ts`

**Interfaces:**
- Consumes: `EditorUrlResp`(来自 `@/api/editorUrl`，字段 `{ ok: boolean; url?: string; message?: string; error_code?: string }`)。
- Produces: `resolveAdminEditorState(resp: EditorUrlResp | null | undefined): { url: string; msg: string }` —— Task 3 调用它。约定：`ok && url` → `{ url, msg: '' }`；否则 `{ url: '', msg: resp?.message || 默认引导文案 }`。

- [ ] **Step 1: 写失败的测试**

Create `frontend/src/views/backendConfigTab.spec.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { resolveAdminEditorState } from './backendConfigTab'

describe('resolveAdminEditorState', () => {
  it('有 url 时显示内嵌, 不带文案', () => {
    expect(resolveAdminEditorState({ ok: true, url: 'https://x/y' }))
      .toEqual({ url: 'https://x/y', msg: '' })
  })

  it('未部署: 用后端给的 message 作引导文案', () => {
    expect(resolveAdminEditorState({ ok: false, error_code: 'APP_NOT_DEPLOYED', message: '应用尚未部署到 aPaaS 平台' }))
      .toEqual({ url: '', msg: '应用尚未部署到 aPaaS 平台' })
  })

  it('ok 但缺 url: 当作未就绪, 落默认文案', () => {
    expect(resolveAdminEditorState({ ok: true }))
      .toEqual({ url: '', msg: '应用尚未部署到平台, 无法打开后台配置' })
  })

  it('null/undefined: 落默认文案', () => {
    expect(resolveAdminEditorState(null)).toEqual({ url: '', msg: '应用尚未部署到平台, 无法打开后台配置' })
    expect(resolveAdminEditorState(undefined)).toEqual({ url: '', msg: '应用尚未部署到平台, 无法打开后台配置' })
  })
})
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd frontend && npx vitest run src/views/backendConfigTab.spec.ts`
Expected: FAIL（`Failed to resolve import './backendConfigTab'` / 函数未定义）。

- [ ] **Step 3: 写最小实现**

Create `frontend/src/views/backendConfigTab.ts`:

```ts
import type { EditorUrlResp } from '@/api/editorUrl'

export interface AdminEditorState {
  url: string
  msg: string
}

const DEFAULT_MSG = '应用尚未部署到平台, 无法打开后台配置'

/**
 * 把 /editor-url 响应映射成「后台配置」tab 的展示态。
 * 有 url → 内嵌 apaas 应用管理后台；否则显引导文案(优先后端 message)。
 */
export function resolveAdminEditorState(resp: EditorUrlResp | null | undefined): AdminEditorState {
  if (resp?.ok && resp.url) return { url: resp.url, msg: '' }
  return { url: '', msg: resp?.message || DEFAULT_MSG }
}
```

- [ ] **Step 4: 跑测试，确认通过**

Run: `cd frontend && npx vitest run src/views/backendConfigTab.spec.ts`
Expected: PASS（4 个用例全过）。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/backendConfigTab.ts frontend/src/views/backendConfigTab.spec.ts
git commit -m "feat(builder): add resolveAdminEditorState helper for 后台配置 tab"
```

---

### Task 3: 接进 ChatPage.vue — 顶部 tab + 状态 + 懒加载 + 模板分支

**Files:**
- Modify: `frontend/src/views/ChatPage.vue`
  - tab 常量 `CONFIG_TOP_TABS`(约 1996-1999)
  - import 区(`getEditorUrl` 同处，约 560-572 一带的 import)
  - 状态/方法(紧挨现有 `embeddedEditorUrl` 块，约 2134-2154 之后)
  - 模板(在 `topTab==='dev'` 分支与 `v-else` 配置行之间，约 132-134)

**Interfaces:**
- Consumes: `resolveAdminEditorState`(Task 2)、`getEditorUrl`(已 import)、`existingAppId: Ref<number|null>`、`topTab: Ref<string>`、`InAppBrowser`、`AppIcon`(均已在 ChatPage 中)。
- Produces: 无(终端 UI)。

- [ ] **Step 1: tab 常量加「后台配置」**

把 `CONFIG_TOP_TABS`(约 1996) 改为：

```ts
const CONFIG_TOP_TABS = [
  { code: 'design', label: '配置' },
  { code: 'dev', label: '自开发' },
  { code: 'admin', label: '后台配置' },
] as const
```

- [ ] **Step 2: 引入纯函数**

在 import 区(与 `import { getEditorUrl } from '@/api/editorUrl'` 邻近处；若该 import 不存在则一并补上)加：

```ts
import { resolveAdminEditorState } from '@/views/backendConfigTab'
```

同时确认 `watch` 已在 `vue` 的具名 import 中（ChatPage 顶部 `import { ... } from 'vue'`）；若缺则补上 `watch`。

- [ ] **Step 3: 加状态 + 懒加载方法 + watch**

紧挨现有 `loadEmbeddedEditorUrl()`(约 2154 之后) 追加：

```ts
// ── 后台配置 tab: 内嵌 apaas 应用管理后台 (app-store/edit-app) ──
// host/tid/appId 全来自应用绑定的 PlatformEnv，动态；前端只用后端返回的整条 URL。
const adminEditorUrl = ref<string>('')
const adminEditorMsg = ref<string>('')
const adminBrowserRef = ref<InstanceType<typeof InAppBrowser> | null>(null)
let adminLoadedForAppId: number | null = null

async function loadAdminEditorUrl() {
  if (!existingAppId.value) return
  // 同一应用已拉到 url 就不重拉，避免重复进 tab 时 iframe 闪重载
  if (adminLoadedForAppId === existingAppId.value && adminEditorUrl.value) return
  try {
    const { url, msg } = resolveAdminEditorState(await getEditorUrl(existingAppId.value, {}))
    adminEditorUrl.value = url
    adminEditorMsg.value = msg
    if (url) adminLoadedForAppId = existingAppId.value
  } catch (e: any) {
    adminEditorUrl.value = ''
    adminEditorMsg.value = e?.message || '加载后台配置失败'
  }
}

// 切进「后台配置」tab 或绑定应用变化时懒加载一次
watch([topTab, existingAppId], ([t]) => {
  if (t === 'admin') void loadAdminEditorUrl()
})
```

- [ ] **Step 4: 模板插入 admin 分支**

在 `<AppDevWorkspacePanel :app-id="existingAppId" />` 所在 `topTab==='dev'` 块的 `</div>`(约 132) 之后、`<!-- 配置 tab content row -->` 与 `<div v-else ...>`(约 133-134) 之前，插入：

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

(配置行保持其原有 `v-else`，自然成为 dev / admin 之后的兜底分支。`.platform-iframe-container` / `.mdsh-empty` 复用现有样式；`.admin-shell` 仅占位，无需新样式。)

- [ ] **Step 5: 构建确认（vite 通过 + 不引入新类型错）**

Run: `cd frontend && npm run build:nocheck`
Expected: vite build 成功结束(无报错退出)。

Run: `cd frontend && npx vue-tsc --noEmit -p tsconfig.json 2>&1 | grep -E "backendConfigTab|adminEditorUrl|adminEditorMsg|resolveAdminEditorState|CONFIG_TOP_TABS"`
Expected: 无输出（本改动相关符号零类型错；ChatPage 其余预存类型错与本任务无关，不作门）。

- [ ] **Step 6: 回归 — 跑前端单测，确认没拖坏**

Run: `cd frontend && npx vitest run src/views/backendConfigTab.spec.ts`
Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add frontend/src/views/ChatPage.vue
git commit -m "feat(builder): 顶部加「后台配置」tab — 内嵌 apaas 应用管理后台(app-store/edit-app)"
```

---

## 验收（用户真机，登录态）

代码门过后，由用户在真机走一遍（需 apaas 登录态 + 一个已部署应用）：

1. 打开一个**已部署**应用 → 顶部出现「配置 / 自开发 / 后台配置」三个 tab。
2. 点「后台配置」→ 中间内嵌出 apaas 应用管理后台（`app-store/edit-app`），免登、可操作（改基本信息/发布/角色权限等）。
3. 切到不同低代码环境的应用 → host 跟着环境变（不是写死的 apaas-trial）。
4. 打开一个**未部署**应用点「后台配置」→ 显示引导空态（“应用需先部署…”），不白屏。
5. （§5 已知点）确认落地页是不是用户要的那页；若 `currentStepIndex=0` 落错步骤，再补 spec §5 的小开关。

## Self-Review 记录

- **Spec 覆盖**：§1 目标(三 tab)→Task3；§2 复用基建→Task2/3 全程复用；§3.1 tab→Task3 Step1；§3.2 状态/取数→Task3 Step3 + Task2(纯函数)；§3.3 模板→Task3 Step4；§3.4 助手天然不带→无需改(已确认)；§4 降级→Task2 默认文案 + Task3 Step4 空态；§5 已知风险→验收第5条；§6 测试→各任务 + 验收；「域名不写死」→Task1 断言不同 host + Global Constraints。无遗漏。
- **占位符**：无 TBD/TODO，所有代码步骤含完整代码与确切命令/预期。
- **类型一致**：`resolveAdminEditorState` 签名/返回 `{ url, msg }` 在 Task2 定义、Task3 解构一致；`AdminEditorState` 字段一致；`getEditorUrl(appId, {})` 与 `editorUrl.ts` 签名一致。
