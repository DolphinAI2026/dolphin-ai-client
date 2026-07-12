# aPaaS Tenant Environment Binding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有平台管理“aPaaS 租户”页面为每个 Builder 租户提供一个默认 aPaaS 环境绑定界面。

**Architecture:** 复用 `Tenant`、`PlatformEnv` 和 `APaaSPlatformCredential`，在 `/api/mcp-platform` 增加一个租户环境绑定接口。管理端继续使用现有租户列表，只增加绑定状态、操作列和紧凑弹窗，不启用完整环境管理页。

**Tech Stack:** FastAPI、SQLAlchemy、Vue 3、Element Plus、Axios、Pytest、Vitest、Playwright

---

### Task 1: 增加租户环境绑定后端能力

**Files:**
- Modify: `backend/app/routes/mcp_platform.py`
- Create: `backend/tests/test_mcp_platform_tenant_binding.py`

- [ ] **Step 1: 写失败的后端测试**

新增测试，直接调用路由函数，验证绑定会复用选中的平台管理员凭据，并清理旧 Token：

```python
import pytest
from sqlalchemy import select

from app.deps import AuthContext
from app.models import APaaSPlatformCredential, PlatformEnv, Tenant, User
from app.routes.mcp_platform import APaaSTenantBindingRequest, bind_apaas_tenant_environment


@pytest.mark.asyncio
async def test_bind_apaas_tenant_environment_uses_selected_admin(db_session):
    tenant = Tenant(tenant_name="客户一", tenant_code="customer-1")
    admin_user = User(
        username="apaas-admin",
        hashed_password="hash",
        is_platform_admin=True,
        is_active=True,
    )
    db_session.add_all([tenant, admin_user])
    await db_session.flush()
    credential = APaaSPlatformCredential(
        user_id=admin_user.id,
        base_url="https://apaas.example.com",
        account="apaas-admin",
        password_enc="encrypted-password",
        token="platform-token",
        is_default=True,
        status="connected",
    )
    db_session.add(credential)
    await db_session.commit()

    result = await bind_apaas_tenant_environment(
        tenant.id,
        APaaSTenantBindingRequest(
            admin_id=f"db_platform_credential_{credential.id}",
            base_url="https://apaas.example.com/backend",
            platform_tenant_id="tenant-100",
        ),
        AuthContext(
            user=admin_user,
            tenant_id=tenant.id,
            tenant_role="platform_admin",
            org_permissions={"*": True},
        ),
        db_session,
    )

    env = (await db_session.execute(select(PlatformEnv))).scalar_one()
    await db_session.refresh(tenant)
    assert tenant.apaas_env_id == env.id
    assert tenant.apaas_tenant_id_str == "tenant-100"
    assert env.base_url == "https://apaas.example.com/backend"
    assert env.platform_tenant_id == "tenant-100"
    assert env.username == "apaas-admin"
    assert env.password_enc == "encrypted-password"
    assert env.token is None
    assert env.status == "disconnected"
    assert result["environmentBound"] is True
    assert result["adminAccount"] == "apaas-admin"
    assert "password_enc" not in result
    assert "token" not in result
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
pytest tests/test_mcp_platform_tenant_binding.py -q
```

Working directory: `backend`

Expected: FAIL，因为请求模型和绑定函数尚不存在。

- [ ] **Step 3: 实现最小绑定接口**

在 `backend/app/routes/mcp_platform.py` 增加：

```python
class APaaSTenantBindingRequest(BaseModel):
    admin_id: str = Field(..., min_length=1)
    base_url: str = Field(..., min_length=1)
    platform_tenant_id: str = Field(..., min_length=1)


def _platform_env_api_base(value: str) -> str:
    base = value.strip().rstrip("/")
    return base if base.endswith("/backend") else f"{base}/backend"


def _public_environment_binding(tenant: Tenant, env: PlatformEnv) -> dict[str, Any]:
    return {
        "localTenantId": tenant.id,
        "platformEnvId": env.id,
        "baseUrl": env.base_url,
        "platformTenantId": env.platform_tenant_id,
        "environmentBound": True,
        "adminAccount": env.username,
        "status": env.status,
    }
```

增加路由：

```python
@router.put("/apaas-tenants/{local_tenant_id}/binding")
async def bind_apaas_tenant_environment(
    local_tenant_id: int,
    body: APaaSTenantBindingRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    _require_platform_admin(ctx)
    tenant = (
        await db.execute(select(Tenant).where(Tenant.id == local_tenant_id))
    ).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="租户不存在")

    admins = await _load_db_admins(db)
    admin = _select_admin(admins, body.admin_id)
    base_url = _platform_env_api_base(body.base_url)
    platform_tenant_id = body.platform_tenant_id.strip()
    if not platform_tenant_id:
        raise HTTPException(status_code=400, detail="aPaaS 租户 ID 不能为空")

    env = None
    if tenant.apaas_env_id:
        env = (
            await db.execute(select(PlatformEnv).where(PlatformEnv.id == tenant.apaas_env_id))
        ).scalar_one_or_none()
    if env is None:
        env = PlatformEnv(
            tenant_id=tenant.id,
            env_name=f"{tenant.tenant_name}-默认环境",
            base_url=base_url,
            platform_tenant_id=platform_tenant_id,
            is_default=True,
        )
        db.add(env)
        await db.flush()

    changed = env.base_url != base_url or env.platform_tenant_id != platform_tenant_id
    env.base_url = base_url
    env.platform_tenant_id = platform_tenant_id
    env.username = admin["account"]
    env.password_enc = admin["password_enc"]
    env.is_default = True
    if changed or env.token:
        env.token = None
        env.status = "disconnected"
    tenant.apaas_env_id = env.id
    tenant.apaas_tenant_id_str = platform_tenant_id
    await db.commit()
    await db.refresh(env)
    return _public_environment_binding(tenant, env)
```

扩展 `_public_admin()`，增加非敏感的 `base_url`，供弹窗默认值使用：

```python
"base_url": _platform_env_api_base(row.get("base_url") or APAAS_BASE_URL),
```

扩展 `list_apaas_tenants(local_only=True)` 的每行响应：

```python
"baseUrl": env.base_url if env else "",
"platformTenantId": env.platform_tenant_id if env else tenant.apaas_tenant_id_str or "",
"environmentBound": bool(env and env.base_url and env.platform_tenant_id),
"adminAccount": env.username if env else "",
```

- [ ] **Step 4: 运行后端测试**

Run:

```bash
pytest tests/test_mcp_platform_tenant_binding.py -q
pytest tests/test_platform_admin_tenant_context.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交后端改动**

```bash
git add backend/app/routes/mcp_platform.py backend/tests/test_mcp_platform_tenant_binding.py
git commit -m "feat(admin): bind tenants to apaas environments"
```

### Task 2: 增加环境绑定界面

**Files:**
- Modify: `admin-spa/src/views/PlatformTenants.vue`
- Modify: `frontend/src/views/platformAdminBindings.spec.ts`

- [ ] **Step 1: 扩展失败的前端回归测试**

在 `frontend/src/views/platformAdminBindings.spec.ts` 增加：

```ts
it('supports one default environment binding per tenant', () => {
  expect(source).toContain('环境绑定')
  expect(source).toContain('绑定环境')
  expect(source).toContain('aPaaS 地址')
  expect(source).toContain('aPaaS 租户 ID')
  expect(source).toContain(
    'apiPut(`/mcp-platform/apaas-tenants/${bindingTarget.value.localTenantId}/binding`',
  )
})
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
npm test -- src/views/platformAdminBindings.spec.ts
```

Working directory: `frontend`

Expected: FAIL，因为绑定列、弹窗和接口调用尚不存在。

- [ ] **Step 3: 增加绑定状态和弹窗**

扩展 `AdminRow`：

```ts
base_url?: string
```

增加绑定状态：

```ts
const bindingVisible = ref(false)
const bindingSaving = ref(false)
const bindingTarget = ref<any | null>(null)
const bindingForm = ref({
  admin_id: '',
  base_url: '',
  platform_tenant_id: '',
})
```

增加打开和保存方法：

```ts
function openBinding(row: any) {
  const admin = admins.value.find((item) => item.id === selectedAdminId.value)
    || admins.value.find((item) => item.is_default)
    || admins.value[0]
  bindingTarget.value = row
  bindingForm.value = {
    admin_id: admin?.id || '',
    base_url: row.baseUrl || admin?.base_url || '',
    platform_tenant_id: row.platformTenantId || pick(row, ['tenantId', 'tenant_id']) || '',
  }
  bindingVisible.value = true
}

async function saveBinding() {
  if (!bindingTarget.value || !bindingForm.value.admin_id
      || !bindingForm.value.base_url.trim()
      || !bindingForm.value.platform_tenant_id.trim()) {
    ElMessage.warning('请选择平台管理员并填写 aPaaS 地址和租户 ID')
    return
  }
  bindingSaving.value = true
  try {
    await apiPut(
      `/mcp-platform/apaas-tenants/${bindingTarget.value.localTenantId}/binding`,
      bindingForm.value,
    )
    bindingVisible.value = false
    await loadLocalTenants()
    ElMessage.success('环境绑定已保存')
  } catch (e: any) {
    ElMessage.error(errorMessage(e, '环境绑定失败'))
  } finally {
    bindingSaving.value = false
  }
}
```

租户表增加“环境绑定”列和“绑定环境/修改绑定”按钮，并增加包含管理员账号、aPaaS 地址、aPaaS 租户 ID 的 `el-dialog`。

修改 `syncTenants()`：远端同步成功后调用 `await loadLocalTenants()`，确保表格始终展示带本地绑定字段的数据。

- [ ] **Step 4: 运行前端测试和构建**

Run:

```bash
npm test -- src/views/platformAdminBindings.spec.ts src/views/platformAdminEmbedState.spec.ts
```

Working directory: `frontend`

Expected: 6 个以上测试全部 PASS。

Run:

```bash
npm run build
```

Working directory: `admin-spa`

Expected: `vue-tsc` 和 Vite build 成功。

- [ ] **Step 5: 提交前端改动**

```bash
git add admin-spa/src/views/PlatformTenants.vue frontend/src/views/platformAdminBindings.spec.ts
git commit -m "feat(admin): add tenant environment binding UI"
```

### Task 3: 本地联调和浏览器验证

**Files:**
- Runtime configuration only

- [ ] **Step 1: 重启本地后端**

继续使用：

```bash
APAAS_BASE_URL=https://apaas-trial.definesys.cn/backend
```

不得在命令输出、截图、日志或代码文件中记录真实密码和 Token。

- [ ] **Step 2: 验证接口**

使用 Builder 平台管理员登录后：

```text
GET /api/mcp-platform/apaas-tenants?local_only=true&page_size=500
```

确认响应包含 `environmentBound`、`baseUrl`、`platformTenantId` 和 `adminAccount`，且不包含密码或 Token。

- [ ] **Step 3: Playwright 验证**

打开：

```text
http://localhost:5174/platform-admin/tenants
```

确认：

- 租户表包含“环境绑定”列。
- “绑定环境”弹窗可打开。
- 平台管理员、地址和租户 ID 能回填。
- 保存失败会保留弹窗并显示错误。
- 页面没有白屏、加载遮罩残留或浏览器运行时错误。

- [ ] **Step 4: 最终检查**

Run:

```bash
git diff --check
git status --short
```

只保留本任务可归属文件，不提交账号、密码、Token 或本地数据库。
