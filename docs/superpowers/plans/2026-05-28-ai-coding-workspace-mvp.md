# AI Coding 主工作台 MVP 实现计划（需求 → 预览闭环）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `/chat` 体系上新建「左对话 + 右 6 Tab」的 AI Coding 主工作台，做实需求 Tab（复用 SpecDesignPanel）和预览 Tab（新建 HTML 原型 iframe），跑通「说需求 → 改基线 → 生成原型 → 预览 → 点选改」闭环。

**Architecture:** 前端新建 `AICodingWorkspace.vue`（左栏复用现成 `SpecChatPanel`，右栏 `WorkspaceTabs` 6 Tab，需求 Tab 嵌 `SpecDesignPanel`，预览 Tab 新建 `PreviewTab`）。对话与需求基线复用现有 `spec-chat-stream` SSE + `spec-updated` 事件联动。后端新增 `app_prototypes` 表 + SSE 原型生成 endpoint（读需求基线 → LLM → 单文件 HTML → 存表）。

**Tech Stack:** 后端 FastAPI + SQLAlchemy(Mapped) + sse_starlette + pytest；前端 Vue3 + TS + Element Plus + fetch/ReadableStream SSE；LLM 走现有 `LLMClient`。

---

## 测试策略（重要 — 先读）

- **后端有 pytest 基础**：`backend/pytest.ini`（asyncio_mode=auto, testpaths=tests）+ `backend/conftest.py` 的 `db_session` fixture（in-memory sqlite，`Base.metadata.create_all` 自动建表，**无 alembic**）。后端 task 走 TDD：先写失败测试 → 实现 → 通过。运行：`cd backend && pytest tests/<file>::<test> -v`。
- **前端无单元测试框架**：`package.json` devDeps 只有 playwright，无 vitest/jest。**不为本切片引入新测试框架**（避免 unilateral restructure）。前端 task 写完组件后，用 dev server + chrome-devtools 手工验证；端到端验收集中在 Task 9 的 playwright E2E（跑 spec §9 验收链路）。
- **提交粒度**：每个 task 末尾 commit 一次。

---

## File Structure

**后端（新建/改）**
- Create `backend/app/models/app_prototype.py` — `AppPrototype` 表 model
- Modify `backend/app/models/__init__.py` — import 注册新 model
- Create `backend/app/routes/applications/prototype.py` — prompt 构造 + SSE 生成 generator + generate/get endpoint
- Modify `backend/app/routes/applications/__init__.py` — include prototype 子路由
- Create `backend/tests/test_prototype_api.py` — 后端测试

**前端（新建/改）**
- Create `frontend/src/api/prototype.ts` — 原型生成 SSE 客户端 + 读取
- Create `frontend/src/views/AICodingWorkspace.vue` — 主工作台容器（左右 splitter）
- Create `frontend/src/components/ai-coding/WorkspaceTabs.vue` — 6 Tab 容器（4 占位）
- Create `frontend/src/components/ai-coding/PreviewTab.vue` — 预览 Tab（iframe sandbox + 点选回填）
- Modify `frontend/src/router/index.ts` — 加 `/ai-coding/:appId?` 路由

**复用（不改内部）**：`components/v3/SpecDesignPanel.vue`（props `appId:number, apaasAppId?:string`）、`components/v3/SpecChatPanel.vue`（props `appId:number, activeChapter:string, chapterTitle?:string`；emit `spec-updated(section_type, section_key)`）、`components/BuilderFrame.vue`（props `breadcrumbs`，slot `#actions` + 默认）。

**E2E**：Create `frontend/e2e/ai-coding-workspace.spec.ts`（按现有 playwright 目录结构校准，见 Task 9）。

---

## Task 1: 新增 `AppPrototype` 表

**Files:**
- Read first: `backend/app/models/deploy_history.py`（对齐 Base import、`app_id`/`tenant_id` 列定义与表名风格）
- Create: `backend/app/models/app_prototype.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_prototype_api.py`

- [ ] **Step 1: 读现有表对齐 pattern**

Read `backend/app/models/deploy_history.py`。确认：`Base` 的 import 路径（应为 `from app.database import Base`）、`app_id`/`tenant_id` 列是否用 `ForeignKey` 还是裸 `Integer + index`、`created_at` 的 server_default 写法。下一步代码按它校准。

- [ ] **Step 2: 写失败测试**

Create `backend/tests/test_prototype_api.py`:

```python
import pytest
from app.models.app_prototype import AppPrototype


@pytest.mark.asyncio
async def test_app_prototype_insert_and_query(db_session):
    proto = AppPrototype(
        app_id=1,
        tenant_id=1,
        version=1,
        html_content="<html><body>hi</body></html>",
        source_spec_version=3,
        created_by=1,
    )
    db_session.add(proto)
    await db_session.commit()
    await db_session.refresh(proto)

    assert proto.id is not None
    assert proto.app_id == 1
    assert proto.version == 1
    assert "<body>" in proto.html_content
```

- [ ] **Step 3: 运行测试，确认失败**

Run: `cd backend && pytest tests/test_prototype_api.py::test_app_prototype_insert_and_query -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models.app_prototype'`

- [ ] **Step 4: 写 model**

Create `backend/app/models/app_prototype.py`（列定义按 Step 1 校准，下面是基线）:

```python
from datetime import datetime
from sqlalchemy import Integer, Text, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class AppPrototype(Base):
    """AI Coding 主工作台生成的 HTML 原型快照（app 中心、可版本化）。"""
    __tablename__ = "app_prototypes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    app_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    tenant_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    html_content: Mapped[str] = mapped_column(Text, nullable=False)
    source_spec_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

- [ ] **Step 5: 注册 model**

Modify `backend/app/models/__init__.py` — 在其它 model import 旁加一行（让 `Base.metadata` 注册映射，conftest create_all 才会建表）:

```python
from app.models.app_prototype import AppPrototype  # noqa: F401
```

- [ ] **Step 6: 运行测试，确认通过**

Run: `cd backend && pytest tests/test_prototype_api.py::test_app_prototype_insert_and_query -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/app_prototype.py backend/app/models/__init__.py backend/tests/test_prototype_api.py
git commit -m "feat(ai-coding): app_prototypes 表 — HTML 原型快照存储"
```

---

## Task 2: 原型生成 prompt 构造（读需求基线）

**Files:**
- Read first: `backend/app/mcp_spec_sections.py`（确认 `read_spec_section` 签名与返回结构）、`backend/app/routes/applications/section_content.py`（确认有无一次性拿全资源的函数）
- Create: `backend/app/routes/applications/prototype.py`
- Test: `backend/tests/test_prototype_api.py`（追加）

- [ ] **Step 1: 读现有读基线函数**

Read `backend/app/mcp_spec_sections.py:118` 附近 `read_spec_section(db, app_id, section_type, section_key) -> dict`，确认返回 `{ok, exists, section:{spec_json,...}}`。确认 section_type/section_key 取值（参考 `spec_chat.py` 的章节映射，如 `models`/`dicts`/`roles`/`menus`）。

- [ ] **Step 2: 写失败测试**

追加到 `backend/tests/test_prototype_api.py`:

```python
@pytest.mark.asyncio
async def test_build_prototype_prompt_includes_models(db_session, monkeypatch):
    from app.routes.applications import prototype

    async def fake_read(db, app_id, section_type, section_key):
        if section_key == "models":
            return {"ok": True, "exists": True,
                    "section": {"spec_json": {"models": [{"name": "供应商", "fields": [{"name": "风险等级"}]}]}}}
        return {"ok": True, "exists": False}

    monkeypatch.setattr(prototype, "read_spec_section", fake_read)
    prompt = await prototype.build_prototype_prompt(db_session, app_id=1)

    assert "供应商" in prompt
    assert "风险等级" in prompt
    assert "data-block" in prompt  # prompt 必须要求给可点选区块加 data-block
    assert "iframe" in prompt.lower()  # 必须要求可独立预览
```

- [ ] **Step 3: 运行测试，确认失败**

Run: `cd backend && pytest tests/test_prototype_api.py::test_build_prototype_prompt_includes_models -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'build_prototype_prompt'`

- [ ] **Step 4: 实现 prompt 构造**

Create `backend/app/routes/applications/prototype.py`:

```python
"""AI Coding 主工作台 — HTML 原型生成。读需求基线 → LLM → 单文件 HTML → 存 app_prototypes。"""
from __future__ import annotations
import json
from app.mcp_spec_sections import read_spec_section

# 需求基线里要喂给原型的 section（section_type 统一用 "spec"，key 按现有约定校准）
_BASELINE_KEYS = ["models", "dicts", "roles", "menus"]

_PROMPT_HEADER = """你是 AI Coding 的 UI 原型设计师。基于下面的应用需求基线，生成一个**单文件 HTML 原型**，供业务用户确认 UI。

硬性要求：
1. 输出**完整单文件 HTML**（<!DOCTYPE html> 开头），不依赖任何本地资源。
2. 只用 CDN 引 Element Plus + ECharts；其余内联 <style>/<script>。
3. 内置**mock 数据**，不调用任何真实接口、不写任何 token/key/真实地址。
4. 企业级后台风格，清晰稳重，信息密度适中。
5. 每个可点选的功能区块（卡片/表格行/图表/按钮）加属性 `data-block="<简短中文标签>"`，供点选交互使用。
6. HTML 必须能在 iframe 中独立预览。

应用需求基线：
"""


async def build_prototype_prompt(db, app_id: int) -> str:
    parts: list[str] = [_PROMPT_HEADER]
    for key in _BASELINE_KEYS:
        res = await read_spec_section(db, app_id, "spec", key)
        if res.get("ok") and res.get("exists"):
            spec_json = res["section"].get("spec_json", {})
            parts.append(f"\n## {key}\n{json.dumps(spec_json, ensure_ascii=False, indent=2)}")
    parts.append("\n\n现在输出完整单文件 HTML（只输出 HTML，不要解释）：")
    return "".join(parts)
```

> 注：`section_type`/`section_key` 的确切取值按 Step 1 的现有约定校准。若现有用的是 `section_type=key`（如直接 `read_spec_section(db, app_id, "models", "models")`），同步调整 `_BASELINE_KEYS` 与调用。

- [ ] **Step 5: 运行测试，确认通过**

Run: `cd backend && pytest tests/test_prototype_api.py::test_build_prototype_prompt_includes_models -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/applications/prototype.py backend/tests/test_prototype_api.py
git commit -m "feat(ai-coding): 原型生成 prompt 构造 — 读需求基线拼 prompt"
```

---

## Task 3: SSE 原型生成 endpoint

**Files:**
- Read first: `backend/app/routes/applications/spec_chat.py:537-612,1000-1014`（SSE generator + `_sse` 辅助 + LLM cfg 加载 + 权限校验 pattern）
- Modify: `backend/app/routes/applications/prototype.py`（加 generator + endpoint + APIRouter）
- Modify: `backend/app/routes/applications/__init__.py`（include 子路由）
- Test: `backend/tests/test_prototype_api.py`（追加）

- [ ] **Step 1: 读 SSE pattern**

Read `spec_chat.py` 的 `_sse(event, data)` 辅助函数、`_spec_chat_event_stream` generator（权限校验 + `_resolve_builder_llm_cfg(db, tenant_id, conversation_id)` + `llm_cfg.chat_completion_stream(...)`）、以及路由怎么返 `EventSourceResponse(...)`。原型 endpoint 照抄这套结构。

- [ ] **Step 2: 写失败测试（mock LLM）**

追加到 `backend/tests/test_prototype_api.py`:

```python
@pytest.mark.asyncio
async def test_generate_prototype_persists_and_emits_ready(db_session, monkeypatch):
    from app.routes.applications import prototype as proto_mod
    from app.models.app_prototype import AppPrototype
    from sqlalchemy import select

    monkeypatch.setattr(proto_mod, "build_prototype_prompt",
                        lambda db, app_id: _async_return("PROMPT"))

    async def fake_stream(prompt, db, tenant_id, app_id):
        for chunk in ["<!DOCTYPE html><body>", "<div data-block='卡片'>x</div>", "</body>"]:
            yield chunk

    monkeypatch.setattr(proto_mod, "_llm_html_stream", fake_stream)

    events = []
    async for ev in proto_mod._generate_event_stream(db_session, app_id=1, tenant_id=1, user_id=1):
        events.append(ev)

    # 末尾有 prototype_ready 事件 + DB 落库
    assert any("prototype_ready" in e for e in events)
    rows = (await db_session.execute(select(AppPrototype).where(AppPrototype.app_id == 1))).scalars().all()
    assert len(rows) == 1
    assert "data-block" in rows[0].html_content


def _async_return(v):
    async def _f(*a, **k):
        return v
    return _f()
```

> 测试直接驱动 generator（不走 HTTP），避免 SSE 传输层复杂度。鉴权/HTTP 层在 Step 5 加 endpoint 后由现有 `_load_app_and_check_*` 保证（与 spec_chat 一致）。

- [ ] **Step 3: 运行测试，确认失败**

Run: `cd backend && pytest tests/test_prototype_api.py::test_generate_prototype_persists_and_emits_ready -v`
Expected: FAIL — `AttributeError: ... '_generate_event_stream'`

- [ ] **Step 4: 实现 generator + LLM 流 + 落库**

追加到 `backend/app/routes/applications/prototype.py`（`_sse`、LLM cfg 解析按 Step 1 从 spec_chat 校准 import）:

```python
from app.routes.applications.spec_chat import _sse, _resolve_builder_llm_cfg  # 校准实际可导出名
from app.models.app_prototype import AppPrototype
from sqlalchemy import select, func as sqlfunc


async def _llm_html_stream(prompt: str, db, tenant_id: int, app_id: int):
    """调现有 LLMClient 流式产出 HTML chunk。按 spec_chat 的 cfg 解析校准。"""
    llm_cfg = await _resolve_builder_llm_cfg(db, tenant_id, None)
    async for token in llm_cfg.chat_completion_stream(
        messages=[{"role": "user", "content": prompt}]
    ):
        yield token


async def _next_version(db, app_id: int) -> int:
    cur = (await db.execute(
        select(sqlfunc.max(AppPrototype.version)).where(AppPrototype.app_id == app_id)
    )).scalar()
    return (cur or 0) + 1


async def _generate_event_stream(db, app_id: int, tenant_id: int, user_id: int):
    yield _sse("started", {"app_id": app_id})
    prompt = await build_prototype_prompt(db, app_id)
    html_parts: list[str] = []
    try:
        async for chunk in _llm_html_stream(prompt, db, tenant_id, app_id):
            html_parts.append(chunk)
            yield _sse("progress", {"chars": sum(len(p) for p in html_parts)})
    except Exception as exc:  # LLM 失败 → error 事件，不落半成品
        yield _sse("error", {"message": f"原型生成失败：{exc}"})
        return

    html = "".join(html_parts).strip()
    if "<body" not in html.lower() and "<html" not in html.lower():
        yield _sse("error", {"message": "生成内容不是合法 HTML"})
        return

    proto = AppPrototype(
        app_id=app_id, tenant_id=tenant_id, version=await _next_version(db, app_id),
        html_content=html, created_by=user_id,
    )
    db.add(proto)
    await db.commit()
    await db.refresh(proto)
    yield _sse("prototype_ready", {"prototype_id": proto.id, "version": proto.version})
```

- [ ] **Step 5: 加 endpoint + router**

继续在 `prototype.py` 顶部建 router、底部加 endpoint（prefix 校准：最终 URL 要是 `/api/applications/{app_id}/prototype/generate`）:

```python
from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse
from app.auth import get_auth_context, AuthContext  # 校准现有 auth 依赖名
from app.database import get_db  # 校准现有 db 依赖名

router = APIRouter()


@router.post("/{app_id}/prototype/generate")
async def generate_prototype(app_id: int, ctx: AuthContext = Depends(get_auth_context), db=Depends(get_db)):
    # 权限校验复用现有 helper（与 spec_chat 一致），校准函数名
    return EventSourceResponse(
        _generate_event_stream(db, app_id=app_id, tenant_id=ctx.tenant_id, user_id=ctx.user_id)
    )
```

Modify `backend/app/routes/applications/__init__.py` — include 子路由（参照该文件现有 `router = APIRouter(prefix="/applications")` + 其它 `router.include_router(...)` 写法）:

```python
from app.routes.applications.prototype import router as prototype_router
router.include_router(prototype_router)
```

- [ ] **Step 6: 运行测试，确认通过**

Run: `cd backend && pytest tests/test_prototype_api.py -v`
Expected: 全部 PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/routes/applications/prototype.py backend/app/routes/applications/__init__.py backend/tests/test_prototype_api.py
git commit -m "feat(ai-coding): SSE 原型生成 endpoint — LLM 流式产 HTML 落库"
```

---

## Task 4: 读取原型 endpoint

**Files:**
- Modify: `backend/app/routes/applications/prototype.py`
- Test: `backend/tests/test_prototype_api.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
@pytest.mark.asyncio
async def test_get_prototype_returns_html(db_session):
    from app.routes.applications import prototype as proto_mod
    from app.models.app_prototype import AppPrototype

    proto = AppPrototype(app_id=1, tenant_id=1, version=1, html_content="<html><body>ok</body></html>")
    db_session.add(proto)
    await db_session.commit()
    await db_session.refresh(proto)

    res = await proto_mod.get_prototype_record(db_session, app_id=1, prototype_id=proto.id, tenant_id=1)
    assert res["html_content"] == "<html><body>ok</body></html>"
    assert res["version"] == 1
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && pytest tests/test_prototype_api.py::test_get_prototype_returns_html -v`
Expected: FAIL — no attribute `get_prototype_record`

- [ ] **Step 3: 实现读取函数 + endpoint**

追加到 `prototype.py`:

```python
async def get_prototype_record(db, app_id: int, prototype_id: int, tenant_id: int) -> dict:
    row = (await db.execute(
        select(AppPrototype).where(
            AppPrototype.id == prototype_id,
            AppPrototype.app_id == app_id,
            AppPrototype.tenant_id == tenant_id,
        )
    )).scalar_one_or_none()
    if row is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="原型不存在")
    return {"id": row.id, "version": row.version, "html_content": row.html_content}


@router.get("/{app_id}/prototype/{prototype_id}")
async def get_prototype(app_id: int, prototype_id: int,
                        ctx: AuthContext = Depends(get_auth_context), db=Depends(get_db)):
    return await get_prototype_record(db, app_id, prototype_id, ctx.tenant_id)
```

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && pytest tests/test_prototype_api.py -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/applications/prototype.py backend/tests/test_prototype_api.py
git commit -m "feat(ai-coding): 读取原型 endpoint GET /prototype/{id}"
```

---

## Task 5: 前端路由 + 工作台骨架

**Files:**
- Read first: `frontend/src/router/index.ts`（lazy import + `:param?` 风格）、`frontend/src/views/ChatPage.vue`（BuilderFrame/WorkbenchShell 用法、`builderCurrentAppId` 来源）、`frontend/src/components/v3/SpecDesignPanel.vue` 顶部 splitter 参考 `OnlineCodingWorkspacePage.vue:115-124`
- Create: `frontend/src/views/AICodingWorkspace.vue`
- Modify: `frontend/src/router/index.ts`

- [ ] **Step 1: 加路由**

Modify `frontend/src/router/index.ts` — 仿现有 lazy 风格加一条:

```typescript
{
  path: '/ai-coding/:appId?',
  name: 'AICoding',
  component: () => import('@/views/AICodingWorkspace.vue'),
},
```

- [ ] **Step 2: 写工作台骨架（左右 splitter + 占位）**

Create `frontend/src/views/AICodingWorkspace.vue`（左栏先放占位，Task 7 换 SpecChatPanel；splitter 参照 OnlineCodingWorkspacePage 的 `startPreviewResize`）:

```vue
<template>
  <BuilderFrame :breadcrumbs="[{ label: 'AI Coding' }]">
    <template #actions>
      <span class="aicoding-app-chip" v-if="appId">应用 #{{ appId }}</span>
    </template>
    <div v-if="!appId" class="aicoding-empty">
      请带应用进入：<code>/ai-coding/&lt;appId&gt;</code>
    </div>
    <div v-else class="aicoding-shell">
      <section class="aicoding-chat" :style="{ flexBasis: chatWidth + 'px' }">
        <div class="aicoding-chat-placeholder">左对话（Task 7 接 SpecChatPanel）</div>
        <div class="aicoding-resizer" @mousedown="startResize"></div>
      </section>
      <section class="aicoding-work">
        <WorkspaceTabs :app-id="appId" />
      </section>
    </div>
  </BuilderFrame>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'
import BuilderFrame from '@/components/BuilderFrame.vue'
import WorkspaceTabs from '@/components/ai-coding/WorkspaceTabs.vue'

const route = useRoute()
const appId = computed<number | null>(() => {
  const raw = route.params.appId
  const n = Number(Array.isArray(raw) ? raw[0] : raw)
  return Number.isFinite(n) && n > 0 ? n : null
})

const activeChapter = ref('models')
const chatWidth = ref(420)
function startResize(e: MouseEvent) {
  const startX = e.clientX
  const startW = chatWidth.value
  const onMove = (ev: MouseEvent) => { chatWidth.value = Math.max(320, Math.min(720, startW + ev.clientX - startX)) }
  const onUp = () => { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp) }
  window.addEventListener('mousemove', onMove); window.addEventListener('mouseup', onUp)
}
</script>

<style scoped>
.aicoding-shell { display: flex; height: 100%; min-height: 0; }
.aicoding-chat { position: relative; flex: 0 0 auto; border-right: 1px solid var(--line); display: flex; flex-direction: column; min-width: 0; }
.aicoding-work { flex: 1 1 auto; min-width: 0; overflow: auto; }
.aicoding-resizer { position: absolute; top: 0; right: -3px; width: 6px; height: 100%; cursor: col-resize; }
.aicoding-empty { padding: 40px; color: var(--text-3); }
.aicoding-app-chip { font-size: 12px; color: var(--text-3); }
</style>
```

- [ ] **Step 3: 验证（dev server）**

Run dev server，浏览器开 `/ai-coding/1`。预期：BuilderFrame 外壳 + 左占位 + 右 6 Tab 容器（Task 6 后），可拖拽分隔。开 `/ai-coding`（无 appId）显空态提示。无 console 报错。
（验证用 preview_* 工具或 chrome-devtools；本 task 右侧 WorkspaceTabs 依赖 Task 6，可先临时注释 import 验证骨架，或与 Task 6 连续做。）

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/AICodingWorkspace.vue frontend/src/router/index.ts
git commit -m "feat(ai-coding): 工作台骨架 + /ai-coding/:appId 路由"
```

---

## Task 6: WorkspaceTabs 6 Tab 容器

**Files:**
- Create: `frontend/src/components/ai-coding/WorkspaceTabs.vue`

- [ ] **Step 1: 写 6 Tab 容器（需求/预览 真，其余 4 占位）**

Create `frontend/src/components/ai-coding/WorkspaceTabs.vue`:

```vue
<template>
  <div class="wt-root">
    <nav class="wt-tabs">
      <button v-for="t in tabs" :key="t.key" class="wt-tab"
        :class="{ active: active === t.key, disabled: t.disabled }"
        :disabled="t.disabled" @click="active = t.key">
        {{ t.label }}<span v-if="t.disabled" class="wt-soon">敬请期待</span>
      </button>
    </nav>
    <div class="wt-body">
      <SpecDesignPanel v-if="active === 'requirement'" :app-id="appId" />
      <PreviewTab v-else-if="active === 'preview'" :app-id="appId" @select-block="$emit('select-block', $event)" />
      <div v-else class="wt-placeholder">「{{ activeLabel }}」敬请期待</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import SpecDesignPanel from '@/components/v3/SpecDesignPanel.vue'
import PreviewTab from '@/components/ai-coding/PreviewTab.vue'

defineProps<{ appId: number }>()
defineEmits<{ (e: 'select-block', label: string): void }>()

const tabs = [
  { key: 'requirement', label: '需求', disabled: false },
  { key: 'preview', label: '预览', disabled: false },
  { key: 'progress', label: '进度', disabled: true },
  { key: 'output', label: '产出', disabled: true },
  { key: 'tools', label: '工具', disabled: true },
  { key: 'observe', label: '可观测', disabled: true },
]
const active = ref('requirement')
const activeLabel = computed(() => tabs.find(t => t.key === active.value)?.label ?? '')
</script>

<style scoped>
.wt-root { display: flex; flex-direction: column; height: 100%; }
.wt-tabs { display: flex; gap: 4px; padding: 8px; border-bottom: 1px solid var(--line); }
.wt-tab { border: 0; background: transparent; padding: 8px 12px; border-radius: 8px; color: var(--text-3); cursor: pointer; font-size: 13px; }
.wt-tab.active { background: var(--brand-soft); color: var(--brand); font-weight: 600; }
.wt-tab.disabled { color: var(--text-4); cursor: not-allowed; }
.wt-soon { font-size: 10px; margin-left: 4px; opacity: .7; }
.wt-body { flex: 1 1 auto; min-height: 0; overflow: auto; }
.wt-placeholder { padding: 48px; text-align: center; color: var(--text-4); }
</style>
```

- [ ] **Step 2: 验证（dev server）**

浏览器 `/ai-coding/1`：需求 Tab 默认显 SpecDesignPanel（11 章）；点预览 Tab 显 PreviewTab（Task 8 前可能空）；点后 4 个 Tab 显「敬请期待」不报错。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ai-coding/WorkspaceTabs.vue
git commit -m "feat(ai-coding): WorkspaceTabs 6 Tab 容器（需求/预览真，4 占位）"
```

---

## Task 7: 左对话接线（复用 SpecChatPanel + 联动刷新）

**Files:**
- Read first: `frontend/src/components/v3/SpecChatPanel.vue`（确认 props `appId/activeChapter/chapterTitle`、emit `spec-updated`）、`SpecDesignPanel.vue`（确认是否暴露「当前章节」或刷新方法；若无对外刷新，靠 `:key` 重挂）
- Modify: `frontend/src/views/AICodingWorkspace.vue`

- [ ] **Step 1: 左栏换成 SpecChatPanel + 接 spec-updated**

Modify `AICodingWorkspace.vue` — 左栏占位替换为真实组件，并用 `spec-updated` 触发需求 Tab 刷新（无对外刷新 API 时用 `refreshKey` 给 WorkspaceTabs 重挂）:

```vue
<!-- template 左栏 -->
<section class="aicoding-chat" :style="{ flexBasis: chatWidth + 'px' }">
  <SpecChatPanel
    :app-id="appId"
    :active-chapter="activeChapter"
    @spec-updated="onSpecUpdated"
  />
  <div class="aicoding-resizer" @mousedown="startResize"></div>
</section>
<!-- template 右栏加 key -->
<WorkspaceTabs :key="refreshKey" :app-id="appId" />
```

```typescript
// script setup 追加
import SpecChatPanel from '@/components/v3/SpecChatPanel.vue'
const refreshKey = ref(0)
function onSpecUpdated(_sectionType: string, _sectionKey: string) {
  refreshKey.value++   // 需求基线变了 → 重挂 WorkspaceTabs 让 SpecDesignPanel 重拉
}
```

> 若 SpecDesignPanel 暴露了 `reload()`/`refresh()` 方法（Step 1 确认），优先调它而非整体重挂，体验更平滑。

- [ ] **Step 2: 验证闭环前半段（dev server + chrome-devtools）**

浏览器 `/ai-coding/1`：左对话输入「给供应商加个风险等级字段」→ 观察 SSE 回复 → 需求 Tab（SpecDesignPanel）数据模型章节出现该字段。确认 `spec-updated` 触发刷新。截图存证。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/AICodingWorkspace.vue
git commit -m "feat(ai-coding): 左对话复用 SpecChatPanel + spec-updated 联动刷新需求 Tab"
```

---

## Task 8: 预览 Tab（SSE 生成 + iframe sandbox + 点选回填）

**Files:**
- Read first: `frontend/src/api/aiChat.ts:109-170`（fetch+ReadableStream SSE 解析 pattern）
- Create: `frontend/src/api/prototype.ts`
- Create: `frontend/src/components/ai-coding/PreviewTab.vue`
- Modify: `frontend/src/views/AICodingWorkspace.vue`（接 select-block 回填）

- [ ] **Step 1: 写原型 SSE 客户端**

Create `frontend/src/api/prototype.ts`（SSE 解析仿 `api/aiChat.ts`，token 取现有方式）:

```typescript
const API_PREFIX = (import.meta as any).env?.VITE_API_PREFIX ?? '/api'

export async function generatePrototype(
  appId: number,
  onEvent: (event: string, data: any) => void,
  signal?: AbortSignal,
): Promise<void> {
  const token = localStorage.getItem('token') ?? ''
  const resp = await fetch(`${API_PREFIX}/applications/${appId}/prototype/generate`, {
    method: 'POST',
    headers: { 'Accept': 'text/event-stream', Authorization: `Bearer ${token}` },
    signal,
  })
  if (!resp.body) throw new Error('无响应流')
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const frames = buffer.split(/\n\n/)
    buffer = frames.pop() ?? ''
    for (const frame of frames) {
      let ev = 'message', data = ''
      for (const line of frame.split(/\r?\n/)) {
        if (line.startsWith('event:')) ev = line.slice(6).trim()
        else if (line.startsWith('data:')) data += line.slice(5).trim()
      }
      if (data) { try { onEvent(ev, JSON.parse(data)) } catch { onEvent(ev, data) } }
    }
  }
}

export async function fetchPrototypeHtml(appId: number, prototypeId: number): Promise<string> {
  const token = localStorage.getItem('token') ?? ''
  const resp = await fetch(`${API_PREFIX}/applications/${appId}/prototype/${prototypeId}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  const json = await resp.json()
  return json.html_content as string
}
```

> `token` 读取方式按现有 `api/aiChat.ts` 校准（可能是统一 axios 实例或 auth store）。

- [ ] **Step 2: 写 PreviewTab（iframe sandbox + 点选注入）**

Create `frontend/src/components/ai-coding/PreviewTab.vue`:

```vue
<template>
  <div class="pt-root">
    <header class="pt-bar">
      <button class="pt-gen" :disabled="loading" @click="onGenerate">
        {{ loading ? `生成中… ${chars}` : '生成原型' }}
      </button>
      <span v-if="error" class="pt-err">{{ error }}</span>
    </header>
    <div class="pt-stage">
      <iframe v-if="html" ref="frameRef" class="pt-frame" sandbox="allow-scripts" :srcdoc="injectedHtml"></iframe>
      <div v-else class="pt-empty">点「生成原型」基于当前需求基线生成 HTML 预览</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { generatePrototype, fetchPrototypeHtml } from '@/api/prototype'

const props = defineProps<{ appId: number }>()
const emit = defineEmits<{ (e: 'select-block', label: string): void }>()

const loading = ref(false)
const chars = ref(0)
const error = ref('')
const html = ref('')
let abort: AbortController | null = null

// 注入点选脚本：给 data-block 元素加点击 → postMessage 到父窗
const SELECT_SCRIPT = `<script>
document.addEventListener('click', function(e){
  var el = e.target.closest('[data-block]'); if(!el) return;
  e.preventDefault();
  parent.postMessage({type:'ai-coding:select', label: el.getAttribute('data-block')}, '*');
});
<\/script>`
const injectedHtml = computed(() =>
  html.value.includes('</body>') ? html.value.replace('</body>', SELECT_SCRIPT + '</body>') : html.value + SELECT_SCRIPT)

async function onGenerate() {
  loading.value = true; error.value = ''; chars.value = 0
  abort = new AbortController()
  try {
    await generatePrototype(props.appId, async (ev, data) => {
      if (ev === 'progress') chars.value = data.chars ?? 0
      else if (ev === 'error') error.value = data.message ?? '生成失败'
      else if (ev === 'prototype_ready') html.value = await fetchPrototypeHtml(props.appId, data.prototype_id)
    }, abort.signal)
  } catch (e: any) { error.value = e?.message ?? '生成失败' }
  finally { loading.value = false }
}

function onMessage(e: MessageEvent) {
  if (e.data?.type === 'ai-coding:select') emit('select-block', e.data.label)
}
onMounted(() => window.addEventListener('message', onMessage))
onUnmounted(() => { window.removeEventListener('message', onMessage); abort?.abort() })
</script>

<style scoped>
.pt-root { display: flex; flex-direction: column; height: 100%; }
.pt-bar { display: flex; align-items: center; gap: 12px; padding: 10px; border-bottom: 1px solid var(--line); }
.pt-gen { background: var(--brand); color: #fff; border: 0; border-radius: 8px; padding: 8px 16px; cursor: pointer; }
.pt-gen:disabled { opacity: .6; cursor: not-allowed; }
.pt-err { color: var(--err); font-size: 12px; }
.pt-stage { flex: 1 1 auto; min-height: 0; background: var(--surface-3); padding: 12px; }
.pt-frame { width: 100%; height: 100%; border: 1px solid var(--line); border-radius: 8px; background: #fff; }
.pt-empty { display: grid; place-items: center; height: 100%; color: var(--text-4); }
</style>
```

- [ ] **Step 3: 接 select-block 回填对话框**

Modify `AICodingWorkspace.vue` — WorkspaceTabs 已透传 `select-block`，在工作台接住并回填到 SpecChatPanel 的输入。SpecChatPanel 若无 `prefill` prop（Step 1 of Task 7 确认），用一个 ref + watch 写入其输入框；最简实现：把选中 label 拼成提示存 `pendingSelect`，传给 SpecChatPanel 或用 toast 引导:

```typescript
// AICodingWorkspace.vue script
const pendingSelect = ref('')
// WorkspaceTabs 加 @select-block="onSelectBlock"
function onSelectBlock(label: string) {
  pendingSelect.value = `我选中了：${label}，`
  // 若 SpecChatPanel 暴露 prefill(text) 方法/prop 则调用；否则 ElMessage 提示用户已选中
}
```

> 若 SpecChatPanel 不支持外部预填输入，本切片降级为：选中后 `ElMessage.success('已选中：' + label + '，在左侧对话里说怎么改')`。完整预填留切片 ②（需 SpecChatPanel 加 `prefill` prop）。

- [ ] **Step 4: 验证完整闭环（chrome-devtools / preview）**

`/ai-coding/1` → 预览 Tab → 生成原型 → iframe 显示带 mock 数据的 HTML → 点某个 `data-block` 区块 → 父窗收到 select 事件（回填或 toast）。截图存证。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/prototype.ts frontend/src/components/ai-coding/PreviewTab.vue frontend/src/views/AICodingWorkspace.vue
git commit -m "feat(ai-coding): 预览 Tab — SSE 生成 + iframe sandbox + 点选回填"
```

---

## Task 9: E2E 验收（playwright）

**Files:**
- Read first: 现有 playwright 配置（`frontend/playwright.config.*` 或 `frontend/e2e/`）确认目录与运行方式
- Create: `frontend/e2e/ai-coding-workspace.spec.ts`

- [ ] **Step 1: 确认 playwright 跑法**

Read playwright 配置，确认 baseURL、登录态注入方式（既有 E2E 怎么处理 auth token）、运行命令（如 `npx playwright test`）。

- [ ] **Step 2: 写 E2E（spec §9 验收链路）**

Create `frontend/e2e/ai-coding-workspace.spec.ts`（选择器按实际 DOM 校准）:

```typescript
import { test, expect } from '@playwright/test'

test('AI Coding 主工作台：需求→预览闭环', async ({ page }) => {
  await page.goto('/ai-coding/1')                       // 1 = 已存在测试应用
  await expect(page.locator('.wt-tab', { hasText: '需求' })).toBeVisible()

  // 后 4 Tab 占位不报错
  await page.locator('.wt-tab', { hasText: '进度' }).click({ force: true })
  await expect(page.locator('.wt-placeholder')).toContainText('敬请期待')

  // 预览 Tab 生成原型
  await page.locator('.wt-tab', { hasText: '预览' }).click()
  await page.locator('.pt-gen').click()
  await expect(page.locator('.pt-frame')).toBeVisible({ timeout: 60_000 })
})
```

- [ ] **Step 3: 跑 E2E**

Run: `cd frontend && npx playwright test e2e/ai-coding-workspace.spec.ts`
Expected: PASS（需后端运行 + 测试应用 id=1 存在 + 登录态）。若环境不具备，改用 chrome-devtools 手工实测 spec §9 全链路并截图存证。

- [ ] **Step 4: Commit**

```bash
git add frontend/e2e/ai-coding-workspace.spec.ts
git commit -m "test(ai-coding): E2E 验收 — 需求→预览闭环"
```

---

## 验收对照（spec §9）

| spec §9 验收点 | 对应 Task |
|---|---|
| 进入 /ai-coding/{appId} 见左对话+右 6 Tab | Task 5,6 |
| 对话加字段 → 需求 Tab 实时更新 | Task 7 |
| 预览 Tab 生成原型 → iframe 显示 | Task 3,8 |
| 点原型卡片 → 回填对话框 | Task 8 |
| 接着改 → 原型更新 | Task 7,8 |
| 刷新不丢（草稿+原型落库）| Task 1,3 + 现有 spec 草稿 |
| 后 4 Tab 占位不报错 | Task 6 |

## 后续切片预留（不在本计划）
进度/产出/工具/可观测 Tab 真实功能、Swarm 引擎、治理后台、SpecChatPanel `prefill` prop（点选完整预填）、原型局部重生成/版本对比 → 见 spec §2 Roadmap。
