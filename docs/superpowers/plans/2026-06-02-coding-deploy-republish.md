# AI Coding 自开发「装回应用 + 重新发布」+ 分场景入口 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 AI Coding 在用户显式点「装回应用」并确认后,把自开发包上传→关联到应用→(页面类)建菜单→重新发布;并在进入 Coding 时分「在应用上定制 / 做通用组件」两场景。

**Architecture:** 后端新增一个编排端点 `POST /api/coding/workspace/{ws_id}/deploy-to-app`,串起既有积木(`WorkspaceManager.build_and_package` + coding.py 上传逻辑 + `APaaSClient.{query_app_dev_kits,enable_self_dev_config,attach_apaas_source_relation,create_self_dev_menu,deploy_app}` + `extension.publish_extension_update`)。codegen agent 工具集不变(只读)。前端在 CodingPage 加分场景入口、context banner、「装回应用」按钮 + InstallModal 确认弹窗,确认即调该端点。

**Tech Stack:** 后端 FastAPI + SQLAlchemy async + httpx;测试 pytest(`backend/tests/`,async via conftest)。前端 Vue 3 + Vite,design-v3 tokens,视觉对照 `docs/design-refs/2026-06-02-coding-prototype/screens_coding.jsx`。

**Spec:** `docs/superpowers/specs/2026-06-02-coding-deploy-republish-design.md`

---

## File Structure

**后端**
- Modify: `backend/app/routes/coding.py` — 抽出可复用上传 helper `_build_and_upload_kits(...)`(从 `upload_workspace_to_platform` 提取);新增 `deploy_to_app` 端点 + `DeployToAppRequest`/响应模型。
- Reuse(不改): `backend/app/apaas_client.py`(5 方法)、`backend/app/routes/applications/extension.py`(`_load_app_and_env` / `_ensure_env_token` / `publish_extension_update`)、`backend/app/coding/workspace.py`(`build_and_package`/`build_and_package_dual`)。
- Test: `backend/tests/test_coding_deploy_to_app.py`(mock APaaSClient + WorkspaceManager,验证编排分支)。

**前端**
- Modify: `frontend/src/api/coding.ts` — 加 `deployToApp(wsId, body)`。
- Create: `frontend/src/views/coding/InstallModal.vue` — 「装回应用」确认弹窗(对照原型 `InstallModal`)。
- Create: `frontend/src/views/coding/CodingSceneEntry.vue` — 分场景入口(bound/lib + 目标应用),对照原型 `CodingEntry`。
- Modify: `frontend/src/views/CodingPage.vue` — 新会话挂 CodingSceneEntry;会话顶 context banner;产物面板加「装回应用 / 发布到资产库」按钮 → InstallModal。

> CodingPage 已超大:新 UI 抽成 InstallModal.vue / CodingSceneEntry.vue 两个独立组件,CodingPage 只做挂载 + 状态。**不动**消息区(本 session 已统一的 native 渲染)/ composer / 历史回放 / IDE。

---

## Task 1: 后端 — 抽出可复用上传 helper

把 `upload_workspace_to_platform`(coding.py:2541)里「构建 + 上传 developmentKit + 拿 kit_id」的逻辑提成独立函数,供新端点复用,避免复制粘贴。

**Files:**
- Modify: `backend/app/routes/coding.py`(在 `upload_workspace_to_platform` 上方加 helper;原端点改为调用 helper)
- Test: `backend/tests/test_coding_deploy_to_app.py`

- [ ] **Step 1: 写失败测试 — helper 上传后能用 fileName 反查到 kit_id**

`backend/tests/test_coding_deploy_to_app.py`:
```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

@pytest.mark.asyncio
async def test_build_and_upload_kits_returns_kit_ids(tmp_path):
    from app.routes import coding as coding_routes

    # mock WorkspaceManager: 单端项目 → build_and_package 返回一个 zip 路径
    zip_path = tmp_path / "form-page-demo.zip"
    zip_path.write_bytes(b"PK\x03\x04demo")
    ws_mgr = MagicMock()
    ws_mgr.get_workspace_path.return_value = tmp_path
    ws_mgr._read_meta.return_value = {"project_type": "form-page", "display_name": "Demo"}
    ws_mgr.build_and_package = AsyncMock(return_value=str(zip_path))

    env = MagicMock(base_url="https://x", platform_tenant_id="t1", token="tok",
                    username="u", password_enc=None)

    # mock 平台上传返回 ok;mock query_app_dev_kits 反查到 id
    with patch.object(coding_routes.httpx, "AsyncClient") as MockHttp, \
         patch.object(coding_routes, "APaaSClient") as MockClient:
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"code": "ok"}
        MockHttp.return_value.__aenter__.return_value.post = AsyncMock(return_value=resp)
        MockClient.return_value.query_app_dev_kits = AsyncMock(
            return_value=[{"id": "999", "fileName": "form-page-demo.zip", "fileType": "FRONTENGINE"}]
        )

        result = await coding_routes._build_and_upload_kits(
            ws_mgr=ws_mgr, ws_id="ws1", env=env, db=AsyncMock(),
        )

    assert result["kit_ids"] == ["999"]
    assert result["file_type"] == "FRONTENGINE"
    assert result["project_type"] == "form-page"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_coding_deploy_to_app.py -v`
Expected: FAIL — `AttributeError: module 'app.routes.coding' has no attribute '_build_and_upload_kits'`

- [ ] **Step 3: 实现 `_build_and_upload_kits`**

在 `backend/app/routes/coding.py` 的 `upload_workspace_to_platform` 定义之前插入(复用同文件已有的 `_PROJECT_TYPE_TO_FILE_TYPE` / `_build_upload_form_data` / `_query_existing_development_kits` / `_find_kit_by_filename` / `_refresh_env_token`):
```python
async def _build_and_upload_kits(ws_mgr, ws_id: str, env, db) -> dict:
    """构建 workspace → 上传 developmentKit → 反查 kit_id。
    返回 {kit_ids: [str], file_type: str, project_type: str, display_name: str, file_names: [str]}。
    复用 upload_workspace_to_platform 的上传细节(update-if-exists + token 自愈)。
    """
    import time, uuid
    ws_path = ws_mgr.get_workspace_path(ws_id)
    meta = ws_mgr._read_meta(ws_path)
    project_type = meta.get("project_type", "")
    display_name = meta.get("display_name") or meta.get("project_name", ws_id)

    # 双端项目:两个包
    if project_type == ProjectType.FORM_COMPONENT_DUAL.value:
        packages = await ws_mgr.build_and_package_dual(ws_id)  # [(zip_path, fileType), ...]
    else:
        file_type = _PROJECT_TYPE_TO_FILE_TYPE.get(project_type)
        if not file_type:
            raise HTTPException(status_code=400, detail=f"不支持的项目类型: {project_type}")
        if project_type in {"backend-api", "backend-feign", "backend-scheduled"}:
            output_dir = ws_mgr._get_build_output_dir(ws_path)
            jars = [j for j in output_dir.glob("*.jar") if not j.name.endswith(".original")]
            if not jars:
                raise HTTPException(status_code=500, detail="未找到编译产物 JAR,请先构建")
            packages = [(str(jars[0]), file_type)]
        else:
            packages = [(await ws_mgr.build_and_package(ws_id), file_type)]

    add_url = f"{env.base_url.rstrip('/')}/xdap-app/selfdevelopment/add/developmentKit"
    update_url = f"{env.base_url.rstrip('/')}/xdap-app/selfdevelopment/update/developmentKit"
    file_names = [Path(p).name for p, _ in packages]
    key_word = (file_names[0][:-4] if file_names[0].endswith(".zip") else file_names[0])
    existing = await _query_existing_development_kits(env.base_url, env.platform_tenant_id, env.token, key_word)

    token = env.token
    for zip_path_str, ft in packages:
        fp = Path(zip_path_str)
        kit = _find_kit_by_filename(existing, fp.name)
        form_data = _build_upload_form_data(
            file_type=ft, description=f"{display_name} - apaas-builder",
            version_code=uuid.uuid4().hex, upload_id=str(int(time.time() * 1000)), existing_kit=kit,
        )
        target = update_url if kit else add_url
        ct = "application/java-archive" if fp.suffix == ".jar" else "application/zip"
        async with httpx.AsyncClient(verify=False, timeout=120.0) as http:
            r = await http.post(target, headers={
                "xdaptenantid": env.platform_tenant_id, "xdaptoken": token,
                "xdaptimestamp": str(int(time.time() * 1000)),
            }, files={"file": (fp.name, fp.read_bytes(), ct)}, data=form_data)
        data = r.json()
        if r.status_code == 401 or data.get("code") == 401:
            token = await _refresh_env_token(env, db)
            # token 刷新后该包重传一次(简化:沿用同 form_data)
            async with httpx.AsyncClient(verify=False, timeout=120.0) as http:
                await http.post(target, headers={
                    "xdaptenantid": env.platform_tenant_id, "xdaptoken": token,
                    "xdaptimestamp": str(int(time.time() * 1000)),
                }, files={"file": (fp.name, fp.read_bytes(), ct)}, data=form_data)

    # 反查 kit_id(add/update 响应不一定带 id;用 fileName 精准匹配)
    client = APaaSClient(base_url=env.base_url, tenant_id=env.platform_tenant_id, token=token)
    kits = await client.query_app_dev_kits("", file_name=key_word)
    kit_ids = [str(k["id"]) for fn in file_names for k in kits if k.get("fileName") == fn and k.get("id")]
    return {
        "kit_ids": kit_ids, "file_type": packages[0][1], "project_type": project_type,
        "display_name": display_name, "file_names": file_names,
    }
```
(注:`ProjectType` / `Path` / `httpx` / `APaaSClient` / `HTTPException` 在 coding.py 已 import。)

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_coding_deploy_to_app.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/coding.py backend/tests/test_coding_deploy_to_app.py
git commit -m "feat(coding): 抽出 _build_and_upload_kits 上传 helper(供 deploy-to-app 复用)"
```

---

## Task 2: 后端 — `deploy-to-app` 编排端点

**Files:**
- Modify: `backend/app/routes/coding.py`(新端点 + 请求/响应模型;复用 extension.py 的 `_load_app_and_env`/`_ensure_env_token`/`publish_extension_update`)
- Test: `backend/tests/test_coding_deploy_to_app.py`(追加)

- [ ] **Step 1: 写失败测试 — bound 页面类:upload→enable→attach→menu→republish 都被调用**

追加到 `backend/tests/test_coding_deploy_to_app.py`:
```python
@pytest.mark.asyncio
async def test_deploy_to_app_bound_page_runs_full_chain(tmp_path):
    from app.routes import coding as coding_routes

    app_rec = MagicMock(id=10, apaas_app_id="84799", platform_app_id="84799",
                        app_code="demo", platform_env_id=1)
    env = MagicMock(base_url="https://x", platform_tenant_id="t1", token="tok")
    client = MagicMock()
    client.enable_self_dev_config = AsyncMock(return_value={"code": "ok"})
    client.attach_apaas_source_relation = AsyncMock(return_value={"code": "ok"})
    client.create_self_dev_menu = AsyncMock(return_value={"code": "ok"})
    client.query_app_detail = AsyncMock(return_value={"currentVersion": "1.0.0"})
    client.deploy_app = AsyncMock(return_value={"code": "ok"})

    with patch.object(coding_routes, "_build_and_upload_kits", AsyncMock(return_value={
            "kit_ids": ["999"], "file_type": "FRONTENGINE", "project_type": "form-page",
            "display_name": "Demo", "file_names": ["form-page-demo.zip"]})), \
         patch.object(coding_routes, "_load_app_and_env", AsyncMock(return_value=(app_rec, env))), \
         patch.object(coding_routes, "_ensure_env_token", AsyncMock(return_value="tok")), \
         patch.object(coding_routes, "APaaSClient", return_value=client), \
         patch.object(coding_routes, "publish_extension_update", AsyncMock(return_value=1)):
        result = await coding_routes._deploy_to_app_impl(
            ws_id="ws1", local_app_id=10, ctx=MagicMock(tenant_id=1), db=AsyncMock())

    assert result["status"] == "installed"
    client.enable_self_dev_config.assert_awaited_once()
    client.attach_apaas_source_relation.assert_awaited_once()
    client.create_self_dev_menu.assert_awaited_once()   # 页面类才建菜单
    client.deploy_app.assert_awaited_once()              # republish

@pytest.mark.asyncio
async def test_deploy_to_app_lib_uploads_only(tmp_path):
    from app.routes import coding as coding_routes
    with patch.object(coding_routes, "_build_and_upload_kits", AsyncMock(return_value={
            "kit_ids": ["999"], "file_type": "FRONTCOMPONENT", "project_type": "form-component",
            "display_name": "Tree", "file_names": ["c.zip"]})):
        # lib 模式不传 local_app_id → 只上传,不 attach
        result = await coding_routes._deploy_to_app_impl(
            ws_id="ws1", local_app_id=None, ctx=MagicMock(tenant_id=1), db=AsyncMock())
    assert result["status"] == "uploaded_only"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_coding_deploy_to_app.py -v`
Expected: FAIL — `_deploy_to_app_impl` 不存在

- [ ] **Step 3: 实现 `_deploy_to_app_impl` + 端点**

在 coding.py 顶部 import 区加:`from app.routes.applications.extension import _load_app_and_env, _ensure_env_token, publish_extension_update`。**若触发循环依赖**(extension.py 间接 import 了 coding),改成在 `_deploy_to_app_impl` 函数体内做延迟 import(`from app.routes.applications.extension import ...`)。`APaaSClient` 已在 coding.py 顶部 import(`_refresh_env_token` 在用),`select` / `PlatformEnv` 若缺则补 import。
新增:
```python
class DeployToAppRequest(BaseModel):
    local_app_id: Optional[int] = None   # bound 传;lib 不传

_PAGE_TYPES = {"menu-page", "form-page", "mobile-page"}

async def _deploy_to_app_impl(ws_id: str, local_app_id, ctx, db) -> dict:
    ws_mgr = WorkspaceManager()
    # lib(无 app)→ 只上传到组件库
    if not local_app_id:
        # lib 也要 env 才能上传:取租户默认 env
        env = (await db.execute(select(PlatformEnv).where(PlatformEnv.tenant_id == ctx.tenant_id))).scalars().first()
        if not env:
            raise HTTPException(status_code=400, detail="租户未配置平台环境")
        env.token = await _ensure_env_token(env, db)
        up = await _build_and_upload_kits(ws_mgr, ws_id, env, db)
        return {"status": "uploaded_only", "kits": up["file_names"],
                "hint": "已传到自开发资产库,可在表单设计器引用 / 去 Builder 关联应用"}

    # bound:解析 app(本地 + 平台两个 id)
    app, env = await _load_app_and_env(local_app_id, ctx, db)
    if not app.apaas_app_id:
        raise HTTPException(status_code=400, detail="应用未部署到平台(无 apaas_app_id),无法装回")
    if env is None:
        raise HTTPException(status_code=400, detail="租户未配置平台环境")
    env.token = await _ensure_env_token(env, db)
    apaas_app_id = str(app.apaas_app_id)

    up = await _build_and_upload_kits(ws_mgr, ws_id, env, db)
    if not up["kit_ids"]:
        raise HTTPException(status_code=502, detail="上传成功但反查不到 kit id,无法 attach")

    client = APaaSClient(base_url=env.base_url, tenant_id=env.platform_tenant_id, token=env.token)
    await client.enable_self_dev_config(apaas_app_id, "ENABLE")
    await client.attach_apaas_source_relation(apaas_app_id, object_ids=up["kit_ids"])

    menu = None
    if up["project_type"] in _PAGE_TYPES:
        # link_url = 自开发组件注册名(取 workspace apaas.json 的 output/register 名)
        apaas_cfg = ws_mgr._read_apaas_config(ws_mgr.get_workspace_path(ws_id))
        register = WorkspaceManager._resolve_output_name(apaas_cfg, up["display_name"])
        await client.create_self_dev_menu(apaas_app_id, menu_name=up["display_name"], link_url=register)
        menu = up["display_name"]

    # republish:复用 republish 的版本号策略(query_app_detail → deploy_app,失败 patch+1)
    detail = await client.query_app_detail(apaas_app_id)
    version = detail.get("currentVersion") or detail.get("version") or "1.0.0"
    try:
        await client.deploy_app(apaas_app_id, version, abstract="自开发装回自动重发")
    except Exception as e:
        parts = version.split("."); 
        if "版本" in str(e) or "version" in str(e).lower():
            parts[-1] = str(int(parts[-1]) + 1); version = ".".join(parts)
            await client.deploy_app(apaas_app_id, version, abstract="自开发装回自动重发")
        else:
            raise

    await publish_extension_update(app.id, "republish_done", {"kits": up["file_names"]})
    return {"status": "installed", "app": {"local_app_id": app.id, "name": getattr(app, "name", "")},
            "menu": menu, "version": version, "kits": up["file_names"]}

@router.post("/workspace/{ws_id}/deploy-to-app")
async def deploy_to_app(
    ws_id: str,
    body: DeployToAppRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="admin")
    return await _deploy_to_app_impl(ws_id, body.local_app_id, ctx, db)
```
(`PlatformEnv` / `select` / `BaseModel` / `Optional` / `WorkspaceManager` / `AuthContext` / `Depends` / `get_auth_context` / `get_db` 在 coding.py 已可用;若 `PlatformEnv` 未 import 则补 `from app.models import PlatformEnv`。)

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_coding_deploy_to_app.py -v`
Expected: PASS(2 个新测试 + Task1 的 1 个)

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/coding.py backend/tests/test_coding_deploy_to_app.py
git commit -m "feat(coding): deploy-to-app 端点(upload→enable→attach→页面建菜单→republish + lib 只上传)"
```

---

## Task 3: 前端 — `deployToApp` API

**Files:**
- Modify: `frontend/src/api/coding.ts`

- [ ] **Step 1: 加 api 方法**(对照同文件 `uploadToPlatform` 的写法,coding.ts:253)
```ts
/** 装回应用:upload→attach→(页面)菜单→republish;lib 模式不传 localAppId 只上传 */
deployToApp(wsId: string, localAppId?: number) {
  return request.post(`/coding/workspace/${wsId}/deploy-to-app`,
    { local_app_id: localAppId ?? null }, { timeout: 300000 })
},
```

- [ ] **Step 2: 验证编译**

Run: `cd frontend && VITE_BASE_URL=/ai-builder/ npx vite build 2>&1 | tail -3`
Expected: `✓ built`

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/coding.ts
git commit -m "feat(coding): coding.ts 加 deployToApp api"
```

---

## Task 4: 前端 — InstallModal.vue(装回应用确认弹窗)

对照 `docs/design-refs/2026-06-02-coding-prototype/screens_coding.jsx` 的 `InstallModal`(rows:应用页面/路由/权限/资产登记 + 编译通过 badge + 取消/确认装回),用 design-v3 tokens 实现 Vue 版。

**Files:**
- Create: `frontend/src/views/coding/InstallModal.vue`

- [ ] **Step 1: 写组件**

props:`{ visible: boolean; appName: string; rows: {icon,title,desc}[]; compiled: boolean; loading: boolean }`;emits:`close` / `confirm`。结构 = 遮罩 + 卡(头:store 图标 + 「装回应用」+ `{appName}` + 编译通过/失败 badge;body:rows 列表;footer:取消 + 确认装回[loading 时 disabled])。样式对照原型 InstallModal 的内联 style(radius 18 / sh-5 / brand-soft 图标格等),搬成 `<style scoped>` 用 `var(--t-*)`/`var(--r-*)`/`var(--sh-*)` token(参照 CodingPage 现有 token 命名)。

- [ ] **Step 2: 验证编译 + 视觉**

Run: `cd frontend && VITE_BASE_URL=/ai-builder/ npx vite build 2>&1 | tail -3`(过编译)
然后在 live 临时挂一下 InstallModal(visible=true 假数据)→ preview_screenshot 对照原型 InstallModal 截图收敛(用 ce-frontend-design 的 screenshot 迭代)。
Expected: 编译通过;弹窗视觉与原型一致(头/rows/badge/按钮)。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/coding/InstallModal.vue
git commit -m "feat(coding): InstallModal 装回应用确认弹窗(对照设计原型)"
```

---

## Task 5: 前端 — CodingSceneEntry.vue(分场景入口)

对照原型 `CodingEntry`:hero「配置装不下的,写代码搞定」+ 两模式卡(在应用上定制 bound / 做通用组件 lib)+ 目标应用/产物去向行 + textarea + 示例 chips(随模式切换)。

**Files:**
- Create: `frontend/src/views/coding/CodingSceneEntry.vue`

- [ ] **Step 1: 写组件**

state:`mode: 'bound'|'lib'`(默认 bound)、`targetApp`(bound 时,默认 = 传入的当前会话绑定 app,可改)、`input`。props:`{ apps: {id,name}[]; defaultAppId?: number }`;emits:`submit({ mode, appId, text })`。bound 显「目标应用」选择器 + 复用提示;lib 显「产物去向 = 自开发资产库」。示例 chips 按 mode 切(bound:给销售CRM加看板等;lib:多选客户树等)。样式对照原型 CodingEntry,用 design-v3 token。

- [ ] **Step 2: 验证编译 + 视觉**

Run: `cd frontend && VITE_BASE_URL=/ai-builder/ npx vite build 2>&1 | tail -3`
live 挂载新会话 → screenshot 对照原型 CodingEntry(用户已给过该屏截图)收敛。
Expected: 编译通过;入口视觉与原型一致,模式切换/目标应用选择可用。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/coding/CodingSceneEntry.vue
git commit -m "feat(coding): CodingSceneEntry 分场景入口(bound/lib + 目标应用,对照原型)"
```

---

## Task 6: 前端 — CodingPage 接线(入口 + banner + 装回按钮 + 弹窗)

**Files:**
- Modify: `frontend/src/views/CodingPage.vue`

- [ ] **Step 1: 挂分场景入口**

新会话且 `streamMessages.length === 0` 时(现有 `.coding-empty-thread` 条件处,CodingPage:120),用 `<CodingSceneEntry :apps="..." :default-app-id="handoffSourceApp?.id" @submit="onSceneSubmit" />` 替换/包裹空态;`onSceneSubmit({mode,appId,text})` 记录 `deployMode/deployAppId` 到组件状态,然后把 `text` 灌进现有发送流程(等同 composer send)。

- [ ] **Step 2: context banner**

bound 模式下,会话区顶部加一行 banner(对照原型 context banner:layers 图标 + `上下文 · {appName}`)。无绑定 app 不显示。

- [ ] **Step 3: 产物面板按钮 + 弹窗**

产物面板(`cap-*` 区)加按钮:`deployMode==='bound'` → 「装回应用」(点击:先组装 rows[页面/路由/权限/资产登记] + 编译状态 → 打开 InstallModal);`deployMode==='lib'` → 「发布到资产库」(直接调 `codingApi.deployToApp(wsId)` 不传 appId)。InstallModal `@confirm` → `loading=true` → `codingApi.deployToApp(wsId, deployAppId)` → 成功 toast(可跳自开发资产库)+ 关闭;失败 ElMessage 报错。

- [ ] **Step 4: 验证编译 + live 端到端**

Run: `cd frontend && VITE_BASE_URL=/ai-builder/ npx vite build 2>&1 | tail -3`
live:新会话 → 选「在应用上定制」+ 目标应用 → 发需求 → (codegen 完)产物面板「装回应用」→ InstallModal 确认 → 观察后端日志走 upload→attach→menu→republish。
Expected: 编译通过;bound 端到端能触发部署;lib 模式只上传。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/CodingPage.vue
git commit -m "feat(coding): CodingPage 接入分场景入口 + context banner + 装回应用/发布按钮 + InstallModal"
```

---

## Task 7: 真实 trial 端到端验证

- [ ] **Step 1: 组件类**(form-component):新会话「做通用组件」→ 生成 → 「发布到资产库」→ 平台组件库出现该 kit。
- [ ] **Step 2: 页面类**(form-page,可用刚才公告通知会话 replay 思路或新建):新会话「在应用上定制」绑定一个有 apaas_app_id 的 app → 生成 → 「装回应用」→ InstallModal 确认 → 平台:kit 已 attach、菜单已建、应用版本已 +1(republish)。
- [ ] **Step 3: 回归**:READ 路径 / 历史回放 / 消息区 native 渲染 / composer / dolphin.ai / 产物面板 原有功能无伤。
- [ ] **Step 4:** 最终 `npx vite build` + `cd backend && ./.venv/bin/python -m pytest tests/test_coding_deploy_to_app.py -v` 全绿。

---

## 备注 / 风险
- **kit_id 反查**:add/update 响应不一定带 id,统一用 `query_app_dev_kits(file_name=key_word)` 按 fileName 精准匹配(同 mcp_server 既有做法)。若平台模糊匹配命中多条,按完整 fileName 过滤。
- **菜单 link_url**:页面类的注册名来自 workspace `apaas.json`(`_resolve_output_name`);若取不到,degrade 为不建菜单 + 提示用户手动在应用里挂菜单。
- **republish 版本号**:复用 republish 路由的「query_app_detail.currentVersion → deploy_app,版本冲突则 patch+1」策略。
- **错误隔离**:enable/attach/menu/republish 任一步失败,抛 HTTPException 带 error_code/message,前端 InstallModal 显错、kit 已上传可重试,不回滚。
- **不碰**:codegen agent 工具(只读)、`upload-to-platform` 原端点、消息区 native 渲染、IDE(code-server)。
