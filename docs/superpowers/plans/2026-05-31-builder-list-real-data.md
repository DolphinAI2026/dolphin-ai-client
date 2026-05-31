# Builder 列表真实数据化 (P1–P3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让「列表设计」预览显示真实业务数据；无数据时显诚实空态(非假行)；行「查看」开 detail 抽屉；行「编辑」深链真应用。

**Architecture:** 纯前端改 `ListDesignerPanel.vue` 一个文件 + 复用已有后端端点 (`business-data` 已接、`apaas-access-url` 已存在)。删除 mock 兜底让既有空态浮现；新增 el-drawer 复用已拉行数据；编辑按钮调 `apaas-access-url` 开真应用。

**Tech Stack:** Vue 3 (`<script setup>` + 选项式渲染混用) / Element Plus (el-drawer) / TypeScript / vite。**无前端测试框架** — 验证用 `vue-tsc -b`(对比基线 405 无新增) + 浏览器 HMR 实测。

**范围说明:** 本计划覆盖 spec 的 P1–P3。**P4(权限矩阵真读)** 是独立后端 MCP 子系统(改 `mcp_server.py:get_role_resource_matrix` + pytest), 按"一子系统一计划"原则单独出计划, 不在本文件。

---

## File Structure

- Modify: `frontend/src/components/v3/ListDesignerPanel.vue` — 唯一改动文件
  - 删 `genMockRows`/`MOCK_NAMES`/`MOCK_BOOKS` (死代码) 及 `loadBusinessData` 的 mock 兜底
  - `dataSource` 类型 `'real'|'mock'` → `'real'|'empty'|'error'`
  - 模板空态块加「打开应用录入」CTA + 删 `mock 数据` tag
  - 新增 `el-drawer` 行详情 + `onRowView`/`onRowEdit` 真实现 + `openApaasApp()` 复用函数

无新建文件 (drawer 内联, 复用现有 `renderCell`/`visibleColumns`, 避免 prop 钻取)。

---

## Phase P1 — 列表 0 条显空态 (删 mock 兜底)

### Task 1: loadBusinessData 去 mock 兜底

**Files:**
- Modify: `frontend/src/components/v3/ListDesignerPanel.vue` (`loadBusinessData` ~696-721, `dataSource` ref ~313)

- [ ] **Step 1: 改 dataSource 类型 + 默认值**

`dataSource` ref (当前 `const dataSource = ref<'real' | 'mock'>('mock')`, ~line 313) 改为:

```ts
const dataSource = ref<'real' | 'empty' | 'error'>('empty')
```

- [ ] **Step 2: 重写 loadBusinessData — 0 条/失败不再造假行**

把 `loadBusinessData` (~696-721) 整体替换为:

```ts
async function loadBusinessData(): Promise<void> {
  // 真业务数据需要 form_id + 应用已部署
  if (!props.formId || !previewColumns.value.length) {
    allRows.value = []
    totalRows.value = 0
    dataSource.value = 'empty'
    return
  }
  try {
    const resp = await request.get<any, any>(
      `/applications/${props.appId}/forms/${props.formId}/business-data?page=1&page_size=50`,
    )
    if (resp?.ok && Array.isArray(resp.items)) {
      allRows.value = resp.items
      totalRows.value = resp.total || resp.items.length
      dataSource.value = resp.items.length > 0 ? 'real' : 'empty'
      return
    }
    // ok=false (未部署等) → 空态, 不编造
    allRows.value = []
    totalRows.value = 0
    dataSource.value = 'empty'
  } catch (_e) {
    allRows.value = []
    totalRows.value = 0
    dataSource.value = 'error'
  }
}
```

- [ ] **Step 3: 删死代码 genMockRows + MOCK 常量**

删除 `MOCK_NAMES` (~416)、`MOCK_BOOKS` (~417)、`genMockRows` 整个函数 (~424-454)。**保留** `STATUS_OPTIONS` (renderCell/filter 仍用)。

- [ ] **Step 4: 类型检查**

Run: `cd frontend && VITE_BASE_URL=/ai-builder/ npx vue-tsc -b 2>&1 | grep -c "error TS"`
Expected: `405` (= 基线, 无新增)。若 >405, 看是否漏了 `genMockRows` 的引用 — grep 确认无残留: `grep -n "genMockRows\|MOCK_NAMES\|MOCK_BOOKS" frontend/src/components/v3/ListDesignerPanel.vue` → 空。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/v3/ListDesignerPanel.vue
git commit -m "feat(list): 列表 0 条显空态而非 mock 假行 (删 genMockRows 兜底)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 2: 删 mock tag + 空态加「打开应用录入」CTA

**Files:**
- Modify: `frontend/src/components/v3/ListDesignerPanel.vue` (模板 banner ~95, 空态块 ~153-167)

- [ ] **Step 1: 删 banner 里的 mock 数据 tag**

删除 ~line 95 整行:
```html
<span v-if="dataSource === 'mock'" class="ldp-pv-mock-tag" title="未拉到真实业务数据, 显示 mock 示例">mock 数据</span>
```

- [ ] **Step 2: 空态块「已配置但无数据」分支加 CTA**

模板里 `<template v-else>` 空态分支 (~161-166), 把 `暂无业务数据` 那段改为带 CTA:

```html
<template v-else>
  <p v-if="!visibleColumns.length">该列表尚未配置可显字段</p>
  <p v-else-if="hasActiveFilter">无匹配筛选条件的数据</p>
  <p v-else>暂无业务数据</p>
  <p class="hint" v-if="visibleColumns.length && !hasActiveFilter">数据由最终用户在前台录入</p>
  <button
    v-if="visibleColumns.length && !hasActiveFilter"
    class="ldp-btn ldp-btn-primary ldp-btn-sm"
    style="margin-top:12px"
    @click="openApaasApp()"
  >打开应用录入数据</button>
</template>
```

(`openApaasApp` 在 P3 Task 4 定义；本步先放按钮, P3 接好行为。若先跑 P1 单独验证, 临时 `@click` 可指向 `() => {}`。)

- [ ] **Step 3: 类型检查 + 浏览器实测**

Run: `cd frontend && VITE_BASE_URL=/ai-builder/ npx vue-tsc -b 2>&1 | grep -c "error TS"` → `405`。
浏览器(HMR): 列表设计 tab 打开 SRM供应商档案管理(0 条) → 应显空态"暂无业务数据"(非假行), mock tag 消失。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/v3/ListDesignerPanel.vue
git commit -m "feat(list): 删 mock tag + 空态加打开应用 CTA

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Phase P2 — 行「查看」detail 抽屉

### Task 3: el-drawer 行详情 (复用已拉行数据)

**Files:**
- Modify: `frontend/src/components/v3/ListDesignerPanel.vue` (state, `onRowView`/`onRowClick` ~500-510, 模板末尾加 drawer)

- [ ] **Step 1: 加抽屉 state**

`<script setup>` 里 (靠近其他 ref) 新增:

```ts
const detailVisible = ref(false)
const detailRow = ref<Record<string, any> | null>(null)
```

确认顶部 import 有 `ref` (已有)。Element Plus `el-drawer` 全局注册 (项目已全局引 Element Plus) — 若非全局, 在 import 区加 `import { ElDrawer } from 'element-plus'`。

- [ ] **Step 2: onRowView / onRowClick 打开抽屉 (替换 alert)**

把 `onRowClick` (~500-506) 和 `onRowView` (~508-510) 替换为:

```ts
function onRowClick(row: Record<string, any>, _i: number) {
  detailRow.value = row
  detailVisible.value = true
}

function onRowView(row: Record<string, any>) {
  onRowClick(row, 0)
}
```

(删掉原 `onRowClick` 里的 `alert(...)` summary 逻辑。)

- [ ] **Step 3: 模板加 el-drawer (放 `.ldp-pv` 容器末尾, 分页之后)**

```html
<el-drawer
  v-model="detailVisible"
  title="数据详情"
  direction="rtl"
  size="420px"
>
  <div v-if="detailRow" class="ldp-detail">
    <div v-for="c in visibleColumns" :key="c.code" class="ldp-detail-row">
      <span class="ldp-detail-label">{{ c.label }}</span>
      <span class="ldp-detail-value">{{ renderCell(detailRow, c) }}</span>
    </div>
  </div>
</el-drawer>
```

- [ ] **Step 4: 加 detail 样式 (scoped `<style>` 末尾)**

```css
.ldp-detail { display: flex; flex-direction: column; }
.ldp-detail-row {
  display: flex; gap: 12px; padding: 10px 4px;
  border-bottom: 1px solid var(--line); font-size: 13px;
}
.ldp-detail-label { flex: 0 0 120px; color: var(--text-3); }
.ldp-detail-value { flex: 1; color: var(--text); word-break: break-all; }
```

- [ ] **Step 5: 类型检查 + 浏览器实测**

Run: `cd frontend && VITE_BASE_URL=/ai-builder/ npx vue-tsc -b 2>&1 | grep -c "error TS"` → `405`。
浏览器: 找一个有数据的表单(或先用有 mock 历史的) → 点行「查看」→ 右侧抽屉显该行全字段 label:value; 空值显 `—`。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/v3/ListDesignerPanel.vue
git commit -m "feat(list): 行查看打开 detail 抽屉 (复用已拉行数据)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Phase P3 — 行「编辑」深链真应用

### Task 4: openApaasApp() 复用函数 + onRowEdit 接入

**Files:**
- Modify: `frontend/src/components/v3/ListDesignerPanel.vue` (`onRowEdit` ~512-514, 新增 `openApaasApp`)

- [ ] **Step 1: 新增 openApaasApp 复用函数**

`<script setup>` 里新增 (P1 Task 2 的 CTA 和本任务的编辑都用它):

```ts
async function openApaasApp() {
  try {
    const resp = await request.get<any, any>(
      `/applications/${props.appId}/apaas-access-url`,
    )
    if (resp?.ok && resp.access_url) {
      window.open(resp.access_url, '_blank')
    } else {
      alert(resp?.message || '应用尚未部署到 aPaaS, 无法打开')
    }
  } catch (e: any) {
    alert(`打开应用失败: ${e?.message || '网络错误'}`)
  }
}
```

- [ ] **Step 2: onRowEdit 改为打开真应用**

把 `onRowEdit` (~512-514) 替换为:

```ts
function onRowEdit(_row: Record<string, any>) {
  // v1: 打开应用级运行态 URL (记录级深链留后续)
  openApaasApp()
}
```

- [ ] **Step 3: 类型检查 + 浏览器实测**

Run: `cd frontend && VITE_BASE_URL=/ai-builder/ npx vue-tsc -b 2>&1 | grep -c "error TS"` → `405`。
浏览器: 点行「编辑」→ 新标签打开真应用 access_url; 空态「打开应用录入」CTA 同样打开。未部署应用 → 弹友好提示(非静默)。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/v3/ListDesignerPanel.vue
git commit -m "feat(list): 行编辑/空态CTA 深链 apaas 真应用 (apaas-access-url)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

- **Spec 覆盖:** P1(空态去 mock)=Task1+2 ✓; P2(查看抽屉)=Task3 ✓; P3(编辑深链)=Task4 ✓; 空态 CTA(决策2)=Task2+4 ✓; P4 明确移交独立计划 ✓。
- **占位扫描:** 无 TBD/TODO; 每个 code-step 给了完整代码。Task2 的 CTA 依赖 Task4 的 `openApaasApp` — 已注明顺序/临时桩。
- **类型一致:** `dataSource: 'real'|'empty'|'error'`(Task1) 全程一致; `openApaasApp`(Task4) 被 Task2 CTA + Task4 onRowEdit 共用, 签名一致; `detailRow`/`detailVisible`(Task3) 命名一致。
- **风险:** `el-drawer` 若非全局注册需显式 import(Task3 Step1 已注明); 共享分支路径限定提交。
