# 桌面端工作台入口范围 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为桌面端增加必须显式选择的 `aPaaS / AI平台` 工作台入口范围，并将中文安装器和 Windows SQLite 路径修复一起交付到 `0.2.39` 单 EXE 安装包。

**Architecture:** Tauri/Rust 的 `<根目录>/.appdata/desktop-config.json` 是入口范围事实源，旧配置缺字段时仅为升级兼容读取为 `both`。前端通过现有桌面 invoke 门面读取和更新配置，顶部导航、路由守卫、首次初始化和桌面设置消费同一枚举；入口范围更新不重启 Runtime 或 sidecar。

**Tech Stack:** Rust、Tauri 2、Vue 3、TypeScript、Pinia、Element Plus、Vitest、PyInstaller、NSIS、PowerShell。

## Global Constraints

- 顶部桌面名称固定为 `aPaaS` 和 `AI平台`；Web 端继续使用现有 `Builder / Code`。
- 新安装首次初始化不预选入口范围，用户必须明确选择。
- 旧配置缺少 `workspace_entry_scope` 时读取为 `both`，不阻塞升级启动。
- 入口范围更新不得退出账号、重启 sidecar 或重启 Runtime。
- 单入口仍显示一个顶部 Tab；访问被隐藏入口时跳转到可用入口首页。
- 不新增分散测试文件；只保留锁定真实故障或纯函数合同的最小回归测试。
- UI 接线不增加 raw-source/字符串存在性断言，使用 TypeScript 检查和桌面构建验证。
- Windows 交付物固定为 `ruijing-0.2.39-windows-x86_64-setup.exe`，且只交付一个安装 EXE。

---

### Task 1: 扩展 Tauri 桌面配置合同

**Files:**
- Modify: `src-tauri/src/desktop_config.rs`
- Modify: `src-tauri/src/desktop_backend.rs`
- Modify: `src-tauri/src/lib.rs`

**Interfaces:**
- Produces: `WorkspaceEntryScope::{Apaas, AiPlatform, Both}`。
- Produces: `DesktopConfig.workspace_entry_scope: WorkspaceEntryScope`。
- Produces: `DesktopSetupInput.workspace_entry_scope: WorkspaceEntryScope`。
- Produces: Tauri command `desktop_update_workspace_entry_scope(scope) -> DesktopStateSnapshot`。

- [ ] **Step 1: 在现有 Rust 内联测试中写失败用例**

在 `desktop_config.rs` 现有测试模块增加：

```rust
#[test]
fn legacy_config_without_workspace_scope_defaults_to_both() {
    let raw = r#"{
        "schema_version": 1,
        "root_dir": "/tmp/DolphinCode",
        "login": {"mode": "control_plane", "base_url": "https://example.com"}
    }"#;
    let config: DesktopConfig = serde_json::from_str(raw).unwrap();
    assert_eq!(config.workspace_entry_scope, WorkspaceEntryScope::Both);
}

#[test]
fn setup_persists_explicit_workspace_scope() {
    let temp = unique_test_dir("workspace-scope");
    let store = DesktopConfigStore::new(temp.join("system"));
    store.save(DesktopSetupInput {
        root_dir: temp.join("DolphinCode").to_string_lossy().into_owned(),
        login: DesktopLoginConfig {
            mode: DesktopLoginMode::ControlPlane,
            base_url: CONTROL_PLANE_DEFAULT_URL.to_string(),
        },
        workspace_entry_scope: WorkspaceEntryScope::AiPlatform,
    }).unwrap();
    let loaded = store.load().unwrap().unwrap();
    assert_eq!(loaded.config.workspace_entry_scope, WorkspaceEntryScope::AiPlatform);
    fs::remove_dir_all(temp).unwrap();
}
```

在 `desktop_backend.rs` 现有测试模块增加：

```rust
#[test]
fn workspace_scope_update_input_preserves_login_and_root() {
    let config = fixture_config(DesktopLoginMode::Apaas);
    let input = workspace_scope_update_input(&config, WorkspaceEntryScope::Apaas);
    assert_eq!(PathBuf::from(input.root_dir), config.root_dir);
    assert_eq!(input.login, config.login);
    assert_eq!(input.workspace_entry_scope, WorkspaceEntryScope::Apaas);
}
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
cd src-tauri
cargo test desktop_config --lib
cargo test workspace_scope --lib
```

Expected: 因 `WorkspaceEntryScope` 和新字段/命令尚不存在而失败。

- [ ] **Step 3: 实现配置枚举和旧配置兼容**

在 `desktop_config.rs` 增加：

```rust
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum WorkspaceEntryScope {
    Apaas,
    AiPlatform,
    Both,
}

fn default_workspace_entry_scope() -> WorkspaceEntryScope {
    WorkspaceEntryScope::Both
}
```

`DesktopConfig` 使用反序列化兼容默认值，`DesktopSetupInput` 保持必填：

```rust
pub struct DesktopConfig {
    pub schema_version: u32,
    pub root_dir: PathBuf,
    pub login: DesktopLoginConfig,
    #[serde(default = "default_workspace_entry_scope")]
    pub workspace_entry_scope: WorkspaceEntryScope,
}

pub struct DesktopSetupInput {
    pub root_dir: String,
    pub login: DesktopLoginConfig,
    pub workspace_entry_scope: WorkspaceEntryScope,
}
```

`DesktopConfigStore::save` 将输入值写入配置。所有现有 `DesktopSetupInput` 和
`DesktopConfig` 构造位置显式补齐字段；登录服务更新必须复制当前
`workspace_entry_scope`，不能改回 `both`。

- [ ] **Step 4: 实现不重启进程的独立更新命令**

在 `desktop_backend.rs` 增加纯函数
`workspace_scope_update_input(config: &DesktopConfig, scope: WorkspaceEntryScope) -> DesktopSetupInput`
和同步更新方法。更新方法读取当前 config，调用 `config_store.save` 保存纯函数返回的同一
`root_dir/login` 和新 scope，成功后只替换内存中的 `inner.config` 并返回 snapshot。不得调用
`queue_update_login`、`run_full_start`、`spawn_sidecar` 或导航 packaged URL。

```rust
#[tauri::command]
pub fn desktop_update_workspace_entry_scope(
    state: tauri::State<'_, DesktopBackend>,
    scope: WorkspaceEntryScope,
) -> Result<DesktopStateSnapshot, DesktopBackendError> {
    state.update_workspace_entry_scope(scope)
}
```

在 `src-tauri/src/lib.rs` 的 `generate_handler!` 注册该命令。

- [ ] **Step 5: 运行 Rust 测试并提交**

Run:

```bash
cd src-tauri
cargo test desktop_config --lib
cargo test desktop_backend --lib
```

Expected: PASS。

Commit:

```bash
git add src-tauri/src/desktop_config.rs src-tauri/src/desktop_backend.rs src-tauri/src/lib.rs
git commit -m "feat(desktop): persist workspace entry scope"
```

---

### Task 2: 增加前端共享类型、入口筛选和路由约束

**Files:**
- Modify: `frontend/src/utils/desktop/setup.ts`
- Modify: `frontend/src/stores/mode.ts`
- Modify: `frontend/src/stores/mode.spec.ts`
- Modify: `frontend/src/router/desktopGuard.ts`
- Modify: `frontend/src/router/desktopGuard.spec.ts`
- Modify: `frontend/src/router/index.ts`

**Interfaces:**
- Consumes: Rust `workspace_entry_scope` 和 `desktop_update_workspace_entry_scope`。
- Produces: `DesktopWorkspaceEntryScope = 'apaas' | 'ai_platform' | 'both'`。
- Produces: `visibleModesForDesktopScope(scope): AppMode[]`。
- Produces: `desktopModeLabel(mode): 'aPaaS' | 'AI平台'`。
- Produces: `resolveDesktopWorkspaceRedirect(scope, targetPath): string | null`。

- [ ] **Step 1: 在既有前端测试中写失败用例**

在 `mode.spec.ts` 增加：

```ts
expect(visibleModesForDesktopScope('apaas')).toEqual(['builder'])
expect(visibleModesForDesktopScope('ai_platform')).toEqual(['code'])
expect(visibleModesForDesktopScope('both')).toEqual(['builder', 'code'])
expect(desktopModeLabel('builder')).toBe('aPaaS')
expect(desktopModeLabel('code')).toBe('AI平台')
```

在 `desktopGuard.spec.ts` 增加：

```ts
expect(resolveDesktopWorkspaceRedirect('apaas', '/code/apps')).toBe('/')
expect(resolveDesktopWorkspaceRedirect('ai_platform', '/apps')).toBe('/code/apps')
expect(resolveDesktopWorkspaceRedirect('ai_platform', '/login')).toBeNull()
expect(resolveDesktopWorkspaceRedirect('ai_platform', '/desktop-settings')).toBeNull()
expect(resolveDesktopWorkspaceRedirect('both', '/apps')).toBeNull()
```

并更新 `buildDesktopSetupInput` 断言，要求第四个参数显式写入
`workspace_entry_scope`。

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
cd frontend
npm run test -- src/stores/mode.spec.ts src/router/desktopGuard.spec.ts
```

Expected: 因新类型、helper 和字段尚不存在而失败。

- [ ] **Step 3: 实现共享桌面配置门面**

在 `setup.ts` 增加：

```ts
export type DesktopWorkspaceEntryScope = 'apaas' | 'ai_platform' | 'both'

export const DESKTOP_WORKSPACE_ENTRY_OPTIONS = [
  { value: 'apaas', label: '仅 aPaaS' },
  { value: 'ai_platform', label: '仅 AI平台' },
  { value: 'both', label: '两者都有' },
] as const
```

扩展 `DesktopConfig`、`DesktopSetupInput` 和 `buildDesktopSetupInput`。增加：

```ts
export function updateDesktopWorkspaceEntryScope(
  scope: DesktopWorkspaceEntryScope,
): Promise<DesktopStateSnapshot> {
  return invokeDesktop('desktop_update_workspace_entry_scope', { scope })
}
```

`getDesktopState`、`saveDesktopSetup`、`updateDesktopLogin` 和新更新函数返回时更新模块级
`DesktopStateSnapshot` 缓存；路由只消费由这些 native invoke 填充的缓存，不写
`localStorage`。

- [ ] **Step 4: 实现模式筛选和桌面路由 helper**

在 `mode.ts` 保持 `MODE_META` 和 `MODE_ORDER` 的 Web 名称不变，新增纯函数：

```ts
export function visibleModesForDesktopScope(scope: DesktopWorkspaceEntryScope): AppMode[] {
  if (scope === 'apaas') return ['builder']
  if (scope === 'ai_platform') return ['code']
  return ['builder', 'code']
}

export function desktopModeLabel(mode: AppMode): string {
  return mode === 'code' ? 'AI平台' : 'aPaaS'
}
```

在 `desktopGuard.ts` 增加受豁免路由集合：`/desktop-setup`、`/login`、
`/desktop-settings`、`/desktop-unavailable`。非豁免路由按 scope 跳转，避免重定向环。

`router/index.ts` 在桌面 bootstrap decision 后，从同一 native snapshot/cache 调用
`resolveDesktopWorkspaceRedirect`；Web 分支不执行。

- [ ] **Step 5: 运行前端测试并提交**

Run:

```bash
cd frontend
npm run test -- src/stores/mode.spec.ts src/router/desktopGuard.spec.ts
```

Expected: PASS。

Commit:

```bash
git add frontend/src/utils/desktop/setup.ts frontend/src/stores/mode.ts \
  frontend/src/stores/mode.spec.ts frontend/src/router/desktopGuard.ts \
  frontend/src/router/desktopGuard.spec.ts frontend/src/router/index.ts
git commit -m "feat(desktop): constrain visible workspaces"
```

---

### Task 3: 接入初始化、桌面设置和顶部 Tab

**Files:**
- Modify: `frontend/src/views/DesktopSetupWizard.vue`
- Modify: `frontend/src/views/DesktopSettings.vue`
- Modify: `frontend/src/components/v2/RailSidebar.vue`

**Interfaces:**
- Consumes: `DESKTOP_WORKSPACE_ENTRY_OPTIONS`、`updateDesktopWorkspaceEntryScope`、
  `visibleModesForDesktopScope`、`desktopModeLabel`。
- Produces: window event `desktop-workspace-entry-scope-changed`，其 `detail` 是
  `DesktopWorkspaceEntryScope`。

- [ ] **Step 1: 修改首次初始化**

在 `DesktopSetupWizard.vue` 的“本地存储”步骤、目录预览下增加分段选择。新安装时：

```ts
const workspaceScope = ref<DesktopWorkspaceEntryScope | null>(null)
```

只有 `snapshot.config` 存在时才从配置 hydrate；新安装不得赋 `both`。最终按钮增加
`workspaceScope === null` 禁用条件，提交时将非空 scope 传给
`buildDesktopSetupInput`。`login_only` 流程不显示也不修改该字段。

- [ ] **Step 2: 修改桌面设置**

在 `DesktopSettings.vue` 增加独立“工作台入口” section 和独立保存按钮：

```ts
async function saveWorkspaceEntryScope() {
  if (!workspaceScope.value || workspaceSaving.value) return
  const snapshot = await updateDesktopWorkspaceEntryScope(workspaceScope.value)
  window.dispatchEvent(new CustomEvent('desktop-workspace-entry-scope-changed', {
    detail: snapshot.config?.workspace_entry_scope,
  }))
  // 当前路由若不再可见，replace 到对应首页。
}
```

该 handler 不调用 `user.logout()`，不复用登录设置的 `saving` 锁，也不显示“重新登录”。

- [ ] **Step 3: 修改顶部 Tab**

`RailSidebar.vue` 在桌面 mount 时通过 `getDesktopState()` 初始化 scope，并监听上述事件。
模板的 `v-for` 从固定 `MODE_ORDER` 改为 computed `visibleModeOrder`；桌面标签调用
`desktopModeLabel(mode)`，Web 标签继续使用 `MODE_META[mode].label`。unmount 时移除监听。

- [ ] **Step 4: 运行已有关键测试和桌面前端构建并提交**

Run:

```bash
cd frontend
npm run test -- src/stores/mode.spec.ts src/router/desktopGuard.spec.ts
npm run build:desktop
```

Expected: PASS，桌面 bundle 构建成功。

Commit:

```bash
git add frontend/src/views/DesktopSetupWizard.vue frontend/src/views/DesktopSettings.vue \
  frontend/src/components/v2/RailSidebar.vue
git commit -m "feat(desktop): configure workspace entries"
```

---

### Task 4: 收口登录启动修复和中文安装器

**Files:**
- Modify: `backend/desktop_sidecar.py`
- Modify: `backend/tests/test_desktop_sidecar.py`
- Modify: `src-tauri/tauri.conf.json`

**Interfaces:**
- Produces: `sqlite_database_url(database_path) -> str`，剥离 Windows `\\?\` 或
  `\\?\UNC\` 规范路径前缀后构造 SQLAlchemy SQLite URL。
- Produces: NSIS `SimpChinese` 安装语言。

- [ ] **Step 1: 运行现有 sidecar 回归测试**

Run:

```bash
cd backend
python -m pytest tests/test_desktop_sidecar.py -q
```

Expected: `9 passed`，包含 Windows verbatim path 回归用例。

- [ ] **Step 2: 核对安装器配置和 diff**

Run:

```bash
rg -n 'sqlite_database_url|SimpChinese|languages' \
  backend/desktop_sidecar.py backend/tests/test_desktop_sidecar.py src-tauri/tauri.conf.json
git diff --check
```

Expected: 三处命中且 `git diff --check` 无输出。

- [ ] **Step 3: 提交修复**

```bash
git add backend/desktop_sidecar.py backend/tests/test_desktop_sidecar.py src-tauri/tauri.conf.json
git commit -m "fix(desktop): start sidecar from Windows roots"
```

---

### Task 5: 构建 Windows 0.2.39 单 EXE

**Files:**
- Build output only: `dist-desktop/windows/ruijing-0.2.39-windows-x86_64-setup.exe`

**Interfaces:**
- Consumes: 当前 worktree 已提交源码、Windows agent-runtime、agentic-coding Windows
  venv、Codex Windows vendor 和 Builder dist。
- Produces: 一个包含 Tauri、sidecar 和完整 local runtime appliance 的 NSIS EXE。

- [ ] **Step 1: 创建独立 Windows staging 并同步当前 worktree**

在 PowerShell 使用：

```powershell
$Source = "\\wsl.localhost\Ubuntu\home\shitou\worktrees\d-ai-code\apaas-builder-ai\tauri-local-runtime"
$Stage = "C:\Users\Administrator\dolphin-code-win\build-staging\apaas-builder-ai-0.2.39"
New-Item -ItemType Directory -Force -Path $Stage | Out-Null
robocopy $Source $Stage /MIR /XD .git node_modules target .venv __pycache__ /XF *.pyc *.pyo
if ($LASTEXITCODE -gt 7) { throw "source staging failed: $LASTEXITCODE" }
```

不得直接从 WSL worktree 的空 `src-tauri/resources/agent-runtime` 调用 `tauri build`。

- [ ] **Step 2: 运行完整 Windows appliance 构建**

```powershell
Set-Location $Stage
.\scripts\build-desktop-windows.ps1 `
  -Version 0.2.39 `
  -Bundle nsis `
  -AgentRuntimeRepo "D:\workspaces\d-ai-code\agent-runtime" `
  -AgenticCodingRoot "D:\workspaces\d-ai-code\agentic-coding" `
  -BuilderDist "D:\workspaces\d-ai-code\agent-runtime\web\builder\dist"
```

不要传 `-SkipInstall`，除非 staging 中 Windows Node/Python 依赖已由同一脚本成功安装。

- [ ] **Step 3: 核对 appliance 和安装包**

```powershell
$Installer = Join-Path $Stage "dist-desktop\windows\ruijing-0.2.39-windows-x86_64-setup.exe"
if (-not (Test-Path $Installer)) { throw "installer missing" }
$Required = @(
  "src-tauri\resources\agent-runtime\bin\agent-runtime.exe",
  "src-tauri\resources\agent-runtime\codex\bin\codex.exe",
  "src-tauri\resources\agent-runtime\agentic-coding\.venv\Scripts\python.exe",
  "src-tauri\resources\agent-runtime\web\builder\dist\index.html"
)
foreach ($Relative in $Required) {
  if (-not (Test-Path (Join-Path $Stage $Relative))) { throw "missing $Relative" }
}
Get-Item $Installer | Select-Object FullName, Length, LastWriteTime
Get-FileHash -Algorithm SHA256 $Installer
```

- [ ] **Step 4: 发布到共享下载目录并打开安装包**

```powershell
$Destination = "D:\workspaces\d-ai-code\apaas-builder-ai\dist-desktop\windows\ruijing-0.2.39-windows-x86_64-setup.exe"
Copy-Item $Installer $Destination -Force
Start-Process $Destination
```

只打开安装包，不进行复杂桌面自动点击验证；由用户完成实际安装和交互反馈。

- [ ] **Step 5: 最终源码状态检查**

Run:

```bash
git status --short --branch
git log --oneline -6
```

Expected: 源码 worktree 无未提交修改；不提交 staging、安装包、PyInstaller `dist/`、
Tauri `target/` 或 materialized appliance。
