# aPaaS Platform Admin Binding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有平台管理页增加 aPaaS 平台管理员账号绑定能力，并用试用环境完成登录和租户同步。

**Architecture:** 复用现有 `/api/mcp-platform/apaas-admins` CRUD、登录与租户同步接口，不新增后端模型或认证接口。管理端在 `PlatformTenants.vue` 内增加一个紧凑的账号管理区；本地后端通过 `APAAS_BASE_URL` 指向试用环境。

**Tech Stack:** Vue 3、Element Plus、Axios、FastAPI、Vitest、Playwright

---

### Task 1: 锁定管理端绑定行为

**Files:**
- Create: `frontend/src/views/platformAdminBindings.spec.ts`
- Read: `admin-spa/src/views/PlatformTenants.vue`

- [ ] **Step 1: 写失败测试**

创建源码级回归测试，要求管理端包含现有账号 CRUD 和登录接口，且刷新按钮在没有管理员账号时禁用：

```ts
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const source = readFileSync(
  resolve(process.cwd(), '../admin-spa/src/views/PlatformTenants.vue'),
  'utf8',
)

describe('aPaaS platform admin bindings', () => {
  it('supports account create, update, delete and login', () => {
    expect(source).toContain("apiPost<AdminRow>('/mcp-platform/apaas-admins'")
    expect(source).toContain('apiPut(`/mcp-platform/apaas-admins/${editingAdminId.value}`')
    expect(source).toContain('apiDel(`/mcp-platform/apaas-admins/${row.id}`')
    expect(source).toContain('apiPost(`/mcp-platform/apaas-admins/${row.id}/login`)')
  })

  it('does not allow tenant refresh without an admin account', () => {
    expect(source).toContain(':disabled="!selectedAdminId"')
  })
})
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
npm test -- src/views/platformAdminBindings.spec.ts
```

Expected: FAIL，因为当前 `PlatformTenants.vue` 只有管理员列表读取和租户刷新。

### Task 2: 增加平台管理员账号管理区

**Files:**
- Modify: `admin-spa/src/views/PlatformTenants.vue`
- Test: `frontend/src/views/platformAdminBindings.spec.ts`

- [ ] **Step 1: 扩展 API 导入和管理员类型**

把 API 导入改为：

```ts
import { apiDel, apiGet, apiPost, apiPut } from '@/api/client'
```

扩展管理员展示类型：

```ts
interface AdminRow {
  id: string
  name: string
  account: string
  is_default: boolean
  status: string
  last_login_at?: string | null
}
```

- [ ] **Step 2: 增加账号管理状态和表单**

在现有租户状态旁增加：

```ts
const adminDialogVisible = ref(false)
const adminSaving = ref(false)
const editingAdminId = ref('')
const adminForm = ref({
  name: '',
  account: '',
  password: '',
  is_default: false,
})
```

新增打开、保存、登录、设默认和删除方法。新增时先调用 `POST /mcp-platform/apaas-admins`，随后调用返回账号的 `/login`；编辑时密码留空不发送 `password`。

- [ ] **Step 3: 增加紧凑账号管理区**

在租户列表前增加一个 `el-card`：

- 表格展示名称、账号、状态、默认标记、最近登录时间。
- 操作按钮：登录、编辑、设为默认、删除。
- “新增账号”按钮打开对话框。
- 对话框字段：名称、账号、密码、默认账号。
- 不渲染 Token、密码密文或 Token 指纹。

把租户刷新按钮调整为：

```vue
<el-button
  type="primary"
  :loading="loading"
  :disabled="!selectedAdminId"
  @click="syncTenants()"
>
  刷新租户
</el-button>
```

- [ ] **Step 4: 运行测试**

Run:

```bash
npm test -- src/views/platformAdminBindings.spec.ts
```

Expected: PASS。

- [ ] **Step 5: 构建管理端**

Run:

```bash
npm run build
```

Working directory: `admin-spa`

Expected: `vue-tsc` 和 Vite build 均成功。

### Task 3: 配置本地试用环境并验证

**Files:**
- Runtime configuration only: no credential file committed

- [ ] **Step 1: 重启本地后端**

在现有本地启动参数上增加：

```bash
APAAS_BASE_URL=https://apaas-trial.definesys.cn/backend
```

账号密码不写入环境变量，由页面录入并加密存入当前本地数据库。

- [ ] **Step 2: 验证配置已加载**

登录 Builder 后请求平台管理员接口，确认后端可创建管理员账号；不得在输出中打印密码或 Token。

- [ ] **Step 3: 浏览器验证**

用 Playwright 打开：

```text
http://localhost:5174/platform-admin/tenants
```

确认：

- 平台管理员账号区可见。
- 新增账号对话框可打开。
- 没有管理员账号时“刷新租户”禁用。
- 页面无白色加载遮罩。
- 浏览器控制台无运行时错误。

- [ ] **Step 4: 最终检查**

Run:

```bash
git diff --check
git status --short
```

仅保留本任务可归属文件，不提交账号、密码、Token 或本地数据库。
