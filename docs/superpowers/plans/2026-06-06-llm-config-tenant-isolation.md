# LLM 配置租户隔离 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让每个租户只能看到、使用、管理自己 `tenant_id` 名下的 LLM 配置;没配模型时明确报错而非借别租户的 key。

**Architecture:** "管道"已铺好——所有解析函数早已收 `tenant_id` 参数,只是 WHERE 里没用它。改动分四层:① Builder 自带的 `_resolve_llm_config` 加租户过滤(已有红测试);② `routes/llm_configs.py` 六个共享解析函数加租户过滤(自动堵 Coding/options/conversations/harness 各调用方的泄漏);③ admin 端点加租户作用域 + 增删改测的归属授权;④ admin-spa 前端加平台管理员租户选择器。

**Tech Stack:** FastAPI + SQLAlchemy async(后端)、pytest + pytest-asyncio + in-memory SQLite(`db_session` fixture,每测试一份新 schema)、Vue 3 + Element Plus(admin-spa)。

**关键事实(实现前必读):**
- 后端 `backend/run.py` reload=False,**改后端必重启 preview backend 进程**才生效。
- 本地 DB = SQLite,测试库 = in-memory(`conftest.py` 的 `db_session`)。
- `.venv` 是 py3.13:`cd backend && source .venv/bin/activate`。
- 路由函数的参数都是 `Depends(...)`,但在测试里可**直接当普通 async 函数调用**,手动传构造好的 `ctx` / `db_session`。
- `AuthContext` 是 dataclass:`AuthContext(user, tenant_id, tenant_role, org_permissions, ...)`。`User` 只有 `username`、`hashed_password` 非空。
- 平台管理员判定:`ctx.tenant_role == "platform_admin" or ctx.user.is_platform_admin`。

---

### Task 1: Builder 路径 `_resolve_llm_config` 租户隔离(已有红测试 → 绿)

`app/ai_chat/agent.py:_resolve_llm_config` 现在三段查询都不按 `tenant_id` 过滤,会借别租户的 default 模型。已有测试 `tests/test_aichat_no_cross_tenant_model.py` 捕获了期望行为,当前是**红的**。本任务让它变绿。

**Files:**
- Modify: `backend/app/ai_chat/agent.py:404-455`(`_resolve_llm_config` 的三段查询)
- Test: `backend/tests/test_aichat_no_cross_tenant_model.py`(已存在,不改)

- [ ] **Step 1: 跑现有测试确认它是红的**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/test_aichat_no_cross_tenant_model.py -v`
Expected: FAIL — `DID NOT RAISE <class 'RuntimeError'>`(租户 A 借到了租户 B 的模型)。

- [ ] **Step 2: 给三段查询都加 `LLMConfig.tenant_id == session.tenant_id`**

`session` 是 `AIChatSession`,建会话时 `tenant_id=ctx.tenant_id`,所以 `session.tenant_id` 可直接用。

第一段(selected,~411 行 where 内):
```python
        res = await db.execute(
            select(LLMConfig).where(
                LLMConfig.id == session.selected_llm_config_id,
                LLMConfig.tenant_id == session.tenant_id,
                LLMConfig.status == "active",
                LLMConfig.purpose.in_(("builder", "all")),
            )
        )
```

第二段(default,~422 行 where 内):
```python
        res = await db.execute(
            select(LLMConfig)
            .where(
                LLMConfig.tenant_id == session.tenant_id,
                LLMConfig.is_default == True,  # noqa: E712
                LLMConfig.status == "active",
                LLMConfig.purpose.in_(("builder", "all")),
            )
        )
```

第三段(any active,~435 行 where 内):
```python
        res = await db.execute(
            select(LLMConfig)
            .where(
                LLMConfig.tenant_id == session.tenant_id,
                LLMConfig.status == "active",
                LLMConfig.purpose.in_(("builder", "all")),
            )
            .order_by(LLMConfig.created_at.desc(), LLMConfig.id.desc())
        )
```

无模型时三段都返回 None → 已有的 `raise RuntimeError("...平台管理...")` 触发。注释 `优先用 session.selected_llm_config_id;没指定则取平台级 default` 顺手改成 `...取本租户 default`。

- [ ] **Step 3: 跑测试确认变绿**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/test_aichat_no_cross_tenant_model.py -v`
Expected: PASS(1 passed)。

- [ ] **Step 4: Commit**

```bash
git add backend/app/ai_chat/agent.py
git commit -m "fix(ai-chat): Builder 模型解析按租户隔离，不再借别租户 default

_resolve_llm_config 三段查询全部加 tenant_id 过滤；本租户无模型时
按既有逻辑抛 RuntimeError 提示去平台管理添加。让已有红测试转绿。

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: 共享解析函数租户隔离(`routes/llm_configs.py`)

六个解析/默认管理函数都收了 `tenant_id` 参数但没用。给它们全加 `LLMConfig.tenant_id == tenant_id` 过滤。调用点签名不变(早已传 `ctx.tenant_id`)。这一处一改,Coding(`list_llm_configs_for_purpose`)、`/options`、`conversations.py`、harness 各路径的跨租户借用全部自动堵上。

**Files:**
- Modify: `backend/app/routes/llm_configs.py`(`get_llm_config_for_purpose` 546-591、`list_llm_configs_for_purpose` 599-615、`get_active_llm_config_by_id` 618-633、`get_active_llm_config_by_id_for_purpose` 636-653、`_clear_defaults` 513-521、`_assign_replacement_default` 524-543)
- Test: `backend/tests/test_llm_config_tenant_scope.py`(新建)

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_llm_config_tenant_scope.py`:
```python
"""共享 LLM 配置解析函数按租户隔离 —— 单测。

回归:这些函数早就收 tenant_id 参数但 WHERE 里没用,导致跨租户借模型。
"""
import pytest

from app.crypto import encrypt_password
from app.models import LLMConfig
from app.models.tenant import Tenant
from app.routes.llm_configs import (
    get_llm_config_for_purpose,
    list_llm_configs_for_purpose,
    get_active_llm_config_by_id,
    get_active_llm_config_by_id_for_purpose,
    _clear_defaults,
)


def _cfg(tenant_id, base, *, purpose="all", is_default=True):
    return LLMConfig(
        tenant_id=tenant_id, config_name="m", provider="dolphin",
        base_url=base, api_key_enc=encrypt_password("k"), model="gpt-5.5",
        purpose=purpose, is_default=is_default, status="active",
    )


async def _two_tenants_one_config(db):
    """租户 A 无配置;租户 B 有一条 default。返回 (a_id, b_id, b_config)。"""
    t_a = Tenant(tenant_name="A", tenant_code="ta")
    t_b = Tenant(tenant_name="B", tenant_code="tb")
    db.add_all([t_a, t_b])
    await db.flush()
    b_cfg = _cfg(t_b.id, "https://tenant-b/v1")
    db.add(b_cfg)
    await db.flush()
    return t_a.id, t_b.id, b_cfg


@pytest.mark.asyncio
async def test_get_for_purpose_does_not_leak(db_session):
    a_id, b_id, b_cfg = await _two_tenants_one_config(db_session)
    # 租户 A 没配 → 不该拿到租户 B 的
    assert await get_llm_config_for_purpose(db_session, a_id, "builder") is None
    # 租户 B 拿到自己的
    got = await get_llm_config_for_purpose(db_session, b_id, "builder")
    assert got is not None and got.id == b_cfg.id


@pytest.mark.asyncio
async def test_list_for_purpose_does_not_leak(db_session):
    a_id, b_id, b_cfg = await _two_tenants_one_config(db_session)
    assert await list_llm_configs_for_purpose(db_session, a_id, "builder") == []
    rows = await list_llm_configs_for_purpose(db_session, b_id, "builder")
    assert [r.id for r in rows] == [b_cfg.id]


@pytest.mark.asyncio
async def test_get_by_id_does_not_leak(db_session):
    a_id, b_id, b_cfg = await _two_tenants_one_config(db_session)
    # 租户 A 拿租户 B 的 config_id 应查不到
    assert await get_active_llm_config_by_id(db_session, a_id, b_cfg.id) is None
    assert await get_active_llm_config_by_id_for_purpose(db_session, a_id, b_cfg.id, "all") is None
    # 租户 B 自己能查到
    assert (await get_active_llm_config_by_id(db_session, b_id, b_cfg.id)).id == b_cfg.id


@pytest.mark.asyncio
async def test_clear_defaults_only_touches_own_tenant(db_session):
    a_id, b_id, b_cfg = await _two_tenants_one_config(db_session)
    a_cfg = _cfg(a_id, "https://tenant-a/v1")
    db_session.add(a_cfg)
    await db_session.flush()
    # 清租户 A 的默认,不该动租户 B 的
    await _clear_defaults(db_session, a_id, "all")
    await db_session.refresh(a_cfg)
    await db_session.refresh(b_cfg)
    assert a_cfg.is_default is False
    assert b_cfg.is_default is True, "清 A 的默认不该波及 B"
```

- [ ] **Step 2: 跑测试确认全红**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/test_llm_config_tenant_scope.py -v`
Expected: 4 个测试 FAIL(现在不过滤 tenant,A 会拿到 B 的;clear 会清掉 B)。

- [ ] **Step 3: 给六个函数加租户过滤**

`get_llm_config_for_purpose`:三处 `db.execute(select(LLMConfig).where(...))` 各自在 where 里加 `LLMConfig.tenant_id == tenant_id,`。第一处(purpose 精确)、第二处(`purpose == "all"`)、第三处(兜底 `status == "active"`)。第三处的 in-python 过滤循环保持不变。

`list_llm_configs_for_purpose`:
```python
    result = await db.execute(
        select(LLMConfig).where(
            LLMConfig.tenant_id == tenant_id,
            LLMConfig.status == "active",
        )
    )
```

`get_active_llm_config_by_id`:
```python
    result = await db.execute(
        select(LLMConfig).where(
            LLMConfig.id == config_id,
            LLMConfig.tenant_id == tenant_id,
            LLMConfig.status == "active",
        )
    )
```

`get_active_llm_config_by_id_for_purpose`:同上,在 `LLMConfig.id == config_id, LLMConfig.status == "active",` 之间加 `LLMConfig.tenant_id == tenant_id,`。

`_clear_defaults`:
```python
    await db.execute(
        update(LLMConfig)
        .where(
            LLMConfig.tenant_id == tenant_id,
            LLMConfig.is_default == True,
        )
        .values(is_default=False)
    )
```
并把 docstring 从 `清除平台所有默认配置;默认模型平台唯一。` 改为 `清除本租户所有默认配置;默认模型每租户唯一。`

`_assign_replacement_default`:在 `select(LLMConfig).where(` 的 `LLMConfig.purpose == purpose,` 前加 `LLMConfig.tenant_id == tenant_id,`。

- [ ] **Step 4: 跑测试确认全绿**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/test_llm_config_tenant_scope.py -v`
Expected: 4 passed。

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/llm_configs.py backend/tests/test_llm_config_tenant_scope.py
git commit -m "fix(llm-config): 共享解析函数按租户隔离

get_llm_config_for_purpose / list_llm_configs_for_purpose /
get_active_llm_config_by_id(_for_purpose) / _clear_defaults /
_assign_replacement_default 全部加 tenant_id 过滤。一改堵上 Coding /
options / conversations / harness 各调用方的跨租户借用。
默认模型从'平台唯一'改为'每租户唯一'。

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: admin 端点租户作用域 + 增删改授权(`routes/llm_configs.py`)

admin 列表现在全表拉;增删改测只按 config_id 查、无归属校验(租户管理员能改别租户的配置)。加:① 授权 helper;② list 加 `tenant_id` query;③ create 加 `tenant_id` body 字段;④ 五个变更端点加归属校验。

**Files:**
- Modify: `backend/app/routes/llm_configs.py`(`LLMConfigCreate` 37-46、`list_llm_configs` 186-197、`create_llm_config` 265-292、`update_llm_config` 295-344、`delete_llm_config` 347-363、`test_llm_config` 366-457、`set_default_llm_config` 460-480、`update_llm_config_status` 483-508;新增 helper)
- Test: `backend/tests/test_llm_config_admin_authz.py`(新建)

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_llm_config_admin_authz.py`:
```python
"""admin LLM 配置端点:租户作用域 + 归属授权。

直接调用路由函数(Depends 只是普通参数),手构 AuthContext。
"""
import pytest
from fastapi import HTTPException

from app.crypto import encrypt_password
from app.deps import AuthContext
from app.models import LLMConfig, User
from app.models.tenant import Tenant
from app.routes.llm_configs import (
    LLMConfigCreate,
    list_llm_configs,
    create_llm_config,
    update_llm_config,
    LLMConfigUpdate,
)


def _cfg(tenant_id, base):
    return LLMConfig(
        tenant_id=tenant_id, config_name="m", provider="dolphin",
        base_url=base, api_key_enc=encrypt_password("k"), model="gpt-5.5",
        purpose="all", is_default=True, status="active",
    )


async def _setup(db):
    t_a = Tenant(tenant_name="A", tenant_code="ta")
    t_b = Tenant(tenant_name="B", tenant_code="tb")
    db.add_all([t_a, t_b])
    await db.flush()
    a_cfg, b_cfg = _cfg(t_a.id, "https://a/v1"), _cfg(t_b.id, "https://b/v1")
    db.add_all([a_cfg, b_cfg])
    await db.flush()
    return t_a, t_b, a_cfg, b_cfg


def _ctx(db, tenant_id, *, platform=False):
    user = User(username=f"u{tenant_id}{platform}", hashed_password="x", is_platform_admin=platform)
    db.add(user)
    return AuthContext(
        user=user,
        tenant_id=tenant_id,
        tenant_role="platform_admin" if platform else "tenant_admin",
        org_permissions={},
    )


@pytest.mark.asyncio
async def test_tenant_admin_list_sees_only_own(db_session):
    t_a, t_b, a_cfg, b_cfg = await _setup(db_session)
    ctx = _ctx(db_session, t_a.id)
    # 即使传别租户 tenant_id 也被忽略,强制本租户
    rows = await list_llm_configs(ctx, db_session, tenant_id=t_b.id)
    assert [r.id for r in rows] == [a_cfg.id]


@pytest.mark.asyncio
async def test_platform_admin_list_with_tenant_id(db_session):
    t_a, t_b, a_cfg, b_cfg = await _setup(db_session)
    ctx = _ctx(db_session, t_a.id, platform=True)
    rows = await list_llm_configs(ctx, db_session, tenant_id=t_b.id)
    assert [r.id for r in rows] == [b_cfg.id]


@pytest.mark.asyncio
async def test_tenant_admin_cannot_edit_other_tenant(db_session):
    t_a, t_b, a_cfg, b_cfg = await _setup(db_session)
    ctx = _ctx(db_session, t_a.id)
    with pytest.raises(HTTPException) as exc:
        await update_llm_config(b_cfg.id, LLMConfigUpdate(model="x"), ctx, db_session)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_platform_admin_create_lands_on_target_tenant(db_session):
    t_a, t_b, a_cfg, b_cfg = await _setup(db_session)
    ctx = _ctx(db_session, t_a.id, platform=True)
    req = LLMConfigCreate(
        config_name="new", provider="dolphin", base_url="https://new/v1",
        api_key="k", model="gpt-5.5", purpose="all", tenant_id=t_b.id,
    )
    created = await create_llm_config(req, ctx, db_session)
    row = (await db_session.get(LLMConfig, created.id))
    assert row.tenant_id == t_b.id


@pytest.mark.asyncio
async def test_tenant_admin_create_ignores_body_tenant_id(db_session):
    t_a, t_b, a_cfg, b_cfg = await _setup(db_session)
    ctx = _ctx(db_session, t_a.id)  # 非平台管理员
    req = LLMConfigCreate(
        config_name="new", provider="dolphin", base_url="https://new/v1",
        api_key="k", model="gpt-5.5", purpose="all", tenant_id=t_b.id,  # 想塞别租户
    )
    created = await create_llm_config(req, ctx, db_session)
    row = (await db_session.get(LLMConfig, created.id))
    assert row.tenant_id == t_a.id, "租户管理员创建必须落到自己租户"
```

- [ ] **Step 2: 跑测试确认全红**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/test_llm_config_admin_authz.py -v`
Expected: FAIL(`LLMConfigCreate` 没有 `tenant_id` 字段会直接构造报错 / list 不过滤 / update 不校验归属)。

- [ ] **Step 3: 加授权 helper + `tenant_id` 字段**

在 `LLMConfigCreate`(class 内)加一行:
```python
    tenant_id: Optional[int] = None  # 仅平台管理员可指定目标租户;租户管理员忽略
```

在 `# ── Helpers ──` 区(`_clear_defaults` 之前)加:
```python
def _is_platform_admin(ctx: AuthContext) -> bool:
    return ctx.tenant_role == "platform_admin" or ctx.user.is_platform_admin


async def _resolve_target_tenant_id(db: AsyncSession, ctx: AuthContext, requested: Optional[int]) -> int:
    """平台管理员用 requested(缺省回退 effective tenant);租户管理员强制自己租户。"""
    if _is_platform_admin(ctx):
        return requested if requested else await resolve_effective_tenant_id(db, ctx)
    return ctx.tenant_id


def _assert_tenant_access(ctx: AuthContext, tenant_id: int) -> None:
    """平台管理员可访问任意租户;否则只能访问自己租户(越权按 404,不泄漏存在性)。"""
    if _is_platform_admin(ctx):
        return
    if ctx.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="配置不存在")
```

- [ ] **Step 4: list 加 `tenant_id` query 作用域**

把 `list_llm_configs` 改为:
```python
@router.get("")
async def list_llm_configs(
    ctx: Annotated[AuthContext, Depends(require_tenant_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Optional[int] = Query(None),
):
    """列出某租户的 LLM 配置。平台管理员可用 ?tenant_id= 指定;租户管理员强制本租户。"""
    effective_tid = await _resolve_target_tenant_id(db, ctx, tenant_id)
    result = await db.execute(
        select(LLMConfig)
        .where(LLMConfig.tenant_id == effective_tid)
        .order_by(LLMConfig.is_default.desc(), LLMConfig.created_at.desc())
    )
    rows = result.scalars().all()
    return [LLMConfigResponse.from_db(r) for r in rows]
```

- [ ] **Step 5: create 落到目标租户**

把 `create_llm_config` 体内的租户解析改掉:
```python
    target_tid = await _resolve_target_tenant_id(db, ctx, req.tenant_id)
    if req.is_default:
        await _clear_defaults(db, target_tid, req.purpose)

    config = LLMConfig(
        tenant_id=target_tid,
        config_name=req.config_name,
        ...
    )
```
(把原来的 `tenant_id = await resolve_effective_tenant_id(db, ctx)` 那两行删掉,`LLMConfig(tenant_id=tenant_id, ...)` 改成 `tenant_id=target_tid`。)

- [ ] **Step 6: 五个变更端点加归属校验**

在 `update_llm_config` / `delete_llm_config` / `test_llm_config` / `set_default_llm_config` / `update_llm_config_status` 里,每个**取出 config 之后、动它之前**插一行:
```python
    _assert_tenant_access(ctx, config.tenant_id)
```
具体位置:都是 `config = result.scalar_one_or_none()` + `if not config: raise 404` 之后紧跟。

- [ ] **Step 7: 跑测试确认全绿**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/test_llm_config_admin_authz.py -v`
Expected: 5 passed。

- [ ] **Step 8: 跑解析 + authz 两个文件 + 已有 aichat 测试一起确认**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/test_llm_config_tenant_scope.py tests/test_llm_config_admin_authz.py tests/test_aichat_no_cross_tenant_model.py -v`
Expected: 全 passed。

- [ ] **Step 9: Commit**

```bash
git add backend/app/routes/llm_configs.py backend/tests/test_llm_config_admin_authz.py
git commit -m "feat(llm-config): admin 端点租户作用域 + 增删改归属授权

list 加 ?tenant_id=(平台管理员指定/租户管理员强制本租户);create 加
body.tenant_id(同上);update/delete/test/set-default/status 加
_assert_tenant_access 归属校验,越权 404。

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: admin-spa 前端租户选择器(`admin-spa/src/views/LlmConfigs.vue`)

平台管理 SPA 的模型配置页加租户下拉:选哪个租户就看/配哪个租户的模型。列表与创建都带上选中 `tenant_id`。

**Files:**
- Modify: `admin-spa/src/views/LlmConfigs.vue`(hero-actions 模板 15-27、state 244-254、`loadConfigs` 354-365、`saveConfig` payload、`onMounted` 517)
- 复用后端 `GET /auth/tenants`(平台管理员专属,返回 `{ id, tenant_name, tenant_code, ... }[]`)

- [ ] **Step 1: 加租户列表 state + 加载函数**

在 `const configs = ref<LlmConfig[]>([])` 附近(~244)加:
```ts
interface TenantOption { id: number; tenant_name: string; tenant_code: string }
const tenants = ref<TenantOption[]>([])
const selectedTenantId = ref<number | null>(null)
```
在 `loadPresets` 附近加:
```ts
async function loadTenants() {
  try {
    const list = await apiGet<TenantOption[]>('/auth/tenants')
    tenants.value = Array.isArray(list) ? list : []
    if (!selectedTenantId.value && tenants.value.length) {
      selectedTenantId.value = tenants.value[0].id
    }
  } catch {
    tenants.value = []
  }
}
```

- [ ] **Step 2: `loadConfigs` / `saveConfig` 带上租户**

`loadConfigs` 的请求行改为:
```ts
    const list = await apiGet<LlmConfig[]>('/llm-configs', { tenant_id: selectedTenantId.value ?? undefined })
```
`saveConfig` 里新增分支(create 时带 tenant_id;edit 不需要):
```ts
    if (!editingConfig.value) {
      delete payload.status
      ;(payload as any).tenant_id = selectedTenantId.value ?? undefined
    }
```
(把原来的 `if (!editingConfig.value) delete payload.status` 替换成上面这段。)

- [ ] **Step 3: 模板加选择器 + onMounted 加载**

在 `hero-actions` 里 `search-input` 之前插:
```vue
        <el-select
          v-model="selectedTenantId"
          class="tenant-select"
          placeholder="选择租户"
          filterable
          @change="loadConfigs"
        >
          <el-option
            v-for="t in tenants"
            :key="t.id"
            :label="`${t.tenant_name}（${t.tenant_code}）`"
            :value="t.id"
          />
        </el-select>
```
头部 badge 文案(~10 行)`默认：{{ defaultConfigLabel }}` 改为 `当前租户默认：{{ defaultConfigLabel }}`。
`onMounted`(517)改为先加载租户再加载配置:
```ts
onMounted(async () => {
  await Promise.all([loadPresets(), loadTenants()])
  await loadConfigs()
})
```

- [ ] **Step 4: preview 验证(admin-spa)**

启动/复用 admin-spa dev server(preview_start)。以平台管理员登录,打开「LLM 配置」页:
1. preview_snapshot 确认顶部出现租户选择器,默认选中第一个租户。
2. 切换到另一个租户 → preview_console_logs / preview_network 确认请求带 `?tenant_id=`,卡片列表随之变化(只显示该租户的配置)。
3. 新增一个模型,保存后停留在当前租户、列表出现新卡片;preview_network 确认 POST body 带 `tenant_id`。
4. preview_screenshot 留证。

构建自检:`cd admin-spa && npm run build`(若该 SPA 有独立 build);确认无类型/编译错误。

- [ ] **Step 5: Commit**

```bash
git add admin-spa/src/views/LlmConfigs.vue
git commit -m "feat(admin-spa): 模型配置页加租户选择器，平台管理员代配

顶部 el-select 选租户;列表与创建带 tenant_id;默认选第一个租户。
配合后端租户作用域,平台管理员可逐租户查看/配置模型。

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: 全量回归 + 重启验证

- [ ] **Step 1: 跑后端全量测试,对比已知预存失败**

Run: `cd backend && source .venv/bin/activate && python -m pytest -q 2>&1 | tail -20`
Expected: 本次新增的 3 个文件全绿;其余失败数 ≤ 改动前的已知预存失败(memory 记 ~6 个本地 SQLite 预存坏 + `test_spec_section_o1.py` collect 失败)。**逐条核对新出现的失败是否由本次改动引入**——若有,回到对应 Task 修。

- [ ] **Step 2: 重启 preview backend(reload=False 必须)**

杀掉并重启后端进程(否则改动不生效)。确认 import 无错、服务起得来。

- [ ] **Step 3: 无模型租户端到端冒烟(可选,需真会话)**

如有条件:用一个**没配模型**的租户发起一次 Builder 或 Coding 会话,确认返回"请到平台管理 → 模型配置添加"之类清晰报错,而非静默用别租户/兜底模型。

---

## Self-Review

**Spec 覆盖核对:**
- 解析层 6 函数加过滤 → Task 2 ✓;Builder 自带 `_resolve_llm_config` → Task 1 ✓(spec 第 1 层 + 第 3 层 Builder 部分)。
- 端点层 list query / create body / 增删改授权 → Task 3 ✓(spec 第 2 层)。
- 不兜底收口:Builder = Task 1(报错);Coding = Task 2 后预检自动触发(spec 已述,无需单独改);harness 辅助路径(help/voice/incremental)保留 env(平台 key 非租户泄漏,spec 明确不动) → 覆盖 ✓。
- admin-spa 选择器 + 复用 `/auth/tenants` + 文案 → Task 4 ✓(spec 第 4 层)。
- 不做 schema 变更 / 不迁移存量 4 条 → 无对应 Task,符合 spec"不做"✓。

**占位符扫描:** 无 TBD/TODO;每个代码步骤都给了完整代码。✓

**类型/命名一致性:** `_is_platform_admin` / `_resolve_target_tenant_id` / `_assert_tenant_access` 在 Task 3 定义并在同任务内使用;`LLMConfigCreate.tenant_id`、`selectedTenantId`、`loadTenants` 跨步骤命名一致。✓

**边界提醒:** Task 3 的 `_assert_tenant_access` 对 member 同租户也放行(同租户测试自己模型 OK);`test_llm_config` 端点仍用 `get_auth_context`(任意登录用户)+ 归属校验,不收紧依赖以免影响普通用户测试本租户模型。
