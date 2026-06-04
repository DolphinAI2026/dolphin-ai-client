# 配置面板只读化 + 深链低代码后台 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 ai-builder 配置面板全部改成只读自渲 + 每面板「打开低代码后台」深链，删掉整个反向代理内嵌编辑（崩溃源）。

**Architecture:** 两阶段。Phase A：抽 `build_editor_path` 纯函数 + 新 `GET /applications/{app_id}/editor-url` 接口（host-absolute aPaaS 编辑器 URL）+ 共享深链按钮，**先与现有内嵌并存并 preview 实测编辑器新标签页 SSO 免登可编辑**。Phase B（A 验证通过后）：各面板去编辑控件改只读 + 挂按钮、流程去 mock 实例 + 修适应、删 `ApaasEmbedIframe`/`platformIframe.ts`/`platform_proxy.py` + 死端点。

**Tech Stack:** FastAPI（无 Alembic）、SQLAlchemy async、pytest（`asyncio_mode=auto`）；Vue 3 + Element Plus + axios、x6（流程画布）；前端无单测 → vue-tsc + preview 验证。Python 3.13（`.venv`）。

**关键风险/铁律：**
1. **SSO 免登是承重假设** → Phase A 的 A5 是硬门：编辑器新标签页确实免登能编辑，才进 Phase B 删兜底。
2. 删 `platform_proxy.py` **之前**必须先在 A1 把 `_build_menu_redirect_path` 逻辑抽走。
3. `main.py` 有 3 处 `platform_proxy` 引用（import / `_ensure_proxy_state` / `include_router`）+ 一个 plugin-asset 中间件用 `handle_plugin_asset_request` —— B7 全部处理，且 plugin-asset 中间件要先确认是否独立承重。
4. MCP 工具（`add/update/disable_apaas_model_field`、`set_role_resource_permission`）**保留**（被 agent 路径 spec_apply 用）；只删 REST wrapper 端点。
5. **AI 配置（对话改配置）链路不动** —— 它是 app 内改配置的主路径。

---

## File Structure

新增：
- `backend/app/apaas_editor_url.py` — 纯函数 `build_editor_path(menu_type, app_id, menu_id, form_id) -> str`（从 `platform_proxy._build_menu_redirect_path` 的 config 分支抽出）+ `_MENU_TYPE_TO_EDITOR_PATH`。
- `backend/app/routes/applications/editor_url.py`（或并入 section_content）— `GET /{app_id}/editor-url` 端点。
- `frontend/src/components/v3/OpenLowcodeBackendButton.vue` — 共享深链按钮。
- `backend/tests/test_apaas_editor_url.py`、`backend/tests/test_editor_url_endpoint.py`。

修改（Phase B）：
- `frontend/src/components/v3/FormDesignerPanel.vue` / `ListDesignerPanel.vue` / `ProcessDesignerPanel.vue` — 去编辑模式改只读 + 挂按钮。
- `frontend/src/components/v3/DataSchemaEditor.vue` / `RoleManagePanel.vue` / `FormPermPanel.vue` — 去编辑控件改只读 + 挂按钮。
- `frontend/src/views/ChatPage.vue` — legacy iframe → 占位 + 按钮；清 iframe 机器。
- `frontend/src/api/`（新增 editor-url client）。

删除（Phase B）：
- `frontend/src/components/v3/ApaasEmbedIframe.vue`、`frontend/src/utils/platformIframe.ts`。
- `backend/app/routes/platform_proxy.py` + `main.py` 注册/引用 + 死 REST 端点。

---

# Phase A — 加深链 + 验证（内嵌仍在做兜底）

## Task A1: 抽 `build_editor_path` 纯函数

**Files:**
- Create: `backend/app/apaas_editor_url.py`
- Test: `backend/tests/test_apaas_editor_url.py`

> 从 `platform_proxy._build_menu_redirect_path`（platform_proxy.py:408-462）抽出**只需要的 config 分支**（runtime 分支是已废弃路径，不抽）。返回的是 `/platform/{tid}/...` 相对路径（host 在 A2 接口拼）。

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_apaas_editor_url.py`:

```python
"""aPaaS 编辑器路径构建（从 platform_proxy 抽出的纯函数）。"""
from __future__ import annotations

from app.apaas_editor_url import build_editor_path


def test_model_menu_path():
    p = build_editor_path("MODEL", apaas_app_id="A1", menu_id="M9", form_id="F3", tid="T7")
    assert p == "/platform/T7/default/data-model-fn-config?appId=A1&menuId=M9&formId=F3&processVersion=false"


def test_no_menu_id_goes_to_overview():
    p = build_editor_path("", apaas_app_id="A1", menu_id="", form_id="", tid="T7")
    assert p == "/platform/T7/admin/app-store/edit-app?appId=A1&currentStepIndex=0"


def test_quote_menu_type_subpath():
    p = build_editor_path("QUOTE", apaas_app_id="A1", menu_id="M2", form_id="", tid="T7")
    assert p == "/platform/T7/default/quote-fn-config?appId=A1&menuId=M2&processVersion=false"


def test_unknown_menu_type_defaults_fn_config():
    p = build_editor_path("WHATEVER", apaas_app_id="A1", menu_id="M2", form_id="", tid="T7")
    assert p.startswith("/platform/T7/default/fn-config?appId=A1&menuId=M2")


def test_no_embed_flags():
    # 真标签页要完整编辑器，不带 embed=1/hideClose=1
    p = build_editor_path("MODEL", apaas_app_id="A1", menu_id="M9", form_id="F3", tid="T7")
    assert "embed=1" not in p and "hideClose=1" not in p
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_apaas_editor_url.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.apaas_editor_url'`

- [ ] **Step 3: 写纯函数**

Create `backend/app/apaas_editor_url.py`:

```python
"""aPaaS 原生编辑器 URL 路径构建（纯函数）。

从 platform_proxy._build_menu_redirect_path 的 config 分支抽出，给「打开低代码后台」深链用。
返回相对路径 `/platform/{tid}/...`；调用方（editor-url 接口）拼上真主机 host 成 host-absolute。
**不带 embed=1/hideClose=1** —— 那是内嵌剥壳用的，真标签页要完整编辑器。
"""
from __future__ import annotations

# 菜单类型 → 平台 editor sub-path（跟 super-agents-dev openLowCodeEditorDirectly 对齐）
_MENU_TYPE_TO_EDITOR_PATH = {
    "MODEL": "data-model-fn-config",
    "MENU_TYPE_MODEL": "data-model-fn-config",
    "QUOTE": "quote-fn-config",
    "MENU_TYPE_QUOTE": "quote-fn-config",
}


def build_editor_path(
    menu_type: str,
    *,
    apaas_app_id: str,
    menu_id: str = "",
    form_id: str = "",
    tid: str,
    step_index: int = 0,
) -> str:
    """返回 aPaaS 编辑器相对路径。

    - 不传 menu_id → 应用编辑总览（currentStepIndex=step_index）。
    - 传 menu_id  → 该菜单的表单/模型编辑器。
    """
    if not (menu_id or "").strip():
        idx = step_index if 0 <= step_index <= 9 else 0
        return f"/platform/{tid}/admin/app-store/edit-app?appId={apaas_app_id}&currentStepIndex={idx}"

    sub_path = _MENU_TYPE_TO_EDITOR_PATH.get((menu_type or "").upper(), "fn-config")
    qs_parts = [f"appId={apaas_app_id}", f"menuId={menu_id}"]
    if (form_id or "").strip():
        qs_parts.append(f"formId={form_id}")
    qs_parts.append("processVersion=false")
    return f"/platform/{tid}/default/{sub_path}?{'&'.join(qs_parts)}"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_apaas_editor_url.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/apaas_editor_url.py backend/tests/test_apaas_editor_url.py
git commit -m "feat(editor-url): extract pure build_editor_path from platform_proxy"
```
End commit body with:
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

---

## Task A2: `GET /applications/{app_id}/editor-url` 接口

**Files:**
- Modify: `backend/app/routes/applications/section_content.py`（加端点，与 `apaas-access-url` 同文件同 router）
- Test: `backend/tests/test_editor_url_endpoint.py`

> 镜像 `apaas-access-url`（section_content.py:723）的 app/env 解析；host=`PlatformEnv.base_url`、tid=`PlatformEnv.platform_tenant_id`（跟 platform_proxy.py:564-566 一致）。返回 host-absolute URL。

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_editor_url_endpoint.py`:

```python
"""editor-url 端点：返回 host-absolute aPaaS 编辑器深链。直接调路由函数（本仓约定）。"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.deps import AuthContext
from app.models import User, Application
from app.models.tenant import Tenant
from app.routes.applications.section_content import get_editor_url


def _ctx(user, tenant_id):
    return AuthContext(user=user, tenant_id=tenant_id, tenant_role="member", org_permissions={})


async def _seed_app(db, *, tenant_id, apaas_app_id="AP123", env_id=None):
    user = User(username="u_eu", hashed_password="x")
    db.add(user)
    await db.flush()
    app = Application(
        user_id=user.id, tenant_id=tenant_id, created_by=user.id,
        app_name="报销申请", app_code="expense",
        apaas_app_id=apaas_app_id, platform_env_id=env_id,
    )
    db.add(app)
    await db.flush()
    return user, app


@pytest.mark.asyncio
async def test_editor_url_builds_host_absolute(db_session):
    from app.models import PlatformEnv
    env = PlatformEnv(
        tenant_id=7, env_name="dev", base_url="https://apaas.example.com/backend",
        platform_tenant_id="TID9", token="tok",
    )
    db_session.add(env)
    await db_session.flush()
    user, app = await _seed_app(db_session, tenant_id=7, env_id=env.id)
    await db_session.commit()

    out = await get_editor_url(app.id, _ctx(user, 7), db_session,
                               menu_type="MODEL", menu_id="M9", form_id="F3")
    assert out["ok"] is True
    # host 去掉 /backend；路径来自 build_editor_path
    assert out["url"] == "https://apaas.example.com/platform/TID9/default/data-model-fn-config?appId=AP123&menuId=M9&formId=F3&processVersion=false"


@pytest.mark.asyncio
async def test_editor_url_app_not_deployed(db_session):
    user, app = await _seed_app(db_session, tenant_id=7, apaas_app_id="", env_id=None)
    await db_session.commit()
    out = await get_editor_url(app.id, _ctx(user, 7), db_session, menu_type="MODEL", menu_id="", form_id="")
    assert out["ok"] is False and out.get("error_code")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_editor_url_endpoint.py -v`
Expected: FAIL — `ImportError: cannot import name 'get_editor_url'`

- [ ] **Step 3: 读现有 apaas-access-url + env 解析，确认字段**

Run: `cd backend && grep -n "apaas-access-url\|platform_tenant_id\|base_url\|_load_app_and_check_view\|class PlatformEnv" app/routes/applications/section_content.py app/models/__init__.py app/models/tenant.py | head -20`
确认：`Application.apaas_app_id` / `Application.platform_env_id`、`PlatformEnv.base_url` / `PlatformEnv.platform_tenant_id`、`_load_app_and_check_view` 的真实签名（在 section_content.py 内）。若 `PlatformEnv` 不在 `app.models` 顶层导出，用真实 import 路径替换测试里的 `from app.models import PlatformEnv`。

- [ ] **Step 4: 写端点**

在 `backend/app/routes/applications/section_content.py`（`apaas-access-url` 端点附近）加：

```python
@router.get("/{app_id}/editor-url")
async def get_editor_url(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    menu_type: str = "",
    menu_id: str = "",
    form_id: str = "",
) -> dict:
    """返回 host-absolute 的 aPaaS 原生编辑器深链（前端 window.open 新标签页用）。

    host = 应用绑定环境 PlatformEnv.base_url（去 /backend）；tid = platform_tenant_id。
    路径由 app.apaas_editor_url.build_editor_path 构建。
    """
    from sqlalchemy import select as _select
    from app.apaas_editor_url import build_editor_path
    from app.models import PlatformEnv

    app = await _load_app_and_check_view(app_id, ctx, db)
    if not app.platform_env_id or not app.apaas_app_id:
        return {"ok": False, "error_code": "APP_NOT_DEPLOYED", "message": "应用尚未部署到 aPaaS 平台"}
    env = (
        await db.execute(
            _select(PlatformEnv).where(
                PlatformEnv.id == app.platform_env_id,
                PlatformEnv.tenant_id == ctx.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if not env or not env.base_url or not env.platform_tenant_id:
        return {"ok": False, "error_code": "ENV_NOT_BOUND", "message": "应用未绑定有效平台环境"}
    host = env.base_url.rstrip("/").replace("/backend", "")
    path = build_editor_path(
        menu_type, apaas_app_id=str(app.apaas_app_id),
        menu_id=menu_id, form_id=form_id, tid=str(env.platform_tenant_id),
    )
    return {"ok": True, "url": f"{host}{path}"}
```

（`Annotated` / `Depends` / `get_auth_context` / `get_db` / `AuthContext` / `AsyncSession` / `_load_app_and_check_view` 该文件已 import；若 `select` 顶部已导入则去掉局部 import。）

- [ ] **Step 5: 跑测试确认通过 + import 冒烟**

Run: `cd backend && .venv/bin/python -m pytest tests/test_editor_url_endpoint.py -v` → PASS（2 passed）
Run: `cd backend && .venv/bin/python -c "import app.main; print('ok')"` → `ok`

- [ ] **Step 6: 提交**

```bash
git add backend/app/routes/applications/section_content.py backend/tests/test_editor_url_endpoint.py
git commit -m "feat(editor-url): add GET /applications/{id}/editor-url host-absolute deep link"
```
End commit body with Co-Authored-By trailer.

---

## Task A3: 前端 editor-url client + 共享按钮组件

**Files:**
- Create: `frontend/src/api/editorUrl.ts`
- Create: `frontend/src/components/v3/OpenLowcodeBackendButton.vue`

> 镜像 `ListDesignerPanel.openApaasApp()`（GET `{ok,url}` → `window.open(url,'_blank')` + alert 兜底）。

- [ ] **Step 1: 写 client**

Create `frontend/src/api/editorUrl.ts`:

```typescript
import request from '@/utils/request'

export interface EditorUrlResp { ok: boolean; url?: string; message?: string; error_code?: string }

export function getEditorUrl(
  appId: number,
  params: { menu_type?: string; menu_id?: string; form_id?: string } = {},
): Promise<EditorUrlResp> {
  return request({ url: `/applications/${appId}/editor-url`, method: 'get', params }) as unknown as Promise<EditorUrlResp>
}
```

- [ ] **Step 2: 写按钮组件**

Create `frontend/src/components/v3/OpenLowcodeBackendButton.vue`:

```vue
<template>
  <button class="open-lowcode-btn" :disabled="loading" :title="title" @click="onClick">
    <span aria-hidden="true">🔧</span> {{ loading ? '打开中…' : '打开低代码后台' }}
  </button>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { getEditorUrl } from '@/api/editorUrl'

const props = defineProps<{
  appId: number
  menuType?: string
  menuId?: string
  formId?: string | null
  title?: string
}>()

const loading = ref(false)

async function onClick() {
  loading.value = true
  try {
    const resp = await getEditorUrl(props.appId, {
      menu_type: props.menuType || '',
      menu_id: props.menuId || '',
      form_id: props.formId || '',
    })
    if (resp?.ok && resp.url) {
      window.open(resp.url, '_blank')
    } else {
      alert(resp?.message || '应用尚未部署到 aPaaS，无法打开后台')
    }
  } catch (e: any) {
    alert(`打开低代码后台失败：${e?.message || '网络错误'}`)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.open-lowcode-btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 5px 12px; font-size: 12.5px; border-radius: 6px;
  border: 1px solid var(--t-border-soft, #d1d5db); background: var(--t-bg-soft, #f3f4f6);
  color: var(--t-text-primary, #1f2937); cursor: pointer;
}
.open-lowcode-btn:hover:not(:disabled) { background: var(--t-bg-input, #e5e7eb); }
.open-lowcode-btn:disabled { opacity: .6; cursor: default; }
</style>
```

- [ ] **Step 3: 类型检查无新错**

Run: `cd frontend && npx vue-tsc --noEmit -p tsconfig.json 2>&1 | grep -E "editorUrl|OpenLowcodeBackendButton" || echo "clean"`
Expected: `clean`

- [ ] **Step 4: 提交**

```bash
git add frontend/src/api/editorUrl.ts frontend/src/components/v3/OpenLowcodeBackendButton.vue
git commit -m "feat(editor-url): frontend client + OpenLowcodeBackendButton"
```
End commit body with Co-Authored-By trailer.

---

## Task A4: 各面板挂深链按钮（暂与内嵌并存）

**Files:**
- Modify: `FormDesignerPanel.vue` / `ListDesignerPanel.vue` / `ProcessDesignerPanel.vue` / `DataSchemaEditor.vue` / `RoleManagePanel.vue` / `FormPermPanel.vue`（各加一个按钮，不动现有编辑模式）

> 这一步只**加按钮**，不删任何东西 —— 为 A5 实测铺路，内嵌编辑仍在做兜底。

- [ ] **Step 1: 每个面板 import + 在工具条放按钮**

对 6 个面板，各在 `<script setup>` import：
```typescript
import OpenLowcodeBackendButton from '@/components/v3/OpenLowcodeBackendButton.vue'
```
并在面板顶部工具条（跟现有按钮同级）放：
```vue
<OpenLowcodeBackendButton
  :app-id="props.appId"
  menu-type="MODEL"
  :menu-id="props.menuId || ''"
  :form-id="props.formId || null"
/>
```
（流程面板 form-id 用 `activeProcess?.form_id || props.formId`；schema/role/perm 面板 menu-type/menu-id 按其 props 传，缺就传空 → 落应用编辑总览。各面板 props 名以实际为准。）

- [ ] **Step 2: 类型检查 + import 冒烟**

Run: `cd frontend && npx vue-tsc --noEmit -p tsconfig.json 2>&1 | grep -E "FormDesignerPanel|ListDesignerPanel|ProcessDesignerPanel|DataSchemaEditor|RoleManagePanel|FormPermPanel" | grep -iv "预存\|preexist" || echo "no new errors"`
Expected: 不引入新错（仓库 vue-tsc 预存坏，重点确认按钮接入处无新错）

- [ ] **Step 3: 提交**

```bash
git add frontend/src/components/v3/FormDesignerPanel.vue frontend/src/components/v3/ListDesignerPanel.vue frontend/src/components/v3/ProcessDesignerPanel.vue frontend/src/components/v3/DataSchemaEditor.vue frontend/src/components/v3/RoleManagePanel.vue frontend/src/components/v3/FormPermPanel.vue
git commit -m "feat(editor-url): mount OpenLowcodeBackendButton on all config panels"
```
End commit body with Co-Authored-By trailer.

---

## Task A5: 【硬门】preview 实测编辑器深链 SSO 免登

**Files:** 无（验证）。**Phase B 不得在本任务通过前开始。**

- [ ] **Step 1: 起 preview，进一个已部署应用的配置面板**

`preview_start` 起前后端（后端加了端点要重启）。登录有平台环境的租户（如 57），打开一个已部署到 aPaaS 的应用配置（如报销申请）。

- [ ] **Step 2: 逐面板点「打开低代码后台」**

各面板点按钮，`preview_network` 看 `/api/applications/{id}/editor-url` 返 `{ok:true,url:...}`，确认 url 是真主机 host-absolute（`https://<apaas-host>/platform/{tid}/...`）。

- [ ] **Step 3: 验证新标签页 SSO 免登能编辑**

按钮 `window.open` 开新标签页 → **确认直接进 aPaaS 原生编辑器、免登、能改并保存**（不是登录页/白屏/报错）。

- [ ] **Step 4: 判定**

- 免登能编辑 → ✅ A5 通过，进 Phase B。
- 跳登录页 / 白屏 → ❌ 深链不免登。先解决：(a) URL 带 auth 参数（参考旧 `_auth=<token>` 注入），或 (b) 先 `POST /auth/exchange-apaas-token` 建 aPaaS 会话再开。解决并复测通过后才进 Phase B。**这是删兜底前的最后一道闸。**

---

# Phase B — 删内嵌 + 代理 + 改只读（A5 通过后）

> 各前端面板任务：移除编辑模式/控件，保留现有只读渲染为唯一视图。验证 = vue-tsc 无新错 + preview 只读渲染正常 + 按钮可用。删除任务：删文件 + 全局搜残引用。

## Task B1: FormDesignerPanel 改只读

**Files:** Modify `frontend/src/components/v3/FormDesignerPanel.vue`

- [ ] **Step 1: 删编辑模式三件套**

删除（精确块见 spec 调查）：
- 模式切换 markup（58-79 行 `.fbp-mode-toggle`）。
- `v-else` 内嵌编辑块（128-141 行，含 `<ApaasEmbedIframe ... menu-type="MODEL" mode="config">`）。
- `viewMode` ref（746）+ watch（751）；`import ApaasEmbedIframe`（149）。
把预览体 `<div v-if="viewMode === 'preview'" ...>`（82-126）改成常渲（去掉 `v-if`），并去掉 loading/error 上的 `&& viewMode === 'preview'` 守卫（35/38）。`.fbp-edit-banner`（1043-1054）/`.fbp-mode-toggle`/`.fbp-mode-btn`（932-960）CSS 删。A4 加的 `OpenLowcodeBackendButton` 保留。

- [ ] **Step 2: 类型检查 + preview**

Run: `cd frontend && npx vue-tsc --noEmit -p tsconfig.json 2>&1 | grep "FormDesignerPanel" | grep -iv 预存 || echo "no new errors"` → 无新错
preview：打开表单面板 → 只读预览正常、无编辑切换、按钮可用。

- [ ] **Step 3: 提交**

```bash
git add frontend/src/components/v3/FormDesignerPanel.vue
git commit -m "refactor(panels): FormDesignerPanel read-only, drop embed edit mode"
```
End commit body with Co-Authored-By trailer.

## Task B2: ListDesignerPanel 改只读

**Files:** Modify `frontend/src/components/v3/ListDesignerPanel.vue`

- [ ] **Step 1: 删编辑模式 + 死字段表机器**

删除：
- 模式切换 markup（35-60 `.ldp-mode-switch`）+ `viewMode` ref（324）+ edit→preview reload watch（759-761）。
- `v-else` 内嵌块（264-276 `<ApaasEmbedIframe ... designer-sub="list">`）+ `import ApaasEmbedIframe`（284）。
- 编辑专用死码：`ColumnRow` 接口、`columns` ref、`filteredColumns` computed、`onAddColumn/onBatchEdit/onEditColumn/onDeleteColumn`（524-538）。
把预览块 `<div v-else-if="viewMode === 'preview'" class="ldp-pv">`（86-262）改成默认渲染。保留 A4 按钮 + `openApaasApp`（如仍想留 runtime 入口）。

- [ ] **Step 2: 类型检查 + preview** → 同 B1 模式（grep ListDesignerPanel 无新错；preview 列表只读正常）。
- [ ] **Step 3: 提交** `refactor(panels): ListDesignerPanel read-only, drop embed edit mode`

## Task B3: ProcessDesignerPanel 改只读（去内嵌 + 编辑机器）

**Files:** Modify `frontend/src/components/v3/ProcessDesignerPanel.vue`

> 本面板 read-only/edit 用布尔 `readOnly`。x6 只读画布（`v-show="readOnly"` 157-173）保留；删 edit 侧。mock 实例 + 适应在 B4 处理（同文件、拆开两个 commit）。

- [ ] **Step 1: 删 业务/设计 切换 + 内嵌 + 编辑机器**

删除：
- `.pdp-mode-segment` 切换（88-106）。
- `<ApaasEmbedIframe v-if="!readOnly" ... designer-sub="process">`（175-186）+ `import`（245）。
- `!readOnly` 相关：sidebar-foot hint（144-147）、`ProcessNodePropsPanel` 块（227-234）、编辑机器 `onSave/onDeploy/serializeGraph/saving/deploying`（1151-1260）、`.pdp-iframe` CSS（1669）、`setViewMode`（624-648）里翻转 readOnly 的逻辑（改成恒只读：`const readOnly = ref(true)` 保留，删 setViewMode 或留个 noop）。

- [ ] **Step 2: 类型检查 + preview** → grep ProcessDesignerPanel 无新错；preview 流程面板只读拓扑+时间轴正常（mock 仍在，下个 task 删）。
- [ ] **Step 3: 提交** `refactor(panels): ProcessDesignerPanel read-only, drop embed design mode`

## Task B4: 流程去 mock 实例 + 修「适应」

**Files:** Modify `frontend/src/components/v3/ProcessDesignerPanel.vue`

- [ ] **Step 1: 删 mock 实例进度，保留真拓扑+节点角色**

删除：`mockInstance` ref + `MOCK_APPROVERS`/`MOCK_ACTIONS`（319-332）、`MockInstanceState`/`MockHistoryEntry` 类型（302-318）、`calcMockInstanceProgress`（665-700）、`paintInstanceProgress`（707-762）、`clearInstanceProgress`（765-789）、`timelineItems` computed（379-401）、业务 banner（67-75）、`<aside class="pdp-timeline">`（188-225）、`.pdp-biz-banner*`/`.pdp-timeline*`/`.pdp-node-current-pulse` CSS（1714-1925）、`paintInstanceProgress()` 调用点（640、1089-1091）。
保留：`buildNodeSpec`、`renderDefinition`、`computeAutoLayout`、`initGraph`、x6 画布、`onFitContent`。

> 可选：若想保留"节点→审批角色"的只读说明，用真 `nodeStates[id]` 的角色字段渲染一个静态侧栏（不带任何"谁批/何时/当前"假数据）。本计划默认只留画布拓扑，不重建侧栏（YAGNI）。

- [ ] **Step 2: 修「适应」自动适应**

`renderDefinition()` 删掉尾部 `if (readOnly.value){paintInstanceProgress()}`（1086-1091）后，在 `refreshCounts(g)` 之后、函数闭合前加：
```javascript
  refreshCounts(g)
  // 渲染后自动适应视口，免得图渲在视口外要手点「适应」
  if (readOnly.value) {
    void nextTick(() => onFitContent())
  }
}
```
（`nextTick` 已 import 于 241；`onFitContent` 在 894。）

- [ ] **Step 3: 类型检查 + preview** → grep 无新错；preview：流程图加载**即自动居中**（不用手点适应）、无假实例进度/无假 banner、真拓扑在。
- [ ] **Step 4: 提交** `fix(process): drop mock instance overlay + auto-fit on load`

## Task B5: schema / role / perm 面板改只读

**Files:** Modify `DataSchemaEditor.vue` / `RoleManagePanel.vue` / `FormPermPanel.vue`

- [ ] **Step 1: 删前端编辑控件 + 写调用，保留只读渲染**

- `DataSchemaEditor.vue`：删字段 CRUD 入口/弹窗 + 对 `/crud/model-field/add|update|disable` 的 `request` 调用（977/1135/1155/1401）；保留字段表/数据预览/SQL/关系只读渲染。挂 A4 按钮。
- `RoleManagePanel.vue`：删矩阵单元写交互 + 对 `/role-resource-matrix/cell` 的写调用（798）；保留矩阵 + 成员只读（READ `/role-resource-matrix` 595 保留）。挂按钮。
- `FormPermPanel.vue`：本已只读，仅确认 A4 按钮在。

- [ ] **Step 2: 类型检查 + preview** → 无新错；三面板只读渲染正常、无编辑控件、按钮可用。
- [ ] **Step 3: 提交** `refactor(panels): schema/role/perm panels read-only + deep-link`

## Task B6: ChatPage legacy iframe → 占位 + 按钮

**Files:** Modify `frontend/src/views/ChatPage.vue`

- [ ] **Step 1: 替换 legacy iframe 块为占位**

把 `v-else` legacy 整页 iframe 块（326-374）换成轻量占位：
```vue
<div v-else class="lowcode-deeplink-placeholder">
  <p class="lcd-hint">这块配置在低代码后台编辑。</p>
  <OpenLowcodeBackendButton :app-id="currentAppId" />
</div>
```
（`currentAppId` 用本页真实当前 app id ref。）删 `legacyMode` ref（2455-2459）及其所有 `!legacyMode`/`legacyMode` 守卫（144/162/172/185/193/200/209/278/287/296/305/314/321）—— 这些守卫去掉后原生面板恒显。删 ChatPage 本地 iframe 机器：`platformIframeUrl/Ref/Key`、`loadPlatformUrl/onPlatformIframeLoad/onIframeError/openPlatformNewTab/navigateIframeToApp` 及相关 refs（~2344-2760、3683-3686、4993-4997、8222-8226 区域，按真实引用清）。import `OpenLowcodeBackendButton`。

> ⚠️ ChatPage 巨大，本任务务必先 grep 所有 `platformIframe`/`legacyMode`/`buildPlatformProxy` 引用，逐一清干净再编译。

- [ ] **Step 2: 类型检查 + preview** → grep ChatPage 无新错（除预存）；preview：配置区原生面板正常显示，无 iframe；非原生 tab（若可达）显占位+按钮。
- [ ] **Step 3: 全局确认 platformIframe.ts / ApaasEmbedIframe 无引用了**

Run: `cd frontend && grep -rn "platformIframe\|ApaasEmbedIframe\|buildPlatformProxy" src/ | grep -v "platformIframe.ts\|ApaasEmbedIframe.vue"` → 应**无输出**（除这两个文件自身）。若有残引用，清掉再继续。

- [ ] **Step 4: 提交** `refactor(chat): replace legacy proxy iframe with deep-link placeholder`

## Task B7: 删 ApaasEmbedIframe.vue + platformIframe.ts

**Files:** Delete `frontend/src/components/v3/ApaasEmbedIframe.vue`, `frontend/src/utils/platformIframe.ts`

- [ ] **Step 1: 确认零引用后删**

Run: `cd frontend && grep -rn "ApaasEmbedIframe\|@/utils/platformIframe" src/` → 应只剩文件自身（或无）。然后：
```bash
git rm frontend/src/components/v3/ApaasEmbedIframe.vue frontend/src/utils/platformIframe.ts
```

- [ ] **Step 2: 类型检查无新错** → `cd frontend && npx vue-tsc --noEmit -p tsconfig.json 2>&1 | grep -iE "platformIframe|ApaasEmbedIframe" || echo "gone"` → `gone`
- [ ] **Step 3: 提交** `chore(panels): delete dead ApaasEmbedIframe + platformIframe util`

## Task B8: 删后端反向代理 + 死 REST 端点

**Files:** Delete `backend/app/routes/platform_proxy.py`; Modify `backend/app/main.py`、`crud_endpoints.py`、`section_content.py`

- [ ] **Step 1: 先确认 plugin-asset 中间件是否独立承重**

Run: `cd backend && grep -n "handle_plugin_asset_request\|_ensure_proxy_state\|platform_proxy" app/main.py`
读 `main.py:220` 用 `handle_plugin_asset_request` 的中间件（`/{32hex}/...` plugin 资源）。**判断**：它是否还服务真实 plugin 资产（与内嵌 iframe 无关的独立基建）？
- 若**独立承重**（仍有 plugin 资源走它）→ 把 `handle_plugin_asset_request` + 它依赖的最小代码**抽到独立小模块**（如 `app/plugin_assets.py`），不随代理一起删。
- 若**只服务内嵌 iframe**（删 iframe 后无来源）→ 连中间件一起删。
本步先定性（grep 调用来源 + 注释），把结论写进 commit message。

- [ ] **Step 2: 删代理文件 + main.py 三处引用**

```bash
git rm backend/app/routes/platform_proxy.py
```
`main.py` 删：line 41 `platform_proxy,`（import 块）、line 105 `from app.routes.platform_proxy import _ensure_proxy_state`（及其用处）、line 199 `app.include_router(platform_proxy.router)`、line 220 `from app.routes.platform_proxy import handle_plugin_asset_request`（按 Step 1 结论：删或改指向新 `plugin_assets`）。

- [ ] **Step 3: 删死 REST 端点（MCP 工具保留）**

- `crud_endpoints.py`：删 `/crud/model-field/add|update|disable`（101/137/170）+ 已死的 `/crud/dict-option/*`（205/238/269）+ `/crud/role/add`（302）。若整文件空了，连文件 + `applications/__init__.py:1935-1936` 注册一起删。**不删** mcp_server 里的 `add/update/disable_apaas_model_field`（spec_apply 用）。
- `section_content.py`：删 `/role-resource-matrix/cell` 写端点（2210）。保留 READ `/role-resource-matrix`（1606）。可选删 MCP `set_role_resource_permission`（mcp_server.py:3254，仅此端点用）。

- [ ] **Step 4: import 冒烟 + 全量回归**

Run: `cd backend && .venv/bin/python -c "import app.main; print('ok')"` → `ok`（代理路由/引用全摘除后仍 import OK）
Run: `cd backend && grep -rn "platform_proxy\|/crud/model-field\|role-resource-matrix/cell" app/ | grep -v "test"` → 无悬挂引用（除有意保留的）
Run: `cd backend && .venv/bin/python -m pytest -q 2>&1 | tail -3` → 新增 7 个 editor-url 测试绿；既有失败数=基线（6 预存），无新增。

- [ ] **Step 5: 提交** `chore(proxy): delete platform_proxy reverse proxy + dead REST edit endpoints`

## Task B9: 端到端回归（preview）

**Files:** 无。

- [ ] **Step 1: 重启 preview 前后端**（删了代理/路由，必须重启）。
- [ ] **Step 2: 逐面板验证**：6 个面板都只读渲染正常（表单预览/列表/流程真拓扑自动适应/schema 字段表/角色权限矩阵）、无任何内嵌 iframe、无编辑控件、每面板「打开低代码后台」开真主机编辑器免登可编辑。
- [ ] **Step 3: 确认无崩溃**：反复进出各面板、切应用，确认不再有内嵌编辑器渲染崩回首页（崩溃源已删）。`preview_console_logs` 无代理/iframe 相关报错。
- [ ] **Step 4: AI 配置链路未受影响**：对话改配置（配置助手）仍正常 —— 它不走代理，本次不应动到。

---

## Self-Review（对照 spec）

**Spec 覆盖：**
- 单元 1 深链接口（抽纯函数 + host-absolute）→ A1 + A2 ✓。
- 单元 2 共享按钮 → A3 ✓。
- 单元 3 面板改只读挂按钮 → B1/B2/B3/B5（表单/列表/流程/schema/role/perm）+ B6（非原生 tab 占位）✓。
- 单元 4 流程去 mock 实例 → B4 ✓。
- 单元 5 删反向代理+内嵌 → B6（ChatPage iframe）+ B7（前端组件/util）+ B8（后端代理+死端点）✓。
- 单元 6 修适应 → B4 Step 2 ✓。
- 实施顺序（先深链验证再删）→ Phase A（含 A5 硬门）/ Phase B 分段 ✓。
- 测试：editor-url TDD（A1/A2）+ 各阶段 vue-tsc/preview + B8 全量回归 ✓。
- 不在范围（真实例进度、后台编辑器本身、AI 配置链路）→ 计划未触碰，B9 Step 4 显式确认 AI 链路未受影响 ✓。

**Placeholder 扫描：** 无 TBD；前端删除任务用 spec 调查的精确行号块 + grep 收尾（不是"删相关代码"空泛指令）。

**类型一致性：** `build_editor_path(menu_type, *, apaas_app_id, menu_id, form_id, tid, step_index)` 全计划一致；`getEditorUrl(appId, {menu_type, menu_id, form_id})` ↔ 后端 query 参数一致；`OpenLowcodeBackendButton` props（app-id/menu-type/menu-id/form-id）前后一致。

## 风险 / 注意
- **A5 硬门**：编辑器深链不免登就别进 Phase B（删了内嵌兜底会没法编辑）。
- **plugin-asset 中间件**（B8 Step 1）：删代理前先判定它是否独立承重，别误删真 plugin 资产服务。
- ChatPage 巨大、iframe 机器引用散落多处（B6）—— 先 grep 全引用再清，编译兜底。
- 删代理前 `build_editor_path` 必须已抽走（A1 在 B8 之前）。
- 重启 preview backend 后浏览器可能缓存旧 JS，刷新即可（非 bug）。
