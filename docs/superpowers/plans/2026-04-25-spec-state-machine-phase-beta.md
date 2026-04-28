# SPEC State Machine — Phase β (Frontend Three-Pane + UI Tool Calls) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Build the frontend three-pane layout (Composer / SpecCanvas / SpecInspector) that lets users see live SPEC state, click confirm/dismiss/edit on each item, and consume the `spec_patch` SSE events the backend already streams.

**Architecture:** New `frontend/src/api/spec.ts` (REST client) + `frontend/src/stores/spec.ts` (Pinia store with SSE patch handler) + 3 new Vue components (`PhaseBar.vue`, `SpecCanvas.vue`, `SpecInspector.vue`). Integrate into `ChatPage.vue` as three-pane mode (when `currentAgent === 'requirements'` AND `spec_id IS NOT NULL`). Preserve existing two-pane mode for non-spec conversations.

**Tech Stack:** Vue 3 Composition API, TypeScript (strict mode via `vue-tsc`), Pinia, Element Plus, existing `request.ts` axios wrapper, existing SSE consumer pattern in ChatPage. **No new test framework introduced** — verification via vue-tsc type-check + visual Preview tool.

**Reference spec:** [docs/superpowers/specs/2026-04-25-spec-state-machine-design.md](../specs/2026-04-25-spec-state-machine-design.md) section 8 (UI 改动)

**Phase β scope** (this plan): frontend wire-up. No backend changes (Phase α delivered all the API surface). Phase γ entry-migrations are separate.

**Estimated effort:** 4-5 working days, 7 tasks.

---

## Prerequisites (verify before Task 1)

- Phase α merged on `claude/coding-shell-alignment` (commits `2b5d209` → `e8e0fa1`)
- Backend running with new code (restart if dev server was up before Phase α)
- MySQL `applications.canonical_spec_id` + `conversations.spec_id` + `specs` table all present (already migrated as part of Phase α verification)

---

## File Map

| Path | Action | Responsibility |
|---|---|---|
| `frontend/src/api/spec.ts` | Create | REST client: `createSpec`, `getSpec`, `transitionPhase`, `updateItem` |
| `frontend/src/types/spec.ts` | Create | TypeScript types mirroring backend Pydantic (`Phase`, `Spec`, `Decision`, etc.) |
| `frontend/src/stores/spec.ts` | Create | Pinia store: holds current `Spec`, exposes mutations bound to API + SSE event handlers |
| `frontend/src/components/spec/PhaseBar.vue` | Create | 5-step phase indicator, click-to-transition |
| `frontend/src/components/spec/SpecCanvas.vue` | Create | Main canvas with 5 collapsible sections + per-card actions |
| `frontend/src/components/spec/SpecCanvas/RoleCard.vue` | Create | Single role card with confirm/edit/dismiss |
| `frontend/src/components/spec/SpecCanvas/ObjectCard.vue` | Create | Single object card (with nested fields) |
| `frontend/src/components/spec/SpecCanvas/DictCard.vue` | Create | Single dict card |
| `frontend/src/components/spec/SpecCanvas/PermissionCard.vue` | Create | Single permission group card |
| `frontend/src/components/spec/SpecCanvas/GoalCard.vue` | Create | Goal summary card |
| `frontend/src/components/spec/SpecInspector.vue` | Create | Right-pane: completeness ring + decisions list + version timeline |
| `frontend/src/views/ChatPage.vue` | Modify | Add `useSpecMode` branch with three-pane layout; pipe `spec_patch` SSE events to spec store |
| `frontend/src/styles/spec.css` | Create | Scoped styles for spec components (uses existing `--t-*` design tokens) |

---

## Conventions

- **Type-safe**: every component uses `<script setup lang="ts">` with explicit prop/emit types. `npm run build` must succeed (vue-tsc gate) before commit.
- **Pinia store pattern**: follow existing `stores/preview.ts` shape (reactive refs + helper functions, exported as composable).
- **API pattern**: follow existing `api/conversation.ts` shape (axios wrapper from `request.ts`, typed request/response).
- **Visual verification**: for UI tasks, use `mcp__Claude_Preview__preview_*` tools to take screenshots + run interactions before committing. For data-layer tasks, vue-tsc + a one-line manual probe is enough.
- **CSS tokens**: only use existing `--t-*` design tokens (from [theme-vars.css](frontend/src/styles/theme-vars.css)). Do NOT introduce raw hex colors. (Tier 1 task A — design token migration — is separate; this plan stays inside the existing token set.)
- **Commit prefix**: `feat(spec-ui):` for components/store, `feat(api-spec):` for API client.

---

## Task 1: Spec API client + TypeScript types

**Files:**
- Create: `frontend/src/types/spec.ts`
- Create: `frontend/src/api/spec.ts`

- [ ] **Step 1.1: Write `frontend/src/types/spec.ts`**

```ts
// Mirrors backend Pydantic models in app/spec/schema.py

export type Phase = 'gathering' | 'drafting' | 'generating' | 'ready'
export type RoleScope = 'SELF' | 'DEPT' | 'DEPT_LOW' | 'ALL'
export type PermissionOp = 'all' | 'add' | 'edit' | 'delete' | 'view'
export type PermissionData = 'ALL' | 'SELF' | 'DEPT' | 'DEPT_LOW'

export interface Decision {
  id: string
  topic: string
  why_blocking: string | null
  options: string[]
  blocking: boolean
  raised_in_phase: Phase
  resolved: boolean
  resolution: string | null
  created_at: string
  resolved_at: string | null
}

export interface Goal {
  title: string
  summary: string
  business_problem: string
  confirmed: boolean
}

export interface Role {
  code: string
  name: string
  scope: RoleScope
  description: string | null
  confirmed: boolean
}

export interface FieldSpec {
  code: string
  name: string
  type: string
  required: boolean
  dict_code: string | null
  ref_model: string | null
  ref_field: string | null
  description: string | null
  confirmed: boolean
}

export interface ObjectSpec {
  code: string
  name: string
  description: string | null
  fields: FieldSpec[]
  sub_objects: Record<string, FieldSpec[]>
  confirmed: boolean
}

export interface DictOption {
  code: string
  name: string
}

export interface DictSpec {
  code: string
  name: string
  options: DictOption[]
  confirmed: boolean
}

export interface PermissionRule {
  role: string
  op: PermissionOp
  data: PermissionData
}

export interface PermissionSpec {
  object_code: string
  rules: PermissionRule[]
  confirmed: boolean
}

export interface Completeness {
  confirmed: number
  total: number
  by_section: Record<string, [number, number]>
  pending_decisions: number
  blocking_decisions: number
}

export interface Spec {
  id: string
  application_id: number | null
  version: number
  parent_spec_id: string | null
  phase: Phase
  goal: Goal | null
  roles: Role[]
  objects: ObjectSpec[]
  dicts: DictSpec[]
  permissions: PermissionSpec[]
  decisions_pending: Decision[]
  decisions_resolved: Decision[]
  completeness: Completeness
  created_at: string
  updated_at: string
  created_by: number
}

export type ItemType = 'role' | 'object' | 'field' | 'dict' | 'permission'
export type ItemAction = 'confirm' | 'dismiss' | 'update'
```

- [ ] **Step 1.2: Write `frontend/src/api/spec.ts`**

Look at `frontend/src/api/conversation.ts` for the import pattern (likely `import request from './request'` or similar). Then:

```ts
import request from '@/utils/request'  // or whichever path matches existing api/*.ts files
import type { Spec, Phase, ItemType, ItemAction } from '@/types/spec'

export interface CreateSpecRequest {
  application_id?: number | null
}

export interface CreateSpecResponse {
  id: string
  phase: Phase
}

export const specApi = {
  create(body: CreateSpecRequest = {}) {
    return request.post<CreateSpecResponse>('/spec', body)
  },
  get(specId: string) {
    return request.get<Spec>(`/spec/${specId}`)
  },
  transitionPhase(specId: string, target: Phase, reason = 'user request') {
    return request.put<Spec>(`/spec/${specId}/phase`, { target, reason })
  },
  updateItem(
    specId: string,
    itemType: ItemType,
    itemCode: string,
    action: ItemAction,
    payload: Record<string, unknown> = {}
  ) {
    return request.put<Spec>(
      `/spec/${specId}/items/${itemType}/${itemCode}`,
      { action, payload }
    )
  },
}
```

**Note**: the actual request import path may differ from `@/utils/request`. Open `frontend/src/api/conversation.ts` and copy its import statement verbatim.

- [ ] **Step 1.3: Verify TypeScript compiles**

```bash
cd frontend && npm run build:nocheck 2>&1 | tail -10
# OR if you want full type-check:
cd frontend && npx vue-tsc --noEmit 2>&1 | grep -i "spec\|error" | head -20
```
Expected: no errors involving `src/api/spec.ts` or `src/types/spec.ts`.

- [ ] **Step 1.4: Commit**

```bash
cd "/Users/mars/Vibe Coding/apaas-builder-ai" && git add frontend/src/types/spec.ts frontend/src/api/spec.ts && git commit -m "$(cat <<'EOF'
feat(api-spec): TypeScript types + REST client

types/spec.ts mirrors backend Pydantic schema.py 一对一。
api/spec.ts 包 4 个 endpoint：create/get/transitionPhase/updateItem。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Pinia spec store

**Files:**
- Create: `frontend/src/stores/spec.ts`

- [ ] **Step 2.1: Read existing store pattern**

```bash
cat frontend/src/stores/preview.ts | head -50
```
Note the pattern (defineStore name, ref-based state, exposed actions, return shape).

- [ ] **Step 2.2: Write `frontend/src/stores/spec.ts`**

```ts
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { specApi } from '@/api/spec'
import type { Spec, Phase, ItemType, ItemAction } from '@/types/spec'

export const useSpecStore = defineStore('spec', () => {
  const current = ref<Spec | null>(null)
  const loading = ref(false)
  const lastError = ref<string | null>(null)

  const phase = computed<Phase | null>(() => current.value?.phase ?? null)
  const completeness = computed(() => current.value?.completeness ?? null)
  const pendingDecisions = computed(() => current.value?.decisions_pending ?? [])
  const blockingDecisions = computed(() =>
    pendingDecisions.value.filter((d) => d.blocking && !d.resolved)
  )

  async function load(specId: string) {
    loading.value = true
    lastError.value = null
    try {
      current.value = await specApi.get(specId)
    } catch (e: unknown) {
      lastError.value = e instanceof Error ? e.message : String(e)
      current.value = null
    } finally {
      loading.value = false
    }
  }

  async function create(applicationId: number | null = null): Promise<string> {
    const resp = await specApi.create({ application_id: applicationId })
    return resp.id
  }

  async function transitionPhase(target: Phase, reason = 'user request') {
    if (!current.value) return
    try {
      current.value = await specApi.transitionPhase(current.value.id, target, reason)
    } catch (e: unknown) {
      lastError.value = e instanceof Error ? e.message : String(e)
      throw e
    }
  }

  async function updateItem(
    type: ItemType, code: string, action: ItemAction, payload: Record<string, unknown> = {}
  ) {
    if (!current.value) return
    try {
      current.value = await specApi.updateItem(current.value.id, type, code, action, payload)
    } catch (e: unknown) {
      lastError.value = e instanceof Error ? e.message : String(e)
      throw e
    }
  }

  /** Apply a `spec_patch` SSE event payload directly to the store
   * (saves a round-trip to GET /spec/{id} after every LLM tool call). */
  function applyPatch(specPayload: Spec) {
    current.value = specPayload
  }

  function reset() {
    current.value = null
    lastError.value = null
  }

  return {
    current, loading, lastError,
    phase, completeness, pendingDecisions, blockingDecisions,
    load, create, transitionPhase, updateItem, applyPatch, reset,
  }
})
```

- [ ] **Step 2.3: Verify compile**
```bash
cd frontend && npx vue-tsc --noEmit 2>&1 | grep -E "stores/spec|error TS" | head -10
```
Expected: no errors in stores/spec.ts.

- [ ] **Step 2.4: Commit**
```bash
cd "/Users/mars/Vibe Coding/apaas-builder-ai" && git add frontend/src/stores/spec.ts && git commit -m "$(cat <<'EOF'
feat(spec-ui): Pinia store with applyPatch hook for SSE 流式更新

useSpecStore 暴露 load/create/transitionPhase/updateItem + applyPatch
（给 ChatPage SSE spec_patch 事件直接写入，避免每次 tool 调用都 GET）。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: PhaseBar component

**Files:**
- Create: `frontend/src/components/spec/PhaseBar.vue`

- [ ] **Step 3.1: Write the component**

```vue
<script setup lang="ts">
import { computed } from 'vue'
import type { Phase } from '@/types/spec'
import { useSpecStore } from '@/stores/spec'
import { ElMessage } from 'element-plus'

const spec = useSpecStore()

interface PhaseStep {
  key: Phase | 'code' | 'deploy'
  label: string
  status: 'done' | 'active' | 'pending'
  clickable: boolean
}

const steps = computed<PhaseStep[]>(() => {
  const p = spec.phase ?? 'gathering'
  const order: Phase[] = ['gathering', 'drafting', 'generating', 'ready']
  const currentIdx = order.indexOf(p)
  return [
    {
      key: 'gathering' as Phase,
      label: '理解需求',
      status: currentIdx > 0 ? 'done' : 'active',
      clickable: currentIdx > 0,  // can rewind to gathering
    },
    {
      key: 'drafting' as Phase,
      label: 'SPEC 设计',
      status: currentIdx > 1 ? 'done' : currentIdx === 1 ? 'active' : 'pending',
      clickable: currentIdx >= 1,
    },
    {
      key: 'generating' as Phase,
      label: '配置生成',
      status: currentIdx >= 2 ? (currentIdx > 2 ? 'done' : 'active') : 'pending',
      clickable: false,  // generating runs only when SPEC complete
    },
    { key: 'code', label: '自开发', status: 'pending', clickable: false },
    { key: 'deploy', label: '部署', status: 'pending', clickable: false },
  ]
})

async function handleClick(step: PhaseStep) {
  if (!step.clickable || step.key === 'code' || step.key === 'deploy') return
  try {
    await spec.transitionPhase(step.key as Phase, '用户在 PhaseBar 点击切换')
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    ElMessage.warning(`无法切换到 ${step.label}：${msg}`)
  }
}
</script>

<template>
  <nav class="phase-bar" aria-label="搭建阶段">
    <button
      v-for="(step, idx) in steps"
      :key="step.key"
      class="phase-step"
      :class="[step.status, { clickable: step.clickable, disabled: !step.clickable }]"
      :disabled="!step.clickable"
      @click="handleClick(step)"
    >
      <span class="phase-index">{{ idx + 1 }}</span>
      <span class="phase-label">{{ step.label }}</span>
    </button>
  </nav>
</template>

<style scoped>
.phase-bar {
  display: flex;
  align-items: center;
  gap: 8px;
}
.phase-step {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: var(--t-radius-md);
  background: var(--t-bg-input);
  color: var(--t-text-secondary);
  border: 1px solid var(--t-border-subtle);
  cursor: pointer;
  font-size: 13px;
  transition: all 0.15s var(--t-ease, cubic-bezier(0.2, 0.9, 0.3, 1));
}
.phase-step.disabled { cursor: not-allowed; opacity: 0.55; }
.phase-step.active {
  background: var(--t-brand-subtle);
  color: var(--t-brand);
  border-color: var(--t-brand);
  font-weight: 600;
}
.phase-step.done {
  background: var(--t-success-subtle);
  color: var(--t-success);
  border-color: var(--t-success-subtle);
}
.phase-step.clickable:hover:not(.disabled) {
  background: var(--t-bg-panel-hover);
}
.phase-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: rgba(0,0,0,0.06);
  font-size: 11px;
  font-weight: 600;
}
.phase-step.active .phase-index { background: var(--t-brand); color: white; }
.phase-step.done .phase-index { background: var(--t-success); color: white; }
</style>
```

- [ ] **Step 3.2: Type-check**
```bash
cd frontend && npx vue-tsc --noEmit 2>&1 | grep -E "PhaseBar\.vue|error TS" | head -10
```
Expected: no errors.

- [ ] **Step 3.3: Commit**
```bash
cd "/Users/mars/Vibe Coding/apaas-builder-ai" && git add frontend/src/components/spec/PhaseBar.vue && git commit -m "$(cat <<'EOF'
feat(spec-ui): PhaseBar 组件（5 步指示器 + 可点击回退）

5 步：理解需求 / SPEC 设计 / 配置生成 / 自开发 / 部署。
点已完成阶段触发 transitionPhase；blocking 决策未解时 backend 拒绝
+ ElMessage 提示。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: SpecCanvas + 5 sub-card components

**Files:**
- Create: `frontend/src/components/spec/SpecCanvas/GoalCard.vue`
- Create: `frontend/src/components/spec/SpecCanvas/RoleCard.vue`
- Create: `frontend/src/components/spec/SpecCanvas/ObjectCard.vue`
- Create: `frontend/src/components/spec/SpecCanvas/DictCard.vue`
- Create: `frontend/src/components/spec/SpecCanvas/PermissionCard.vue`
- Create: `frontend/src/components/spec/SpecCanvas.vue`

Each card has 3 actions (✅ confirm / ✏️ edit / ❌ dismiss). Edit opens an inline editor or simple ElDialog. For Phase β, **edit can be deferred** — implement confirm + dismiss only (most-frequent actions). Edit-via-dialog can be a follow-up if needed.

- [ ] **Step 4.1: Write `RoleCard.vue` (template for the other 4)**

```vue
<script setup lang="ts">
import { useSpecStore } from '@/stores/spec'
import type { Role } from '@/types/spec'
import { ElMessage, ElMessageBox } from 'element-plus'

const props = defineProps<{ role: Role }>()
const spec = useSpecStore()

async function confirm() {
  try {
    await spec.updateItem('role', props.role.code, 'confirm')
    ElMessage.success(`已确认角色：${props.role.name}`)
  } catch (e: unknown) {
    ElMessage.error(`确认失败：${e instanceof Error ? e.message : String(e)}`)
  }
}

async function dismiss() {
  try {
    await ElMessageBox.confirm(
      `确定删除角色「${props.role.name}」？此操作不可撤销。`,
      '确认删除',
      { type: 'warning' }
    )
  } catch { return /* user cancelled */ }
  try {
    await spec.updateItem('role', props.role.code, 'dismiss')
    ElMessage.success(`已删除角色：${props.role.name}`)
  } catch (e: unknown) {
    ElMessage.error(`删除失败：${e instanceof Error ? e.message : String(e)}`)
  }
}
</script>

<template>
  <article class="spec-card" :class="{ confirmed: role.confirmed }">
    <header class="spec-card-header">
      <h4 class="spec-card-title">{{ role.name }}</h4>
      <span class="spec-card-code">{{ role.code }}</span>
      <span class="spec-card-scope">数据范围：{{ scopeLabel(role.scope) }}</span>
    </header>
    <p v-if="role.description" class="spec-card-desc">{{ role.description }}</p>
    <footer class="spec-card-actions">
      <span v-if="role.confirmed" class="spec-card-status">✓ 已确认</span>
      <template v-else>
        <button class="action-btn confirm" @click="confirm">✓ 确认</button>
        <button class="action-btn dismiss" @click="dismiss">✕ 删除</button>
      </template>
    </footer>
  </article>
</template>

<script lang="ts">
function scopeLabel(scope: string): string {
  return ({ ALL: '全部', DEPT: '本部门', DEPT_LOW: '部门及下级', SELF: '仅本人' } as Record<string, string>)[scope] || scope
}
</script>

<style scoped>
.spec-card {
  border: 1px solid var(--t-border-subtle);
  border-radius: var(--t-radius-md);
  padding: 12px 14px;
  background: var(--t-bg-panel);
  transition: border-color 0.15s;
}
.spec-card.confirmed {
  border-color: var(--t-success);
  background: var(--t-success-subtle);
}
.spec-card-header { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.spec-card-title { margin: 0; font-size: 14px; color: var(--t-text-primary); }
.spec-card-code { font-family: monospace; font-size: 12px; color: var(--t-text-muted); }
.spec-card-scope { font-size: 12px; color: var(--t-text-secondary); margin-left: auto; }
.spec-card-desc { margin: 6px 0; font-size: 13px; color: var(--t-text-secondary); }
.spec-card-actions { display: flex; gap: 8px; margin-top: 8px; }
.action-btn {
  padding: 4px 10px;
  font-size: 12px;
  border: 1px solid var(--t-border-subtle);
  border-radius: var(--t-radius-sm);
  background: var(--t-bg-input);
  cursor: pointer;
}
.action-btn.confirm:hover { background: var(--t-success-subtle); border-color: var(--t-success); color: var(--t-success); }
.action-btn.dismiss:hover { background: var(--t-danger-subtle); border-color: var(--t-danger); color: var(--t-danger); }
.spec-card-status { color: var(--t-success); font-size: 12px; font-weight: 600; }
</style>
```

- [ ] **Step 4.2: Write `GoalCard.vue` (singleton — top-of-canvas card)**

```vue
<script setup lang="ts">
import { useSpecStore } from '@/stores/spec'
import type { Goal } from '@/types/spec'
import { ElMessage } from 'element-plus'

const props = defineProps<{ goal: Goal }>()
const spec = useSpecStore()

// Goal uses singleton-style item update; we treat code as fixed sentinel "_goal"
async function confirm() {
  try {
    // PUT /spec/{id}/items/role/_goal won't work — goal isn't a "role". Goal confirmation
    // is intentionally NOT in the items REST surface for Phase α. Frontend handles by
    // mutating the role-equivalent through a dedicated path or just hides the button.
    // For Phase β: skip confirm action; goal flips to confirmed=true through LLM tool call.
    ElMessage.info('应用目标在 SPEC 流程中由 AI 自动确认（暂不支持手动确认按钮）')
  } catch (e: unknown) {
    ElMessage.error(String(e))
  }
}
</script>

<template>
  <article class="spec-card goal-card" :class="{ confirmed: goal.confirmed }">
    <header class="spec-card-header">
      <h3 class="spec-card-title">🎯 {{ goal.title }}</h3>
      <span v-if="goal.confirmed" class="spec-card-status">✓ 已确认</span>
    </header>
    <p class="spec-card-desc"><strong>业务问题：</strong>{{ goal.business_problem }}</p>
    <p class="spec-card-desc"><strong>系统简介：</strong>{{ goal.summary }}</p>
  </article>
</template>

<style scoped>
.goal-card {
  border-left: 4px solid var(--t-brand);
}
.goal-card.confirmed { border-left-color: var(--t-success); }
.spec-card-header { display: flex; align-items: baseline; justify-content: space-between; }
.spec-card-title { margin: 0 0 8px 0; font-size: 16px; }
.spec-card-desc { margin: 4px 0; font-size: 13px; color: var(--t-text-secondary); }
.spec-card-status { color: var(--t-success); font-size: 12px; font-weight: 600; }
</style>
```

(Note: Goal `confirm` UX is constrained because the backend `/items/role/_goal` doesn't map. For Phase β, goal stays AI-driven; user can `dismiss` it indirectly by chatting "重新定义目标". A dedicated `/items/goal` REST surface is a Phase γ enhancement.)

- [ ] **Step 4.3: Write `ObjectCard.vue`, `DictCard.vue`, `PermissionCard.vue`**

Mirror RoleCard structure. Each takes its respective Pydantic type as prop, calls `spec.updateItem('object'|'dict'|'permission', code, 'confirm'|'dismiss')`. For ObjectCard, list nested fields with their own confirm/dismiss buttons (call `spec.updateItem('field', field_code, 'confirm', { object_code: object.code })`).

Code pattern for ObjectCard:

```vue
<script setup lang="ts">
import { useSpecStore } from '@/stores/spec'
import type { ObjectSpec } from '@/types/spec'
import { ElMessage, ElMessageBox } from 'element-plus'

const props = defineProps<{ object: ObjectSpec }>()
const spec = useSpecStore()

async function confirmObject() {
  try {
    await spec.updateItem('object', props.object.code, 'confirm')
    ElMessage.success(`已确认对象：${props.object.name}`)
  } catch (e: unknown) {
    ElMessage.error(`确认失败：${e instanceof Error ? e.message : String(e)}`)
  }
}

async function dismissObject() {
  try { await ElMessageBox.confirm(`删除对象「${props.object.name}」及其全部字段？`, '确认删除', { type: 'warning' }) }
  catch { return }
  try {
    await spec.updateItem('object', props.object.code, 'dismiss')
    ElMessage.success(`已删除对象：${props.object.name}`)
  } catch (e: unknown) {
    ElMessage.error(`删除失败：${e instanceof Error ? e.message : String(e)}`)
  }
}

async function confirmField(fieldCode: string) {
  try {
    await spec.updateItem('field', fieldCode, 'confirm', { object_code: props.object.code })
    ElMessage.success('字段已确认')
  } catch (e: unknown) {
    ElMessage.error(`确认失败：${e instanceof Error ? e.message : String(e)}`)
  }
}

async function dismissField(fieldCode: string, fieldName: string) {
  try { await ElMessageBox.confirm(`删除字段「${fieldName}」？`, '确认删除', { type: 'warning' }) }
  catch { return }
  try {
    await spec.updateItem('field', fieldCode, 'dismiss', { object_code: props.object.code })
    ElMessage.success('字段已删除')
  } catch (e: unknown) {
    ElMessage.error(`删除失败：${e instanceof Error ? e.message : String(e)}`)
  }
}
</script>

<template>
  <article class="spec-card object-card" :class="{ confirmed: object.confirmed }">
    <header class="spec-card-header">
      <h4 class="spec-card-title">📋 {{ object.name }} <span class="spec-card-code">{{ object.code }}</span></h4>
    </header>
    <p v-if="object.description" class="spec-card-desc">{{ object.description }}</p>
    <ul class="field-list">
      <li v-for="f in object.fields" :key="f.code" class="field-item" :class="{ confirmed: f.confirmed }">
        <span class="field-name">{{ f.name }}</span>
        <span class="field-type">{{ f.type }}</span>
        <span class="field-code">{{ f.code }}</span>
        <span v-if="f.required" class="field-req">必填</span>
        <span class="field-actions">
          <template v-if="!f.confirmed">
            <button class="action-btn confirm" @click="confirmField(f.code)">✓</button>
            <button class="action-btn dismiss" @click="dismissField(f.code, f.name)">✕</button>
          </template>
          <span v-else class="field-status">✓</span>
        </span>
      </li>
    </ul>
    <footer class="spec-card-actions">
      <span v-if="object.confirmed" class="spec-card-status">✓ 已确认</span>
      <template v-else>
        <button class="action-btn confirm" @click="confirmObject">✓ 确认整个对象</button>
        <button class="action-btn dismiss" @click="dismissObject">✕ 删除对象</button>
      </template>
    </footer>
  </article>
</template>

<style scoped>
.object-card { padding: 14px 16px; }
.field-list { list-style: none; padding: 0; margin: 8px 0; border-top: 1px dashed var(--t-border-subtle); }
.field-item { display: flex; align-items: center; gap: 10px; padding: 6px 0; border-bottom: 1px dashed var(--t-border-subtle); font-size: 13px; }
.field-item.confirmed { color: var(--t-success); }
.field-name { font-weight: 500; min-width: 100px; }
.field-type { color: var(--t-text-secondary); font-size: 12px; }
.field-code { font-family: monospace; font-size: 11px; color: var(--t-text-muted); }
.field-req { background: var(--t-warning-subtle); color: var(--t-warning); padding: 1px 6px; border-radius: 3px; font-size: 11px; }
.field-actions { margin-left: auto; display: flex; gap: 4px; }
.field-actions .action-btn { padding: 2px 6px; font-size: 11px; }
.field-status { color: var(--t-success); font-weight: 600; }
.spec-card { border: 1px solid var(--t-border-subtle); border-radius: var(--t-radius-md); padding: 12px 14px; background: var(--t-bg-panel); }
.spec-card.confirmed { border-color: var(--t-success); background: var(--t-success-subtle); }
.spec-card-header { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.spec-card-title { margin: 0; font-size: 14px; color: var(--t-text-primary); }
.spec-card-code { font-family: monospace; font-size: 12px; color: var(--t-text-muted); }
.spec-card-desc { margin: 6px 0; font-size: 13px; color: var(--t-text-secondary); }
.spec-card-actions { display: flex; gap: 8px; margin-top: 8px; }
.action-btn { padding: 4px 10px; font-size: 12px; border: 1px solid var(--t-border-subtle); border-radius: var(--t-radius-sm); background: var(--t-bg-input); cursor: pointer; }
.action-btn.confirm:hover { background: var(--t-success-subtle); border-color: var(--t-success); color: var(--t-success); }
.action-btn.dismiss:hover { background: var(--t-danger-subtle); border-color: var(--t-danger); color: var(--t-danger); }
.spec-card-status { color: var(--t-success); font-size: 12px; font-weight: 600; }
</style>
```

For DictCard and PermissionCard, follow the same pattern:
- DictCard: list options (read-only display), confirm/dismiss the whole dict
- PermissionCard: list `rules` (role × op × data) as a small table, confirm/dismiss the whole permission group

- [ ] **Step 4.4: Write `SpecCanvas.vue` (composes all the cards)**

```vue
<script setup lang="ts">
import { computed } from 'vue'
import { useSpecStore } from '@/stores/spec'
import GoalCard from './SpecCanvas/GoalCard.vue'
import RoleCard from './SpecCanvas/RoleCard.vue'
import ObjectCard from './SpecCanvas/ObjectCard.vue'
import DictCard from './SpecCanvas/DictCard.vue'
import PermissionCard from './SpecCanvas/PermissionCard.vue'

const spec = useSpecStore()

const sections = computed(() => [
  { key: 'goal', label: '🎯 业务目标', count: spec.current?.goal ? 1 : 0 },
  { key: 'roles', label: '👥 角色', count: spec.current?.roles.length ?? 0 },
  { key: 'objects', label: '📋 数据对象', count: spec.current?.objects.length ?? 0 },
  { key: 'dicts', label: '📚 数据字典', count: spec.current?.dicts.length ?? 0 },
  { key: 'permissions', label: '🔒 权限', count: spec.current?.permissions.length ?? 0 },
])
</script>

<template>
  <div class="spec-canvas">
    <header v-if="!spec.current" class="empty-state">
      <p>尚未开始 SPEC 设计 — 在左侧聊天框输入需求开始</p>
    </header>
    <template v-else>
      <section v-for="sec in sections" :key="sec.key" class="canvas-section">
        <header class="section-header">
          <h3>{{ sec.label }} <span class="section-count">{{ sec.count }}</span></h3>
        </header>
        <div class="section-body">
          <GoalCard v-if="sec.key === 'goal' && spec.current.goal" :goal="spec.current.goal" />
          <template v-else-if="sec.key === 'roles'">
            <RoleCard v-for="role in spec.current.roles" :key="role.code" :role="role" />
          </template>
          <template v-else-if="sec.key === 'objects'">
            <ObjectCard v-for="obj in spec.current.objects" :key="obj.code" :object="obj" />
          </template>
          <template v-else-if="sec.key === 'dicts'">
            <DictCard v-for="dict in spec.current.dicts" :key="dict.code" :dict="dict" />
          </template>
          <template v-else-if="sec.key === 'permissions'">
            <PermissionCard v-for="perm in spec.current.permissions" :key="perm.object_code" :permission="perm" />
          </template>
          <p v-else class="empty-section">暂无</p>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.spec-canvas {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
  background: var(--t-bg-base);
}
.empty-state {
  text-align: center;
  color: var(--t-text-muted);
  margin-top: 60px;
  font-size: 14px;
}
.canvas-section { margin-bottom: 24px; }
.section-header h3 {
  margin: 0 0 10px 0;
  font-size: 14px;
  color: var(--t-text-primary);
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.section-count {
  font-size: 12px;
  color: var(--t-text-muted);
  background: var(--t-bg-input);
  padding: 1px 8px;
  border-radius: 10px;
}
.section-body { display: flex; flex-direction: column; gap: 8px; }
.empty-section { color: var(--t-text-muted); font-size: 13px; padding: 8px 0; }
</style>
```

- [ ] **Step 4.5: Type-check + commit**

```bash
cd frontend && npx vue-tsc --noEmit 2>&1 | grep -E "spec/SpecCanvas|error TS" | head -10
cd "/Users/mars/Vibe Coding/apaas-builder-ai" && git add frontend/src/components/spec && git commit -m "$(cat <<'EOF'
feat(spec-ui): SpecCanvas + 5 卡片组件（confirm/dismiss）

GoalCard / RoleCard / ObjectCard / DictCard / PermissionCard 各一张
单元卡，confirm 直接调 PUT /api/spec/{id}/items；dismiss 走 ElMessageBox
二次确认。Goal 卡暂无手动 confirm 按钮（backend items 路由不映射 goal，
留 Phase γ 加 /items/goal 路由再补）。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: SpecInspector component

**Files:**
- Create: `frontend/src/components/spec/SpecInspector.vue`

- [ ] **Step 5.1: Implement Inspector**

```vue
<script setup lang="ts">
import { computed } from 'vue'
import { useSpecStore } from '@/stores/spec'

const spec = useSpecStore()

const completenessPct = computed(() => {
  const c = spec.completeness
  if (!c || c.total === 0) return 0
  return Math.round((c.confirmed / c.total) * 100)
})

const sections = computed(() => {
  const by = spec.completeness?.by_section ?? {}
  return Object.entries(by).map(([key, [confirmed, total]]) => ({
    key, label: sectionLabel(key), confirmed, total,
    pct: total === 0 ? 0 : Math.round((confirmed / total) * 100),
  }))
})

function sectionLabel(key: string): string {
  return ({
    goal: '业务目标', roles: '角色', objects: '数据对象',
    fields: '字段', dicts: '字典', permissions: '权限',
  } as Record<string, string>)[key] || key
}
</script>

<template>
  <aside class="spec-inspector" v-if="spec.current">
    <!-- 完成度 -->
    <section class="inspector-section">
      <h4 class="inspector-h">完成度</h4>
      <div class="completeness-ring">
        <span class="completeness-num">{{ spec.completeness?.confirmed ?? 0 }}/{{ spec.completeness?.total ?? 0 }}</span>
        <span class="completeness-pct">{{ completenessPct }}%</span>
      </div>
      <ul class="completeness-by-section">
        <li v-for="s in sections" :key="s.key">
          <span class="sec-label">{{ s.label }}</span>
          <span class="sec-progress">{{ s.confirmed }}/{{ s.total }}</span>
          <div class="sec-bar"><div class="sec-bar-fill" :style="{ width: s.pct + '%' }"></div></div>
        </li>
      </ul>
    </section>

    <!-- 待决策 -->
    <section class="inspector-section">
      <h4 class="inspector-h">待决策 <span class="inspector-count">{{ spec.pendingDecisions.length }}</span></h4>
      <ul class="decisions-list">
        <li v-for="d in spec.pendingDecisions" :key="d.id" class="decision-item" :class="{ blocking: d.blocking }">
          <header>
            <span class="decision-topic">{{ d.topic }}</span>
            <span v-if="d.blocking" class="blocking-tag">阻塞</span>
          </header>
          <p v-if="d.why_blocking" class="decision-why">{{ d.why_blocking }}</p>
          <ol v-if="d.options.length" class="decision-options">
            <li v-for="(opt, i) in d.options" :key="i">{{ opt }}</li>
          </ol>
        </li>
      </ul>
      <p v-if="spec.pendingDecisions.length === 0" class="empty-text">所有决策已解决</p>
    </section>

    <!-- 版本时间线（Phase β 占位，γ 实现 fork 后填充） -->
    <section class="inspector-section">
      <h4 class="inspector-h">版本</h4>
      <p class="version-current">v{{ spec.current?.version ?? 1 }}</p>
      <p v-if="spec.current?.parent_spec_id" class="version-parent">基于 {{ spec.current.parent_spec_id }}</p>
    </section>
  </aside>
</template>

<style scoped>
.spec-inspector {
  width: 280px;
  flex-shrink: 0;
  border-left: 1px solid var(--t-border-subtle);
  padding: 16px 14px;
  background: var(--t-bg-panel);
  overflow-y: auto;
  font-size: 13px;
}
.inspector-section { margin-bottom: 24px; }
.inspector-h { margin: 0 0 8px 0; font-size: 13px; color: var(--t-text-primary); display: flex; align-items: center; gap: 6px; }
.inspector-count { background: var(--t-bg-input); color: var(--t-text-secondary); padding: 1px 7px; border-radius: 10px; font-size: 11px; }
.completeness-ring { display: flex; align-items: baseline; gap: 8px; padding: 8px 0; }
.completeness-num { font-size: 22px; font-weight: 700; color: var(--t-brand); font-family: monospace; }
.completeness-pct { font-size: 14px; color: var(--t-text-secondary); }
.completeness-by-section { list-style: none; padding: 0; margin: 0; }
.completeness-by-section li { display: grid; grid-template-columns: 80px 50px 1fr; align-items: center; gap: 6px; padding: 4px 0; font-size: 12px; }
.sec-label { color: var(--t-text-secondary); }
.sec-progress { font-family: monospace; color: var(--t-text-primary); text-align: right; }
.sec-bar { height: 4px; background: var(--t-bg-input); border-radius: 2px; overflow: hidden; }
.sec-bar-fill { height: 100%; background: var(--t-brand); transition: width 0.3s; }

.decisions-list { list-style: none; padding: 0; margin: 0; }
.decision-item { padding: 8px 10px; margin-bottom: 6px; background: var(--t-bg-input); border-radius: var(--t-radius-sm); border-left: 3px solid var(--t-text-muted); }
.decision-item.blocking { border-left-color: var(--t-warning); background: var(--t-warning-subtle); }
.decision-item header { display: flex; align-items: center; gap: 6px; }
.decision-topic { font-weight: 500; color: var(--t-text-primary); }
.blocking-tag { background: var(--t-warning); color: white; font-size: 10px; padding: 1px 5px; border-radius: 3px; }
.decision-why { margin: 4px 0; font-size: 12px; color: var(--t-text-secondary); }
.decision-options { margin: 4px 0 0 18px; padding: 0; font-size: 12px; color: var(--t-text-secondary); }
.decision-options li { margin-bottom: 2px; }

.empty-text { color: var(--t-text-muted); font-size: 12px; }
.version-current { font-family: monospace; font-size: 14px; color: var(--t-text-primary); margin: 0; }
.version-parent { font-size: 11px; color: var(--t-text-muted); margin: 4px 0 0; }

@media (max-width: 1280px) {
  .spec-inspector { display: none; }  /* hide on small screens; Phase γ adds drawer toggle */
}
</style>
```

- [ ] **Step 5.2: Type-check + commit**

```bash
cd frontend && npx vue-tsc --noEmit 2>&1 | grep -E "SpecInspector|error TS" | head -10
cd "/Users/mars/Vibe Coding/apaas-builder-ai" && git add frontend/src/components/spec/SpecInspector.vue && git commit -m "$(cat <<'EOF'
feat(spec-ui): SpecInspector（completeness + 待决策 + 版本）

3 段：完成度 (n/total + by_section 进度条) / 待决策列表 (blocking 标签
+ why + options) / 版本号。<1280px 屏幕暂时隐藏 inspector，Phase γ
加抽屉切换。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: ChatPage three-pane integration + SSE wiring

**Files:**
- Modify: `frontend/src/views/ChatPage.vue` (large file — surgical edits only)

This is the biggest task in Phase β. ChatPage.vue is ~11.7k lines. Plan strictly:

- [ ] **Step 6.1: Add imports + store hookup**

In `frontend/src/views/ChatPage.vue`, after existing imports (around line 1-100), add:

```ts
import { useSpecStore } from '@/stores/spec'
import PhaseBar from '@/components/spec/PhaseBar.vue'
import SpecCanvas from '@/components/spec/SpecCanvas.vue'
import SpecInspector from '@/components/spec/SpecInspector.vue'
```

After existing `const store = useStore()` or similar (find it via grep — likely around line 1700), add:

```ts
const specStore = useSpecStore()

const useSpecMode = computed(() =>
  currentAgent.value === 'requirements' && !!conversation.value?.spec_id
)
```

Where `conversation.value` is whatever variable holds the loaded conversation in ChatPage. Verify by grepping `conversation.spec_id` and `currentAgent`.

- [ ] **Step 6.2: Auto-create spec for new requirements conversations**

Find the `ensureFreshRequirementsConversation` function (around line 6820 — the function that creates a new requirements conversation when user starts fresh). Modify it to:

1. After `const data = await conversationApi.create({ agent_type: 'requirements', ... })`,
2. Add: create a spec, then update conversation to link.

```ts
// After conversationApi.create() returns successfully:
const newSpecId = await specStore.create(null)  // null = no app yet
// Re-create conversation WITH spec_id (or PATCH it — depends on existing API surface)
// If conversationApi.create accepts spec_id (Task 9 of Phase α added this), pass it directly:
const data = await conversationApi.create({
  agent_type: 'requirements',
  spec_id: newSpecId,
  ...(initialMessage.trim() ? { initial_message: initialMessage.trim() } : {}),
  ...(selectedBuilderModelId.value != null ? { selected_llm_config_id: selectedBuilderModelId.value } : {}),
})
// Then load spec into store
await specStore.load(newSpecId)
```

Verify `conversationApi` matches the existing TypeScript types — may need to update `frontend/src/api/conversation.ts` to accept `spec_id` in the create body.

- [ ] **Step 6.3: Hook spec_patch SSE events to specStore.applyPatch**

Find the SSE event-handling block in `sendMessage` or similar (around line 5760-5825 — search for `normalizedType === 'progress'` and `normalizedType === 'done'`). Add a new handler **before** the existing `progress` handler:

```ts
if (currentEvent === 'spec_patch' || normalizedType === 'spec_patch') {
  if (parsed.data) {
    specStore.applyPatch(parsed.data)
  }
  continue
}
```

Make sure `currentEvent` and `parsed` are defined the same way as for other event handlers in this block.

- [ ] **Step 6.4: Three-pane layout in template**

Find the `builder-content` div (line 142). Add a sibling block that renders only when `useSpecMode === true`:

```vue
<div v-if="useSpecMode" class="spec-three-pane">
  <PhaseBar class="spec-three-pane-phasebar" />
  <div class="spec-three-pane-body">
    <!-- LEFT: Existing chat composer (re-use existing chat-side block) -->
    <div class="chat-side spec-chat-side">
      <!-- Reuse existing composer / message list components if extracted, or
           wrap the existing chat-side template content via v-if -->
      <slot name="composer" />
    </div>
    <!-- MIDDLE: SpecCanvas -->
    <SpecCanvas class="spec-canvas-pane" />
    <!-- RIGHT: SpecInspector -->
    <SpecInspector class="spec-inspector-pane" />
  </div>
</div>

<!-- Existing two-pane mode (when !useSpecMode) -->
<div v-show="!useSpecMode" class="builder-content">
  <!-- existing template -->
</div>
```

**Implementation note**: ChatPage.vue is highly entangled. The cleanest path is to **wrap** the existing `builder-content` in a conditional, and emit a new top-level `spec-three-pane` block above it. The composer (chat input + message list) needs to render in both modes — extract its template into a reusable `<template v-if>` block or a new `ChatComposer.vue` sub-component (recommended if ChatPage exceeds 12k lines after this work).

For Phase β, **the simplest viable**: keep two top-level branches, duplicate the composer template inside the new branch. Refactor to a shared sub-component is a follow-up.

- [ ] **Step 6.5: Add styles**

Append to ChatPage.vue's `<style scoped>` (near line 7495 where `.builder-content` lives):

```css
.spec-three-pane {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.spec-three-pane-phasebar {
  padding: 12px 16px;
  border-bottom: 1px solid var(--t-border-subtle);
  background: var(--t-bg-panel);
}
.spec-three-pane-body {
  display: flex;
  flex: 1;
  overflow: hidden;
}
.spec-chat-side { width: 380px; flex-shrink: 0; border-right: 1px solid var(--t-border-subtle); }
.spec-canvas-pane { flex: 1; overflow: hidden; }
.spec-inspector-pane { /* width comes from component */ }

@media (max-width: 1280px) {
  .spec-inspector-pane { display: none; }
}
```

- [ ] **Step 6.6: Type-check + dev-server smoke**

```bash
cd frontend && npx vue-tsc --noEmit 2>&1 | grep -E "ChatPage\.vue|error TS" | head -20
```
Expected: no new errors in ChatPage.vue.

Then start dev server (or refresh existing one) and visually verify in browser at `localhost:5173/ai-builder/chat` (new conversation → should see three-pane). Use Preview tool:

```
preview_start http://localhost:5173/ai-builder/
preview_snapshot
preview_screenshot
```

If three-pane doesn't render, debug via `preview_console_logs` and Vue DevTools.

- [ ] **Step 6.7: Commit**

```bash
cd "/Users/mars/Vibe Coding/apaas-builder-ai" && git add frontend/src/views/ChatPage.vue frontend/src/api/conversation.ts && git commit -m "$(cat <<'EOF'
feat(spec-ui): ChatPage 三栏布局 + SSE spec_patch 事件接入

新对话（agent_type=requirements）启动时自动创建 spec，conversation.spec_id
绑定。useSpecMode==true 时渲染三栏（左 Composer / 中 SpecCanvas / 右
SpecInspector）+ PhaseBar 在顶部。SSE spec_patch 事件直接写入 specStore。

旧两栏模式保持不动，老对话和非 requirements agent 不受影响。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Visual smoke + iteration

**Files:** none (uses Preview tool to verify, may iterate on Tasks 3-6 if visual issues found)

- [ ] **Step 7.1: Restart backend with Phase α code**

User's running backend on port 8000 has OLD code. Restart so it picks up SpecAgent + /api/spec routes:
```bash
# Find current backend PID and stop it
lsof -nP -i:8000 | grep LISTEN | awk '{print $2}' | xargs kill
# Restart
cd "/Users/mars/Vibe Coding/apaas-builder-ai/backend" && source venv/bin/activate && nohup python run.py > /tmp/backend.log 2>&1 &
sleep 4
curl -sS http://localhost:8000/openapi.json | python3 -c "import sys,json; d=json.load(sys.stdin); print('spec routes:', [p for p in d['paths'] if 'spec' in p])"
```
Expected: prints 4 spec routes.

- [ ] **Step 7.2: Frontend dev server**

```bash
lsof -nP -i:5173 | grep LISTEN  # check if running
# If not:
cd "/Users/mars/Vibe Coding/apaas-builder-ai/frontend" && nohup npm run dev > /tmp/frontend.log 2>&1 &
sleep 5
```

- [ ] **Step 7.3: Visual end-to-end via Preview tool**

```
mcp__Claude_Preview__preview_start url=http://localhost:5173/ai-builder/
mcp__Claude_Preview__preview_screenshot  # initial landing
```

Login as a test user. Navigate to a new chat (requirements agent). Type "我想做一个预算管理系统，根据老项目backlog+新商机转化进行季度收入预测".

Verify with screenshots:
1. Three-pane layout renders (PhaseBar top, Composer left, Canvas middle, Inspector right)
2. After AI responds, Inspector "待决策" list shows 3-5 questions
3. PhaseBar shows "理解需求" as active
4. Completeness shows 0/0
5. Click PhaseBar "SPEC 设计" — should fail with toast (blocking decisions)

Capture screenshots of each state and store in `/tmp/spec_phase_beta_smoke_*.png`.

- [ ] **Step 7.4: Resolve a decision via chat, verify cascade**

Send a follow-up: "整体公司层面，每月滚动更新". The LLM should call `resolve_decision` and `set_goal` and `add_role`. Verify:
- New cards appear in SpecCanvas (Goal, Roles)
- Inspector decisions count drops
- Completeness updates (e.g., 0/3 → 0/5 if 5 unconfirmed items added)

Click "✓ 确认" on a Role card. Verify:
- Role card flips to confirmed (green border)
- Inspector roles section shows (1/5) progress

- [ ] **Step 7.5: If anything broken, fix in-place + commit each fix separately**

Common issues to anticipate:
- Pinia store not initialized → wrap `useSpecStore()` calls in `setup()` (already done)
- `conversation.spec_id` undefined for old conversations → useSpecMode falls back to false, two-pane renders (intended)
- Axios baseURL missing `/api` prefix → check `request.ts` config; existing api/*.ts work today, so spec.ts should too if same pattern
- ElMessage not styled → ensure Element Plus is globally registered (it already is, used elsewhere in ChatPage)

For each fix, single commit:
```bash
cd "/Users/mars/Vibe Coding/apaas-builder-ai" && git commit -am "fix(spec-ui): <one-line description>"
```

- [ ] **Step 7.6: Final visual capture for the user**

Take 4 screenshots:
1. Empty three-pane (just opened)
2. After first user message + AI clarifying questions
3. After first card confirmed
4. PhaseBar transition attempt blocked by decisions

Save to `/tmp/spec_phase_beta_visual.png` (combine into single image if possible) and reference in final report.

---

## Self-Review Checklist (run before declaring Phase β complete)

- [ ] `cd frontend && npx vue-tsc --noEmit` shows no new errors
- [ ] `cd backend && pytest tests/ -v` still shows 34 passed (no backend regression — Phase β didn't touch backend)
- [ ] Browser smoke: new requirements conversation → three-pane appears, AI asks ≥3 questions, Inspector reflects them
- [ ] Click PhaseBar with blocking decisions → toast warning shows, no transition
- [ ] Click ✓ confirm on a role/object card → card flips green, Inspector updates
- [ ] Click ✕ dismiss on a role card → confirmation dialog → role removed
- [ ] Old conversations (spec_id IS NULL) still render in two-pane mode
- [ ] Each commit references task number, builds clean

---

## What's NOT in this plan (deferred to Phase γ or later)

- **Edit modal** for cards (currently only confirm/dismiss; edit by re-issuing chat message)
- **Goal confirmation** REST surface (`/items/goal/_singleton`)
- **Drawer Inspector** for `<1280px` (currently hidden)
- **Decision option click** that auto-sends "选 [option]" as user message (currently user types it manually)
- **Version timeline visual** (just shows v{N} text; full timeline uses `parent_spec_id` chain — Phase γ when fork is implemented)
- **Existing PreviewPanel as "技术视图" tab** (kept side-by-side via mode switch — Phase γ if needed)
- **Coding handoff** (when phase=ready, transition to coding view)
- **Bootstrap from doc UX** (entries 2/3/6 — Phase γ)
- **Backend security follow-ups** (concurrency lock I2 / final event contract I4 from Phase α review)
