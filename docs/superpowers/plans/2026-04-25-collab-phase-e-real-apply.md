# 协作 Phase E — 真接 Platform Deploy + Fix-up Proposal + ChatPage Hook

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** 让 ChangeProposal apply 真正在 aPaaS 平台上落地变更（不再是 noop 切指针），失败时自动开 fix-up proposal 帮用户继续；同时激活 Phase B 的 fork hook（ChatPage 传 application_id）。

**Architecture:**
- 复用既有 `backend/app/incremental_executor.py:IncrementalExecutor.execute_diff(ConfigDiff)` — 这是 V1→V2 文档增量场景已经验证过的平台部署引擎
- 新桥：`backend/app/proposal/platform_apply.py` — 把 Phase B 的 `apply_plan`（基于 SPEC diff）翻译成 IncrementalExecutor 能消费的 `ConfigDiff`
- 改造 `apply.execute_apply`：apply_plan + 平台 dry-run 通过后调 IncrementalExecutor，记录详细 apply_log
- partial failure：自动 fork 当前 draft 成新 draft + create 新 ChangeProposal('fix-up' tag) 含未完成的 ops
- ChatPage `useChatStore.sendMessage` body 加 `application_id`，激活 chat.py 的 fork hook

**前置条件:**
- Phase A+B+C+D 完成（commits up to `1baeb51`），backend 191 tests passing baseline
- IncrementalExecutor 已在生产路径用过（V1→V2 文档增量更新）— 这是已验证的
- 用户准备测试 tenant（重要：执行前需用户确认有可踩 API 的测试 aPaaS 平台租户）

**Tech Stack:** 复用既有 generation pipeline + Phase B/C/D 的 proposal 机制。

**约定:** 中文 commit messages（Conventional Commits 风格）。每 task 一个 commit。

---

## ⚠ 启动前需要的真实环境

E1+E2 真踩平台 API。**执行前确认**：
- 已绑定 platform_url + platform_token 的测试 application（用户在某个 dev/staging tenant 上）
- 该 tenant 上的"破坏"是可接受的（apply 真创建对象/字段不可逆）
- 推荐：拿一个空白 application 走全流程，避免污染既有数据

如果用户只有生产 tenant，**先做 dry-run mode + 强 confirm**，不真落 ops（标 task 里）。

---

## Task 1: ChatPage 传 application_id 激活 fork hook (E3)

**Files:**
- Modify: `frontend/src/views/ChatPage.vue`（找到 send message 调用点，传 application_id）
- Modify: `frontend/src/api/conversation.ts`（如果有 send message wrapper，加可选 application_id 参数）
- Modify: `frontend/src/stores/coding.ts` 或类似（如有 chat store）

**简单**：找 ChatPage 调 `/api/conversations/{id}/send` 或 `/api/chat/send` 的地方，加 `application_id: store.currentApp?.id`。

### Step 1: 找调用点

```bash
cd "/Users/mars/Vibe Coding/apaas-builder-ai"
grep -nE "/send|sendMessage|chatApi\." frontend/src/views/ChatPage.vue frontend/src/api/*.ts | head -20
```

预期：找到 chat send fetch 调用。如果是 fetchEventSource SSE 调用，body JSON 直接加字段。

### Step 2: 加 application_id 字段

修改 send message 的 body 序列化处理，加：

```typescript
body: JSON.stringify({
  conversation_id: conversationId.value,
  message: ...,
  application_id: store.currentApp?.id ?? null,  // 新增
  // ... 既有字段
})
```

注意：`application_id` 在前端 store 里可能是 string（如 `"12"`），但后端 ChatRequest 要 int。先 grep 确认 store.currentApp.id 类型；如是 string 转 `Number(...)`，并加 `Number.isFinite` 检查避免 NaN。

### Step 3: vue-tsc 干净

```bash
cd frontend && npx vue-tsc --noEmit
```

### Step 4: Commit

```bash
git add frontend/src/views/ChatPage.vue frontend/src/api/*.ts
git commit -m "$(cat <<'EOF'
feat(collab/chat): ChatPage send message 带 application_id 激活 fork hook

ChatPage 调 /api/chat/send 或 /api/conversations/{id}/send 时附带
当前 store.currentApp.id（转 int），让 chat.py Phase B 的 fork hook
真触发：conversation.spec_id 空 + application 有 canonical → 自动
fork 出 personal draft，SpecAgent 操作 draft 不污染 canonical。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: ApplyPlan → ConfigDiff 翻译桥

**Files:**
- Create: `backend/app/proposal/platform_apply.py`
- Create: `backend/tests/test_platform_apply_diff.py`

### 背景

Phase B 的 `apply.diff_spec(canonical, draft) → list[ApplyOp]` 是 SPEC 层 diff（语义级）。

既有 `backend/app/config_diff.py` 已有 `compute_diff(old_config, new_config) → ConfigDiff` —— 它产出 IncrementalExecutor 能消费的 dataclass。

桥梁：把 `canonical Spec` + `draft Spec` 各自转 `config dict` (用 `app.spec.converter:spec_to_config`)，然后调 `compute_diff` 拿 ConfigDiff。

### platform_apply.py 实现

```python
"""Phase E：把 SPEC diff 翻译成 IncrementalExecutor 能消费的 ConfigDiff，并执行真平台部署"""
from __future__ import annotations
import logging
from typing import Optional

from app.spec.schema import Spec
from app.spec.converter import spec_to_config
from app.config_diff import compute_diff, ConfigDiff
from app.incremental_executor import IncrementalExecutor, ExecutionResult
from app.apaas_client import APaaSClient
from app.models import Application

logger = logging.getLogger(__name__)


def spec_diff_to_config_diff(canonical: Optional[Spec], draft: Spec) -> ConfigDiff:
    """把 SPEC 的 canonical → draft 转换成 IncrementalExecutor 能消费的 ConfigDiff

    canonical=None（全新应用）时，old_config={"data":{}}，diff 全部是 add ops
    """
    old_config = spec_to_config(canonical) if canonical else {"data": {"appName": "", "models": [], "roles": [], "dicts": [], "permissions": []}}
    new_config = spec_to_config(draft)
    return compute_diff(old_config, new_config)


async def execute_platform_apply(
    *,
    application: Application,
    canonical: Optional[Spec],
    draft: Spec,
    dry_run: bool = False,
) -> ExecutionResult:
    """真接平台 apply：调 IncrementalExecutor.execute_diff

    dry_run=True 时仅算 diff 不调平台 API（用于第二道门预检）。
    """
    diff = spec_diff_to_config_diff(canonical, draft)
    if dry_run:
        result = ExecutionResult()
        # diff 摘要写到 results
        for category in ("roles", "dicts", "models", "forms", "processes"):
            ops = getattr(diff, category, [])
            for op in ops:
                result.add_success(category, f"[dry-run] {op}")
        return result

    if not application.platform_url or not application.platform_token:
        raise RuntimeError(f"application {application.id} 未连接 aPaaS 平台（platform_url/token 缺失）")
    if not application.apaas_app_id:
        raise RuntimeError(f"application {application.id} 还没在 aPaaS 平台创建（apaas_app_id 缺失）")

    client = APaaSClient(
        base_url=application.platform_url,
        tenant_id=application.platform_tenant_id,
        token=application.platform_token,
    )
    new_config = spec_to_config(draft)
    executor = IncrementalExecutor(
        client=client,
        app_id=application.apaas_app_id,
        app_name=application.app_name,
        target_config=new_config,
    )
    return await executor.execute_diff(diff)
```

### Tests

`test_platform_apply_diff.py` 至少 3 测试（mock 既有 compute_diff + IncrementalExecutor）：
1. `test_canonical_none_treated_as_empty` — canonical=None → old_config 是空 dict，diff 全是 add
2. `test_dry_run_does_not_call_platform` — dry_run=True 不构造 client / executor，仅返回 diff 摘要
3. `test_platform_apply_calls_executor` — happy path：mock IncrementalExecutor.execute_diff，验证调用

Commit message：

```
feat(collab/proposal): SPEC diff → ConfigDiff 翻译桥 + execute_platform_apply

复用既有 compute_diff (config_diff.py) + IncrementalExecutor (V1→V2 增量
已验证)，避免重写平台部署逻辑。spec_diff_to_config_diff 把 canonical Spec
+ draft Spec 转 config dict 再 compute_diff 拿 ConfigDiff。

execute_platform_apply 支持 dry_run（仅算 diff 不调 platform API），用于
Phase B 第二道门预检。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
```

---

## Task 3: execute_apply 接 IncrementalExecutor 真部署

**Files:**
- Modify: `backend/app/proposal/apply.py`（execute_apply 替换 noop 实现）
- Modify: `backend/tests/test_proposal_apply.py`（既有测试可能假设 noop，需更新）

### 改动

`execute_apply` 的 try 分支 — 替换原来"切 canonical_spec_id 指针"的核心逻辑：

```python
async def execute_apply(
    db: AsyncSession,
    *,
    proposal_id: str,
    plan: ApplyPlan,
    tenant_id: int,
) -> dict:
    """真接平台 apply（Phase E 升级）。

    流程：
    1. load draft + canonical
    2. dry_run 一遍（IncrementalExecutor 也支持 dry-run，确认 diff 真能跑）
    3. 真执行 → ExecutionResult
    4. 写 apply_log（含 ExecutionResult.journal）
    5. 全部成功 → 切 canonical 指针 + status=applied
    6. 部分失败 → status=apply_failed，apply_log 记录 failed ops，触发 fix-up
       proposal 自动建（Task 4）
    """
    from datetime import datetime, timezone
    from app.spec.persistence import load_spec
    from app.proposal.platform_apply import execute_platform_apply

    proposal_row = (await db.execute(
        select(ChangeProposal).where(ChangeProposal.id == proposal_id)
    )).scalar_one()
    app_row = (await db.execute(
        select(Application).where(Application.id == proposal_row.application_id)
    )).scalar_one()

    apply_log: list[dict] = []
    success = True
    failure_reason = None
    exec_result_dict: dict = {}

    try:
        draft = await load_spec(db, proposal_row.draft_spec_id, tenant_id=tenant_id)
        if not draft:
            raise RuntimeError("draft 不存在")

        canonical = None
        if app_row.canonical_spec_id:
            canonical = await load_spec(db, app_row.canonical_spec_id, tenant_id=tenant_id)

        # 真平台 apply
        exec_result = await execute_platform_apply(
            application=app_row, canonical=canonical, draft=draft, dry_run=False,
        )
        exec_result_dict = exec_result.to_dict()
        apply_log.append({"executor_journal": exec_result.journal.to_dict()})

        if not exec_result.success:
            success = False
            failure_reason = "; ".join(exec_result.errors[:3]) or "executor returned success=False"
            proposal_row.status = "apply_failed"
        else:
            # 切 canonical_spec_id 指针 + draft.kind = canonical
            from app.models.spec import Spec as SpecORM
            spec_row = (await db.execute(select(SpecORM).where(SpecORM.id == draft.id))).scalar_one()
            spec_row.kind = "canonical"
            previous_canonical = app_row.canonical_spec_id
            app_row.canonical_spec_id = draft.id
            apply_log.append({"previous_canonical": previous_canonical})
            proposal_row.status = "applied"
            proposal_row.applied_at = datetime.now(timezone.utc).replace(tzinfo=None)

        proposal_row.apply_log = {
            "ops": apply_log,
            "executor_result": exec_result_dict,
            "success": success,
            "failure_reason": failure_reason,
        }
        await db.commit()

        # git 同步（Phase C 保留）
        if success:
            try:
                from app.git.sync import finalize_apply_to_git
                tag = await finalize_apply_to_git(db, proposal=proposal_row, application=app_row)
                if tag:
                    proposal_row.apply_log = {**(proposal_row.apply_log or {}), "git_tag": tag}
                    await db.commit()
            except Exception as e:
                logger.warning(f"git finalize failed: {e}")
                apply_log.append({"git_finalize_failed": str(e)})

        # partial failure → 自动开 fix-up proposal（Task 4 实现）
        if not success:
            try:
                from app.proposal.fixup import create_fixup_proposal
                fixup_id = await create_fixup_proposal(
                    db, failed_proposal=proposal_row, exec_result=exec_result, tenant_id=tenant_id,
                )
                proposal_row.apply_log = {**proposal_row.apply_log, "fixup_proposal_id": fixup_id}
                await db.commit()
            except Exception as e:
                logger.exception(f"fixup creation failed: {e}")

    except Exception as e:
        logger.exception(f"apply failed for proposal {proposal_id}: {e}")
        success = False
        failure_reason = str(e)
        proposal_row.status = "apply_failed"
        proposal_row.apply_log = {
            "ops": apply_log,
            "error": failure_reason,
        }
        await db.commit()

    return {
        "success": success,
        "failure_reason": failure_reason,
        "apply_log": apply_log,
        "executor_result": exec_result_dict,
    }
```

### Tests 更新

既有 `test_proposal_apply.py` 中如有测试假设 apply 后看到 `noop_in_v1` 标记，要更新：现在 apply_log 含 `executor_journal`。如果测试纯靠 mock，patch `execute_platform_apply` 让它返回 fake ExecutionResult。

加 1 个新测试：`test_apply_executor_failure_marks_apply_failed` — mock execute_platform_apply 返 ExecutionResult(success=False, errors=["..."])，断言 proposal.status='apply_failed' + apply_log 含 failure_reason。

Commit message：

```
feat(collab/proposal): execute_apply 接 IncrementalExecutor 真部署到平台

替换 Phase B/C/D v1 的 noop_in_v1 实现：
- 调 execute_platform_apply (Task 2 桥) → IncrementalExecutor.execute_diff
- 写 apply_log 含 executor.journal（详细资源创建/更新记录）
- 全成功：切 canonical_spec_id 指针 + draft kind→canonical + git tag
- 部分失败：status=apply_failed + 触发 fix-up proposal 自动建（Task 4）

⚠ 此 task ship 后 apply 真改远端 aPaaS 平台数据（不可逆）。生产前
确保用户已配测试 tenant + 走过 dry-run。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
```

---

## Task 4: Fix-up Proposal 自动开机制

**Files:**
- Create: `backend/app/proposal/fixup.py`
- Create: `backend/tests/test_proposal_fixup.py`

### fixup.py

```python
"""partial apply 失败时：自动 fork 当前 draft + 创建新 ChangeProposal 含未完成 ops

逻辑：
1. 失败的 proposal.status = 'apply_failed'，draft Spec 已经部分应用（e.g. 创建了 model A，
   但 model B 失败）。当前 draft 仍是"目标状态"，但 canonical 应该已经被部分推进。
2. fix-up proposal：fork 当前 draft → 新 draft（拷贝），创建新 ChangeProposal 引用同一应用，
   title="fix-up: <原 title>"，description 含 ExecutionResult.errors 摘要 + 失败 ops 列表
3. 不自动 promote — 用户人工查看后决定（safer）
"""
from __future__ import annotations
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collaboration import ChangeProposal
from app.proposal.persistence import create_proposal
from app.spec.persistence import fork_canonical_to_draft, load_spec
from app.incremental_executor import ExecutionResult


async def create_fixup_proposal(
    db: AsyncSession,
    *,
    failed_proposal: ChangeProposal,
    exec_result: ExecutionResult,
    tenant_id: int,
) -> Optional[str]:
    """为失败的 apply 自动创建 fix-up proposal。

    返回新 proposal.id，或 None（如无法 fork）。
    """
    # 用失败 proposal 的 draft 作为新 fix-up 的"基础"
    failed_draft = await load_spec(db, failed_proposal.draft_spec_id, tenant_id=tenant_id)
    if not failed_draft:
        return None

    # fork 一份新 draft（避免共享同一 Spec.id 行）
    new_draft = await fork_canonical_to_draft(
        db, canonical=failed_draft, user_id=failed_proposal.created_by, tenant_id=tenant_id,
    )

    # 失败摘要
    errors_summary = "\n".join(f"- {e}" for e in exec_result.errors[:10])
    journal_summary = []
    for entry in exec_result.journal.entries:
        marker = "✓" if entry.platform_id else "✗"
        journal_summary.append(f"{marker} {entry.operation} {entry.resource_type}:{entry.resource_code}")

    description = (
        f"⚠ 自动创建的 fix-up proposal，源自失败的 apply：[{failed_proposal.id}] {failed_proposal.title}\n\n"
        f"### 失败原因\n{errors_summary or '（无 errors，但 success=False）'}\n\n"
        f"### 已执行的操作（部分成功，部分失败）\n" + "\n".join(journal_summary) + "\n\n"
        f"---\n请人工评审：哪些 ops 已完成（不需重做）、哪些需要重试 / 调整后重新 apply。"
    )

    fixup = await create_proposal(
        db,
        application_id=failed_proposal.application_id,
        draft_spec_id=new_draft.id,
        base_canonical_spec_id=failed_proposal.base_canonical_spec_id,
        title=f"fix-up: {failed_proposal.title}",
        description=description,
        created_by=failed_proposal.created_by,
        status="draft",  # 不自动 promote — 等人工检查
    )
    return fixup.id
```

### Tests

`test_proposal_fixup.py` 2 测试：
1. `test_fixup_creates_new_draft_and_proposal` — mock failed proposal 含 draft，调 create_fixup_proposal → 新 proposal id 返回，DB 中存在
2. `test_fixup_includes_error_summary_in_description` — failed proposal 失败原因 / journal 内容正确出现在 fixup.description

Commit message：

```
feat(collab/proposal): partial apply 失败自动开 fix-up proposal

满足 spec D7 决策的完整版（之前 Phase B v1 仅记 status=apply_failed）：
- fork 失败 proposal 的 draft 成新 draft（避免共享行）
- create_proposal title="fix-up: ..."，description 含 ExecutionResult
  errors 摘要 + journal entries（标 ✓/✗）
- 新 proposal status='draft' 不自动 promote — 等人工检查后决定哪些
  ops 已完成不重做、哪些需重试

execute_apply 失败分支自动调用此函数，apply_log 写入 fixup_proposal_id
让前端能跳转。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
```

---

## Task 5: 前端 ProposalDetailPage 显示 platform deploy 进度 + fix-up 链接

**Files:**
- Modify: `frontend/src/views/ProposalDetailPage.vue`
- Modify: `frontend/src/types/proposal.ts`（apply_log shape 扩展）

### types 加

```typescript
export interface ExecutorJournalEntry {
  resource_type: string
  operation: string
  resource_name: string
  resource_code: string
  platform_id?: string | null
  timestamp: number
}

export interface ApplyLogV2 {
  ops: any[]
  executor_result?: {
    success: boolean
    results: Record<string, string[]>
    errors: string[]
    warnings: string[]
    journal: ExecutorJournalEntry[]
  }
  fixup_proposal_id?: string
  git_tag?: string
  failure_reason?: string
  error?: string
  previous_canonical?: string
}
```

### ProposalDetailPage UI

`apply` 卡片（status='applied'）和 `apply_failed` 卡片增强：

```vue
<section v-if="detail.status === 'applied'" class="applied-card">
  <h3>已 apply</h3>
  <p>@ {{ formatDate(detail.applied_at) }}</p>
  <p v-if="(detail.apply_log as any)?.git_tag">
    Git tag: <code>{{ (detail.apply_log as any).git_tag }}</code>
  </p>
  <details v-if="(detail.apply_log as any)?.executor_result">
    <summary>平台部署详情（{{ (detail.apply_log as any).executor_result.journal.length }} 个资源）</summary>
    <ul class="journal-list">
      <li v-for="(entry, idx) in (detail.apply_log as any).executor_result.journal" :key="idx">
        <span class="journal-icon">{{ entry.platform_id ? '✓' : '✗' }}</span>
        <code>{{ entry.operation }} {{ entry.resource_type }}:{{ entry.resource_code }}</code>
        <span v-if="entry.platform_id" class="muted small">(id: {{ entry.platform_id }})</span>
      </li>
    </ul>
  </details>
</section>

<section v-if="detail.status === 'apply_failed'" class="apply-failed-card">
  <h3>apply 失败</h3>
  <p>{{ (detail.apply_log as any)?.failure_reason || (detail.apply_log as any)?.error || '未知错误' }}</p>
  <details v-if="(detail.apply_log as any)?.executor_result?.errors?.length">
    <summary>错误列表（{{ (detail.apply_log as any).executor_result.errors.length }} 条）</summary>
    <ul class="error-list">
      <li v-for="(err, idx) in (detail.apply_log as any).executor_result.errors" :key="idx">{{ err }}</li>
    </ul>
  </details>
  <p v-if="(detail.apply_log as any)?.fixup_proposal_id" class="fixup-link">
    🔧 系统已自动创建 fix-up proposal：
    <button class="builder-btn builder-btn-primary" type="button" @click="goToProposal((detail.apply_log as any).fixup_proposal_id)">
      查看 fix-up
    </button>
  </p>
</section>
```

加 css：

```css
.journal-list, .error-list { list-style: none; padding-left: 0; margin-top: 8px; }
.journal-list li, .error-list li { padding: 4px 0; border-bottom: 1px solid var(--line); }
.journal-icon { display: inline-block; width: 16px; }
.fixup-link { margin-top: 12px; padding: 8px; background: var(--t-warning-subtle); border-radius: 4px; }
```

`goToProposal` method 应已在 Phase B 时存在（router.push）。

vue-tsc 干净 + commit。

Commit message：

```
feat(collab/fe): ProposalDetail 显示 platform deploy 进度 + fix-up 链接

apply_log 升级到 v2 shape（含 executor_result.journal/errors）：
- applied 卡片新增"平台部署详情"折叠面板，列每个资源 ✓/✗ + platform_id
- apply_failed 卡片显示 errors 列表 + 自动 fix-up proposal 跳转按钮

types/proposal.ts 加 ExecutorJournalEntry / ApplyLogV2 interfaces。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
```

---

## Task 6: E2E + handoff

- Backend pytest 全过（≥ 191 + Phase E 新增 ~10 = ~200+）
- Frontend vue-tsc 干净
- 真机 smoke（**需要测试 tenant 配齐**）：
  1. 用测试 tenant 上的 application（platform_url + token + apaas_app_id 配过）
  2. ChatPage 编辑（带 application_id）→ fork hook 真触发 → SpecAgent 改 draft
  3. promote → ProposalDetail → approve → apply
  4. apply 真在测试 tenant 上创建对象/字段（去 aPaaS 平台 UI 验证）
  5. 故意构造一个会失败的 case（如重复字段名）→ 验 fix-up proposal 自动建
- 写 `docs/superpowers/HANDOFF-collab-phase-e-done.md`
- Commit handoff

---

## 自检（Plan Self-Review）

**Spec / backlog 覆盖**：
- ✅ E1 真接 platform deploy → Task 2 + Task 3
- ✅ E2 fix-up proposal 自动开 → Task 4
- ✅ E3 ChatPage application_id → Task 1
- ✅ apply_log 升级展示 → Task 5

**简化范围**：
- 不修改 IncrementalExecutor（复用既有），只造翻译桥
- fix-up proposal 不自动 promote（safer，等人工 review）
- dry_run mode 实现了但 Phase B 第二道门暂未真用 — Task 3 留个 hook 后续可加

**风险**：
- Task 3 上 ship 后 apply **真改远端平台数据** — 强烈建议先 dry-run 验证一轮
- IncrementalExecutor 既有逻辑可能有边缘 bug（虽然 V1→V2 跑过，但 Phase E 走的是新 entry path）

---

## 执行选择

Plan complete. 沿用 subagent-driven 模式。建议顺序：
- 先 Task 1（前端小改）单独 ship，**激活 fork hook**，可立刻测试 Phase B 已经做过的 draft 流
- 再 Task 2+3+4 后端核心（**不上生产 tenant 用**，只在测试 tenant 真测）
- 再 Task 5 前端展示
- 最后 Task 6 收尾
