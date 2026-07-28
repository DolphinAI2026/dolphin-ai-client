# Desktop First-Run Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Dolphin Code 桌面客户端在启动 Runtime Manager 和 sidecar 之前完成登录服务与本地根目录初始化，并在后续启动、失败恢复和设置修改中始终使用同一份可诊断配置。

**Architecture:** Tauri 始终先创建一个加载内置 `dist-desktop` 的主窗口，由 Rust 读取系统 AppData 下的 `bootstrap.json` 和用户根目录下的 `.appdata/desktop-config.json`，再决定显示初始化/恢复界面或后台启动 Runtime Manager 与 sidecar。Rust 是桌面配置与进程生命周期事实源；sidecar 只消费 Rust 校验后传入的登录模式、服务地址、应用目录和 Runtime 目录，业务 WebView 仅在 sidecar 健康后导航到稳定 loopback origin。

**Tech Stack:** Rust 1.93、Tauri 2、serde、ureq、Vue 3、TypeScript、Element Plus、FastAPI/Python、PyInstaller、Vitest、pytest。

## File Map

- Create `src-tauri/src/desktop_config.rs`: 配置类型、路径推导、URL/目录校验、原子持久化及内联 Rust 测试。
- Modify `src-tauri/Cargo.toml`: Windows 配置文件原子替换所需的最小 `windows-sys` feature。
- Create `src-tauri/src/desktop_backend.rs`: 主窗口启动状态机、Tauri commands、Runtime Manager/sidecar 生命周期、导航、日志与恢复。
- Modify `src-tauri/src/lib.rs`: 注册桌面模块、commands、统一主窗口创建和退出清理。
- Modify `backend/desktop_sidecar.py`: 接收登录模式、服务地址、applications 根目录和 Runtime 根目录。
- Modify `backend/app/code_runtime/local_runtime.py`: 将 Runtime 实例路径与 Manager 数据根统一到 `<root>/.appdata/runtime`。
- Modify `backend/ruijing-sidecar.spec`: Windows onefile 使用无控制台子系统。
- Create `frontend/src/utils/desktop/setup.ts`: 全仓唯一的桌面初始化 Tauri invoke 门面和共享类型。
- Modify `frontend/src/utils/desktop/index.ts`: 导出初始化能力。
- Modify `frontend/src/router/desktopGuard.ts`: 增加纯函数形式的桌面启动阶段路由决议。
- Modify `frontend/src/router/index.ts`: 初始化守卫前移到认证守卫之前，删除旧 aPaaS/LLM onboarding 分流。
- Rewrite `frontend/src/views/DesktopSetupWizard.vue`: 两步首次初始化、登录服务单步修改、启动中和失败恢复。
- Create `frontend/src/views/DesktopSettings.vue`: 登录服务修改、根目录只读展示、打开根目录/日志目录。
- Modify `frontend/src/views/Login.vue`: 显示当前服务摘要和“更改登录服务”。
- Modify `frontend/src/components/v2/RailSidebar.vue`: 桌面用户菜单增加“桌面设置”。
- Delete `frontend/src/composables/useOnboardingState.ts`: 退役登录后 aPaaS/LLM 初始化判断。
- Delete `frontend/src/composables/useOnboardingState.spec.ts`: 删除对应过期测试。
- Modify existing tests only: `backend/tests/test_desktop_sidecar.py`, `backend/tests/test_code_runtime_local_runtime.py`, `frontend/src/router/desktopGuard.spec.ts`, `frontend/src/components/v2/RailSidebar.spec.ts`, `frontend/src/stores/user.spec.ts`。

## Shared Contracts

Rust、Python 和 TypeScript 使用以下稳定 wire names，不增加近义字段：

```text
DesktopLoginMode = control_plane | apaas
DesktopPhase = needs_setup | saving_config | starting_runtime | starting_sidecar | ready | failed
DesktopSetupScope = full | login_only
DesktopPathKind = root | logs
```

稳定错误码：

```text
DESKTOP_SETUP_ROOT_REQUIRED
DESKTOP_SETUP_ROOT_UNWRITABLE
DESKTOP_SETUP_CONFIG_INVALID
DESKTOP_SETUP_SERVICE_UNREACHABLE
DESKTOP_SETUP_RUNTIME_START_FAILED
DESKTOP_SETUP_SIDECAR_START_FAILED
```

## Global Constraints

- 桌面端始终只交付一个用户安装的 Tauri 安装包；sidecar 是内部 bundle，不新增第二个用户入口。
- 用户选择的根目录是 applications、Runtime、session、cache 和日志的唯一新数据根；系统 AppData 只保存 `bootstrap.json` 指针。
- 除读取本方案新建的 `bootstrap.json` 外，不扫描、移动、合并或删除系统 AppData 中既有的 `app.db`、密钥、Runtime、应用目录及其他历史文件。
- Rust/Python/TypeScript 必须使用 Shared Contracts 中的 wire names、错误码和路径关系，不增加兼容别名。
- 不新增散落的前端或 Python 测试文件；Rust 测试保持模块内联，前端/Python 只修改 File Map 指定的现有测试文件。
- packaged 页面只通过 Tauri commands 读取启动状态；Runtime Manager 成功且 sidecar 健康后才导航到 loopback 业务 origin。

---

### Task 1: Rust 桌面配置模型与原子持久化

**Files:**
- Create: `src-tauri/src/desktop_config.rs`
- Modify: `src-tauri/Cargo.toml`
- Modify: `src-tauri/src/lib.rs`
- Test: inline `#[cfg(test)]` module in `src-tauri/src/desktop_config.rs`

**Interfaces:**
- Produces: `DesktopConfigStore::load`, `DesktopConfigStore::save`, `DesktopPaths::from_root`, `default_root_dir`。
- Persists: `<system-app-data>/bootstrap.json` and `<root>/.appdata/desktop-config.json`。

- [ ] **Step 1: 写配置反序列化、URL 校验和路径推导失败测试**

在 `desktop_config.rs` 先定义测试使用的公开合同，再写内联测试：

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn unique_test_dir(label: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "dolphin-desktop-{label}-{}-{}",
            std::process::id(),
            SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos(),
        ))
    }

    #[test]
    fn paths_are_derived_from_one_user_root() {
        let paths = DesktopPaths::from_root(PathBuf::from("/tmp/DolphinCode"));
        assert_eq!(paths.applications_dir, PathBuf::from("/tmp/DolphinCode/applications"));
        assert_eq!(paths.data_dir, PathBuf::from("/tmp/DolphinCode/.appdata"));
        assert_eq!(paths.runtime_dir, PathBuf::from("/tmp/DolphinCode/.appdata/runtime"));
        assert_eq!(paths.logs_dir, PathBuf::from("/tmp/DolphinCode/.appdata/logs"));
    }

    #[test]
    fn login_url_rejects_credentials_and_fragments() {
        for raw in [
            "ftp://example.com",
            "https://user:secret@example.com",
            "https://example.com/#fragment",
            "example.com",
        ] {
            assert!(normalize_login_url(raw).is_err(), "accepted {raw}");
        }
        assert_eq!(
            normalize_login_url("https://om-demo.dfy.definesys.cn/").unwrap(),
            "https://om-demo.dfy.definesys.cn",
        );
    }

    #[test]
    fn root_config_is_written_before_bootstrap_pointer() {
        let temp = unique_test_dir("save-order");
        let system_data = temp.join("system");
        let root = temp.join("DolphinCode");
        let store = DesktopConfigStore::new(system_data.clone());
        let saved = store.save(DesktopSetupInput {
            root_dir: root.to_string_lossy().into_owned(),
            login: DesktopLoginConfig {
                mode: DesktopLoginMode::ControlPlane,
                base_url: CONTROL_PLANE_DEFAULT_URL.to_string(),
            },
        }).unwrap();

        assert!(saved.paths.config_path.is_file());
        let pointer: BootstrapPointer = read_json(&system_data.join("bootstrap.json")).unwrap();
        assert_eq!(PathBuf::from(pointer.root_dir), saved.config.root_dir);
        std::fs::remove_dir_all(temp).unwrap();
    }
}
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd src-tauri
cargo test desktop_config --lib
```

Expected: FAIL，模块、类型和函数尚不存在。

- [ ] **Step 3: 实现配置、校验和原子保存**

在 `desktop_config.rs` 定义以下核心类型：

```rust
use serde::{Deserialize, Serialize};
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use tauri::Url;

pub const CONTROL_PLANE_DEFAULT_URL: &str = "https://om-demo.dfy.definesys.cn";
pub const APAAS_DEFAULT_URL: &str = "https://apaas-trial.definesys.cn/backend";

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum DesktopLoginMode {
    ControlPlane,
    Apaas,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct DesktopLoginConfig {
    pub mode: DesktopLoginMode,
    pub base_url: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct DesktopConfig {
    pub schema_version: u32,
    pub root_dir: PathBuf,
    pub login: DesktopLoginConfig,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DesktopSetupInput {
    pub root_dir: String,
    pub login: DesktopLoginConfig,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct BootstrapPointer {
    schema_version: u32,
    root_dir: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct DesktopPaths {
    pub root_dir: PathBuf,
    pub applications_dir: PathBuf,
    pub data_dir: PathBuf,
    pub runtime_dir: PathBuf,
    pub sessions_dir: PathBuf,
    pub cache_dir: PathBuf,
    pub logs_dir: PathBuf,
    pub config_path: PathBuf,
}

#[derive(Debug, Clone, Serialize)]
pub struct SavedDesktopConfig {
    pub config: DesktopConfig,
    pub paths: DesktopPaths,
}

#[derive(Debug, Clone, Serialize, thiserror::Error)]
#[error("{message}")]
pub struct DesktopConfigError {
    pub code: String,
    pub message: String,
}

impl DesktopConfigError {
    fn invalid(message: impl Into<String>) -> Self {
        Self {
            code: "DESKTOP_SETUP_CONFIG_INVALID".to_string(),
            message: message.into(),
        }
    }
}

fn read_json<T: serde::de::DeserializeOwned>(path: &Path) -> Result<T, DesktopConfigError> {
    let bytes = fs::read(path).map_err(|error| DesktopConfigError::invalid(error.to_string()))?;
    serde_json::from_slice(&bytes).map_err(|error| DesktopConfigError::invalid(error.to_string()))
}
```

实现约束：

```rust
pub fn normalize_login_url(raw: &str) -> Result<String, DesktopConfigError> {
    let mut url = Url::parse(raw.trim()).map_err(|_| DesktopConfigError::invalid("服务地址不是有效 URL"))?;
    if !matches!(url.scheme(), "http" | "https")
        || url.host_str().is_none()
        || !url.username().is_empty()
        || url.password().is_some()
        || url.fragment().is_some()
    {
        return Err(DesktopConfigError::invalid("服务地址必须是无凭据、无 fragment 的 HTTP(S) 绝对 URL"));
    }
    url.set_fragment(None);
    Ok(url.as_str().trim_end_matches('/').to_string())
}
```

`DesktopConfigStore::save` 必须按以下顺序执行：创建并规范化根目录；创建 `applications/`、`.appdata/runtime/`、`.appdata/sessions/`、`.appdata/cache/`、`.appdata/logs/`；在根目录创建、`sync_all` 并删除探测文件；原子写根配置；最后原子写 `bootstrap.json`。`atomic_write_json` 使用同目录临时文件和 `sync_all`，不得先删除旧目标文件。Unix 使用 `fs::rename` 覆盖；Windows 在目标已存在时使用 `MoveFileExW(MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)`，因此在 `src-tauri/Cargo.toml` 的 Windows dependencies 增加带 `Win32_Storage_FileSystem` feature 的 `windows-sys`。

`DesktopConfigStore::load` 对缺失 `bootstrap.json` 返回 `Ok(None)`；对 schema 不匹配、相对路径、根配置缺失、根配置 `root_dir` 与 pointer 不一致返回 `DESKTOP_SETUP_CONFIG_INVALID`，不删除任何文件。

默认目录必须来自 Tauri 解析出的 home directory，不读取当前工作目录：

```rust
pub fn default_root_dir(home_dir: &Path) -> PathBuf {
    home_dir.join("DolphinCode")
}
```

- [ ] **Step 4: 暴露模块并运行测试**

在 `src-tauri/src/lib.rs` 增加：

```rust
pub mod desktop_config;
```

运行：

```bash
cd src-tauri
cargo fmt --check
cargo test desktop_config --lib
```

Expected: PASS，配置能往返读取，非法 URL 和不可写根目录返回稳定错误码。

- [ ] **Step 5: 提交配置层**

```bash
git add src-tauri/Cargo.toml src-tauri/Cargo.lock src-tauri/src/desktop_config.rs src-tauri/src/lib.rs
git commit -m "feat(desktop): persist first-run configuration"
```

---

### Task 2: Tauri 主窗口与后端启动状态机

**Files:**
- Create: `src-tauri/src/desktop_backend.rs`
- Modify: `src-tauri/src/lib.rs`
- Test: inline `#[cfg(test)]` module in `src-tauri/src/desktop_backend.rs`

**Interfaces:**
- Produces commands: `desktop_get_state`, `desktop_save_setup`, `desktop_test_service`, `desktop_enter_login_setup`, `desktop_retry_start`, `desktop_update_login`, `desktop_open_path`。
- Owns: `LocalRuntimeApiServer`, `CommandChild`, packaged URL, stable sidecar port, launch generation and current error。

- [ ] **Step 1: 写状态转换和 sidecar 参数失败测试**

在 `desktop_backend.rs` 内联测试纯函数，不启动真实 Tauri：

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use crate::desktop_config::{DesktopConfig, DesktopLoginConfig, DesktopLoginMode};

    fn fixture_config(mode: DesktopLoginMode) -> DesktopConfig {
        DesktopConfig {
            schema_version: 1,
            root_dir: PathBuf::from("/tmp/DolphinCode"),
            login: DesktopLoginConfig {
                mode,
                base_url: "https://om-demo.dfy.definesys.cn".to_string(),
            },
        }
    }

    #[test]
    fn control_plane_sidecar_contract_uses_applications_and_runtime_dirs() {
        let config = fixture_config(DesktopLoginMode::ControlPlane);
        let launch = SidecarLaunch::from_config(&config, 8799, "http://127.0.0.1:9001", "token");
        let applications = config.root_dir.join("applications");
        let runtime = config.root_dir.join(".appdata/runtime");
        assert_eq!(launch.arg_value("--applications-root"), applications.to_string_lossy().as_ref());
        assert_eq!(launch.arg_value("--runtime-data-dir"), runtime.to_string_lossy().as_ref());
        assert_eq!(launch.arg_value("--login-mode"), "control_plane");
        assert_eq!(launch.arg_value("--login-base-url"), "https://om-demo.dfy.definesys.cn");
    }

    #[test]
    fn failed_runtime_does_not_collapse_to_legacy_manager_unavailable() {
        let error = DesktopBackendError::runtime("cannot bind local runtime manager");
        assert_eq!(error.code, "DESKTOP_SETUP_RUNTIME_START_FAILED");
        assert!(!error.message.contains("LOCAL_RUNTIME_MANAGER_UNAVAILABLE"));
    }
}
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd src-tauri
cargo test desktop_backend --lib
```

Expected: FAIL，状态机与 launch contract 尚不存在。

- [ ] **Step 3: 实现状态与命令返回模型**

定义共享状态：

```rust
#[derive(Debug, Clone, Copy, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum DesktopPhase {
    NeedsSetup,
    SavingConfig,
    StartingRuntime,
    StartingSidecar,
    Ready,
    Failed,
}

#[derive(Debug, Clone, Copy, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum DesktopSetupScope {
    Full,
    LoginOnly,
}

#[derive(Debug, Clone, Serialize)]
pub struct DesktopBackendError {
    pub code: String,
    pub message: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct DesktopStateSnapshot {
    pub phase: DesktopPhase,
    pub setup_scope: DesktopSetupScope,
    pub config: Option<DesktopConfig>,
    pub default_root_dir: PathBuf,
    pub error: Option<DesktopBackendError>,
}

#[derive(Debug, Clone, Copy, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DesktopPathKind {
    Root,
    Logs,
}

struct SidecarLaunch {
    args: Vec<String>,
    env: std::collections::BTreeMap<String, String>,
}

impl SidecarLaunch {
    fn from_config(
        config: &DesktopConfig,
        port: u16,
        manager_url: &str,
        manager_token: &str,
    ) -> Self {
        let paths = DesktopPaths::from_root(config.root_dir.clone());
        let mode = match config.login.mode {
            DesktopLoginMode::ControlPlane => "control_plane",
            DesktopLoginMode::Apaas => "apaas",
        };
        Self {
            args: vec![
                "--port".into(), port.to_string(),
                "--data-dir".into(), paths.data_dir.to_string_lossy().into_owned(),
                "--applications-root".into(), paths.applications_dir.to_string_lossy().into_owned(),
                "--runtime-data-dir".into(), paths.runtime_dir.to_string_lossy().into_owned(),
                "--login-mode".into(), mode.into(),
                "--login-base-url".into(), config.login.base_url.clone(),
            ],
            env: [
                ("DOLPHIN_LOCAL_RUNTIME_MANAGER_URL".into(), manager_url.into()),
                ("DOLPHIN_LOCAL_RUNTIME_MANAGER_TOKEN".into(), manager_token.into()),
            ].into_iter().collect(),
        }
    }

    fn arg_value(&self, key: &str) -> &str {
        let index = self.args.iter().position(|item| item == key).expect("argument exists");
        self.args.get(index + 1).expect("argument value exists")
    }
}
```

`DesktopBackend` 内部只允许一个 launch generation 生效：每次重试或登录服务切换递增 generation，旧线程即使稍后健康也不得覆盖当前状态或导航窗口。

commands 使用以下签名，所有错误都返回可序列化的稳定 `code/message`：

```rust
#[tauri::command]
pub fn desktop_get_state(state: tauri::State<'_, DesktopBackend>)
    -> DesktopStateSnapshot;

#[tauri::command]
pub fn desktop_save_setup(
    app: tauri::AppHandle,
    state: tauri::State<'_, DesktopBackend>,
    input: DesktopSetupInput,
) -> Result<DesktopStateSnapshot, DesktopBackendError>;

#[tauri::command]
pub fn desktop_test_service(
    login: DesktopLoginConfig,
) -> Result<(), DesktopBackendError>;

#[tauri::command]
pub fn desktop_enter_login_setup(
    app: tauri::AppHandle,
    state: tauri::State<'_, DesktopBackend>,
) -> Result<(), DesktopBackendError>;

#[tauri::command]
pub fn desktop_retry_start(
    app: tauri::AppHandle,
    state: tauri::State<'_, DesktopBackend>,
) -> Result<DesktopStateSnapshot, DesktopBackendError>;

#[tauri::command]
pub fn desktop_update_login(
    app: tauri::AppHandle,
    state: tauri::State<'_, DesktopBackend>,
    login: DesktopLoginConfig,
) -> Result<DesktopStateSnapshot, DesktopBackendError>;

#[tauri::command]
pub fn desktop_open_path(
    app: tauri::AppHandle,
    state: tauri::State<'_, DesktopBackend>,
    kind: DesktopPathKind,
) -> Result<(), DesktopBackendError>;
```

`desktop_test_service` 先复用 `normalize_login_url`，再用 5 秒超时请求该 URL。任意 2xx-4xx 响应表示服务可达；传输失败或 5xx 返回 `DESKTOP_SETUP_SERVICE_UNREACHABLE`。该 command 只服务显式“测试连接”按钮，不参与保存阻塞条件。

- [ ] **Step 4: 将当前 `lib.rs` 启动逻辑拆入生命周期对象**

把 `packaged_agent_runtime_root`、`stable_port`、`wait_healthy`、sidecar spawn、进程事件日志、深度终止逻辑移入 `desktop_backend.rs`。`lib.rs` 只保留 builder wiring：

```rust
pub mod desktop_backend;
pub mod desktop_config;
pub mod local_runtime;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            desktop_backend::desktop_get_state,
            desktop_backend::desktop_save_setup,
            desktop_backend::desktop_test_service,
            desktop_backend::desktop_enter_login_setup,
            desktop_backend::desktop_retry_start,
            desktop_backend::desktop_update_login,
            desktop_backend::desktop_open_path,
        ])
        .setup(desktop_backend::setup)
        .build(tauri::generate_context!())
        .expect("error while running tauri application")
        .run(desktop_backend::handle_run_event);
}
```

`setup` 必须立即创建唯一 `main` 窗口，初始 URL 固定为 `WebviewUrl::App("index.html".into())`。创建后保存 `window.url()` 作为跨平台 packaged URL；不得硬编码 `tauri://localhost` 或 `http://tauri.localhost`。

读取配置后：

```text
Ok(None)             -> needs_setup/full
Err(config error)    -> needs_setup/full + DESKTOP_SETUP_CONFIG_INVALID
Ok(Some(config))     -> starting_runtime -> starting_sidecar -> ready
```

启动过程在后台线程执行，窗口始终可见。Runtime 或 sidecar 失败时更新 `failed`，保留 packaged 页面，不退出应用。

- [ ] **Step 5: 实现 Runtime 与 sidecar 启动顺序**

Runtime Manager 必须使用：

```rust
LocalRuntimeApiServer::start(&paths.runtime_dir, &agent_runtime_root)
```

sidecar 只有在 Manager 成功后才启动。其参数必须完整包含：

```text
--port <stable-port>
--data-dir <root>/.appdata
--applications-root <root>/applications
--runtime-data-dir <root>/.appdata/runtime
--login-mode control_plane|apaas
--login-base-url <validated-url>
```

并继续注入：

```text
DOLPHIN_LOCAL_RUNTIME_MANAGER_URL
DOLPHIN_LOCAL_RUNTIME_MANAGER_TOKEN
DOLPHIN_DESKTOP_DATA_DIR=<root>/.appdata
DOLPHIN_AGENT_RUNTIME_PATH=<packaged-agent-runtime>
CODING_USE_RUNAGENT=1
```

sidecar 健康后调用：

```rust
window.navigate(tauri::Url::parse(&format!("http://127.0.0.1:{port}/"))?)?;
```

首次配置或重试只轮询 `desktop_get_state`；不得让 packaged 页面请求 sidecar API。

- [ ] **Step 6: 实现登录服务切换与退出清理**

`desktop_enter_login_setup`：先把当前状态设为 `needs_setup/login_only`，导航到已保存的 packaged URL，再静默停止 sidecar；保留 Runtime Manager。

`desktop_update_login`：复用当前 `root_dir` 写入配置，状态切到 `starting_sidecar`，导航 packaged URL，停止旧 sidecar，使用现有 Runtime Manager URL/token 启动新 sidecar。若 Manager 已丢失，则走完整 `starting_runtime -> starting_sidecar`。

`RunEvent::ExitRequested | RunEvent::Exit`：先停止 sidecar 进程树，再调用 `LocalRuntimeApiServer::shutdown()`。Windows sidecar 进程树使用 `taskkill /PID <pid> /T /F` 且给 `taskkill` 自身设置 `CREATE_NO_WINDOW`；Unix 保留先收集 child PID 再终止的逻辑。

- [ ] **Step 7: 运行 Rust 验证并提交**

```bash
cd src-tauri
cargo fmt --check
cargo test desktop_backend --lib
cargo test local_runtime --lib
cargo check
git add src-tauri/src/desktop_backend.rs src-tauri/src/lib.rs
git commit -m "feat(desktop): add recoverable startup state machine"
```

Expected: 主窗口不再等待 sidecar 才创建，失败不退出，Manager 先于 sidecar 启动。

---

### Task 3: sidecar 登录与 Runtime 路径合同

**Files:**
- Modify: `backend/desktop_sidecar.py`
- Modify: `backend/app/code_runtime/local_runtime.py`
- Modify: `backend/ruijing-sidecar.spec`
- Test: `backend/tests/test_desktop_sidecar.py`
- Test: `backend/tests/test_code_runtime_local_runtime.py`

**Interfaces:**
- Consumes Tauri arguments from Task 2。
- Produces settings env and a Manager request path rooted at `<root>/.appdata/runtime`。

- [ ] **Step 1: 在现有测试文件增加失败测试**

`backend/tests/test_desktop_sidecar.py` 增加：

```python
def test_build_env_maps_control_plane_login_and_user_root(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "environ", os.environ.copy())
    data_dir = tmp_path / ".appdata"
    env = ds.build_env(
        data_dir=data_dir,
        port=8799,
        login_mode="control_plane",
        login_base_url="https://om-demo.dfy.definesys.cn",
        applications_root=tmp_path / "applications",
        runtime_data_dir=data_dir / "runtime",
    )
    assert env["AUTH_PROVIDER"] == "control_plane"
    assert env["DOLPHIN_WORKSPACE_BASE_URL"] == "https://om-demo.dfy.definesys.cn"
    assert env["APAAS_BASE_URL"] == ""
    assert env["APAAS_WORKSPACE_ROOT"] == str(tmp_path / "applications")
    assert env["DOLPHIN_LOCAL_RUNTIME_DATA_DIR"] == str(data_dir / "runtime")


def test_build_env_maps_apaas_login(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "environ", os.environ.copy())
    env = ds.build_env(
        data_dir=tmp_path / ".appdata",
        port=8799,
        login_mode="apaas",
        login_base_url="https://apaas-trial.definesys.cn/backend",
        applications_root=tmp_path / "applications",
        runtime_data_dir=tmp_path / ".appdata/runtime",
    )
    assert env["AUTH_PROVIDER"] == "apaas"
    assert env["APAAS_BASE_URL"] == "https://apaas-trial.definesys.cn/backend"
    assert env["DOLPHIN_WORKSPACE_BASE_URL"] == ""
```

`backend/tests/test_code_runtime_local_runtime.py` 增加环境断言：

```python
def test_from_environment_uses_explicit_runtime_data_dir(monkeypatch, tmp_path):
    runtime_dir = tmp_path / ".appdata" / "runtime"
    runtime_dir.mkdir(parents=True)
    monkeypatch.setenv("DOLPHIN_LOCAL_RUNTIME_MANAGER_URL", "http://127.0.0.1:9988")
    monkeypatch.setenv("DOLPHIN_LOCAL_RUNTIME_MANAGER_TOKEN", "manager-secret")
    monkeypatch.setenv("DOLPHIN_DESKTOP_DATA_DIR", str(tmp_path / ".appdata"))
    monkeypatch.setenv("DOLPHIN_LOCAL_RUNTIME_DATA_DIR", str(runtime_dir))
    monkeypatch.setenv("DOLPHIN_AGENT_RUNTIME_PATH", str(tmp_path / "agent-runtime"))
    client = LocalRuntimeClient.from_environment()
    assert client.runtime_data_dir == runtime_dir
```

- [ ] **Step 2: 运行测试确认失败**

```bash
backend/.venv/bin/python -m pytest -q \
  backend/tests/test_desktop_sidecar.py \
  backend/tests/test_code_runtime_local_runtime.py \
  -k 'build_env_maps or explicit_runtime_data_dir'
```

Expected: FAIL，`build_env` 无新参数，LocalRuntimeClient 仍使用 desktop data 根。

- [ ] **Step 3: 扩展 sidecar CLI 和环境映射**

将 `build_env` 改为显式参数合同：

```python
def build_env(
    data_dir: Path,
    port: int,
    *,
    login_mode: str = "control_plane",
    login_base_url: str = "https://om-demo.dfy.definesys.cn",
    applications_root: Path | None = None,
    runtime_data_dir: Path | None = None,
) -> dict:
    if login_mode not in {"control_plane", "apaas"}:
        raise ValueError("login_mode must be control_plane or apaas")
    applications_root = Path(applications_root or data_dir.parent / "applications")
    runtime_data_dir = Path(runtime_data_dir or data_dir / "runtime")
    db_path = data_dir / "app.db"
    written = {
        "DESKTOP_MODE": "1",
        "HOST": "127.0.0.1",
        "PORT": str(port),
        "SIDECAR_DATA_DIR": str(data_dir),
        "DATABASE_URL": f"sqlite+aiosqlite:///{db_path}",
        "ENCRYPTION_KEY": ensure_encryption_key(data_dir),
        "JWT_SECRET_KEY": ensure_jwt_secret(data_dir),
        "AUTH_PROVIDER": login_mode,
        "DOLPHIN_WORKSPACE_BASE_URL": login_base_url if login_mode == "control_plane" else "",
        "APAAS_BASE_URL": login_base_url if login_mode == "apaas" else "",
        "PUBLIC_ACCOUNT_BASE_URL": "",
        "ACCEPTED_TOKEN_ISSUERS": "ai-builder,desktop-sidecar",
        "APAAS_WORKSPACE_ROOT": str(applications_root),
        "DOLPHIN_LOCAL_RUNTIME_DATA_DIR": str(runtime_data_dir),
    }
```

`main()` 增加 `--login-mode`、`--login-base-url`、`--applications-root`、`--runtime-data-dir` 参数并原样传给 `build_env`。默认值保留现有开发启动兼容，但桌面包必须由 Tauri 显式传入。

- [ ] **Step 4: 统一 Python Runtime 目录**

`LocalRuntimeClient.__init__` 增加 `runtime_data_dir`，兼容未传入时回落到 `desktop_data_dir`：

```python
self.runtime_data_dir = (
    Path(runtime_data_dir).expanduser()
    if runtime_data_dir is not None
    else self.desktop_data_dir
)
```

`from_environment()` 读取 `DOLPHIN_LOCAL_RUNTIME_DATA_DIR`，缺失时兼容为 `Path(DOLPHIN_DESKTOP_DATA_DIR) / "runtime"`。把 `_assert_reused_provider`、`_entry_token`、`_start`、runtime lock 中所有 `_runtime_directory_fds` / `_scope_directory_fds` 的根参数从 `self.desktop_data_dir` 改为 `self.runtime_data_dir`。

最终 Rust Manager 与 Python 生成的请求路径必须同时满足：

```text
manager data_root = <root>/.appdata/runtime
codex_home       = <root>/.appdata/runtime/local-runtimes/<scope>/codex-home
runtime_dir      = <root>/.appdata/runtime/local-runtimes/<scope>/instances/<instance>
```

- [ ] **Step 5: 禁止 Windows sidecar 弹控制台**

在 `backend/ruijing-sidecar.spec` 改为：

```python
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="ruijing-sidecar",
    debug=False,
    strip=False,
    upx=False,
    console=(os.name != "nt"),
    onefile=True,
)
```

Tauri 继续消费 stdout/stderr 并写日志；不得通过显示命令行窗口承担诊断职责。

- [ ] **Step 6: 运行测试并提交**

```bash
backend/.venv/bin/python -m pytest -q \
  backend/tests/test_desktop_sidecar.py \
  backend/tests/test_code_runtime_local_runtime.py
git add backend/desktop_sidecar.py backend/app/code_runtime/local_runtime.py backend/ruijing-sidecar.spec backend/tests/test_desktop_sidecar.py backend/tests/test_code_runtime_local_runtime.py
git commit -m "fix(desktop): align sidecar and runtime root contracts"
```

Expected: `APAAS_WORKSPACE_ROOT` 指向 applications，Runtime Manager 请求不再逃逸 Manager 的 data root。

---

### Task 4: 前端桌面初始化 API 与认证前路由守卫

**Files:**
- Create: `frontend/src/utils/desktop/setup.ts`
- Modify: `frontend/src/utils/desktop/index.ts`
- Modify: `frontend/src/router/desktopGuard.ts`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/router/desktopGuard.spec.ts`
- Modify: `frontend/src/stores/user.ts`
- Modify: `frontend/src/stores/user.spec.ts`
- Delete: `frontend/src/composables/useOnboardingState.ts`
- Delete: `frontend/src/composables/useOnboardingState.spec.ts`

**Interfaces:**
- Consumes Task 2 Tauri commands。
- Produces one early route gate that works on both packaged and sidecar origins。

- [ ] **Step 1: 在现有 desktop guard 测试中写失败断言**

扩展 `frontend/src/router/desktopGuard.spec.ts`：

```ts
import { resolveDesktopBootstrapRedirect } from './desktopGuard'

it('未初始化和启动失败都在认证前进入桌面初始化页', () => {
  expect(resolveDesktopBootstrapRedirect('needs_setup', '/login')).toBe('/desktop-setup')
  expect(resolveDesktopBootstrapRedirect('starting_runtime', '/')).toBe('/desktop-setup')
  expect(resolveDesktopBootstrapRedirect('failed', '/code/apps')).toBe('/desktop-setup')
})

it('ready 后放行业务路由，初始化页自身防环', () => {
  expect(resolveDesktopBootstrapRedirect('ready', '/login')).toBeNull()
  expect(resolveDesktopBootstrapRedirect('needs_setup', '/desktop-setup')).toBeNull()
})

it('旧 aPaaS 和 LLM onboarding 守卫已退役', () => {
  expect(routerSource).not.toContain('fetchOnboardingState')
  expect(routerSource).not.toContain('isOnboardingConfirmed')
  expect(routerSource).toContain("meta: { tenantContext: 'none' }")
})
```

更新旧断言：`/desktop-setup` 不再重定向 `/code/apps`，也不再要求 `requiresAuth`。

- [ ] **Step 2: 运行测试确认失败**

```bash
cd frontend
npm run test -- src/router/desktopGuard.spec.ts src/stores/user.spec.ts
```

Expected: FAIL，新 API/守卫不存在，旧 onboarding import 仍存在。

- [ ] **Step 3: 实现 Tauri invoke 门面**

`frontend/src/utils/desktop/setup.ts` 定义完整类型：

```ts
export type DesktopLoginMode = 'control_plane' | 'apaas'
export type DesktopPhase =
  | 'needs_setup'
  | 'saving_config'
  | 'starting_runtime'
  | 'starting_sidecar'
  | 'ready'
  | 'failed'
export type DesktopSetupScope = 'full' | 'login_only'

export interface DesktopLoginConfig {
  mode: DesktopLoginMode
  base_url: string
}

export interface DesktopConfig {
  schema_version: number
  root_dir: string
  login: DesktopLoginConfig
}

export interface DesktopStateSnapshot {
  phase: DesktopPhase
  setup_scope: DesktopSetupScope
  config: DesktopConfig | null
  default_root_dir: string
  error: { code: string; message: string } | null
}

async function invokeDesktop<T>(command: string, args?: Record<string, unknown>): Promise<T> {
  if (!__DESKTOP__) throw new Error('Desktop capability is unavailable')
  const { invoke } = await import('@tauri-apps/api/core')
  return invoke<T>(command, args)
}
```

导出 `getDesktopState`、`saveDesktopSetup`、`testDesktopService`、`enterDesktopLoginSetup`、`retryDesktopStart`、`updateDesktopLogin`、`openDesktopPath`。在 `frontend/src/utils/desktop/index.ts` 统一 re-export，业务组件不得直接 import `@tauri-apps/api/core`。

- [ ] **Step 4: 将桌面启动守卫前移到认证前**

`desktopGuard.ts` 增加纯函数：

```ts
export function resolveDesktopBootstrapRedirect(
  phase: DesktopPhase,
  targetPath: string,
): string | null {
  if (phase === 'ready') return null
  if (targetPath.startsWith('/desktop-setup')) return null
  return '/desktop-setup'
}
```

`router/index.ts` 中 `/desktop-setup` 改为：

```ts
{
  path: '/desktop-setup',
  name: 'DesktopSetup',
  component: () => import('@/views/DesktopSetupWizard.vue'),
  meta: { tenantContext: 'none' },
}
```

在 `beforeEach` 的第一段、创建 `userStore` 和恢复用户之前执行：

```ts
let desktopBootstrapReadyForDocument = false

if (__DESKTOP__) {
  if (!desktopBootstrapReadyForDocument) {
    const desktopState = await getDesktopState()
    desktopBootstrapReadyForDocument = desktopState.phase === 'ready'
    const desktopRedirect = resolveDesktopBootstrapRedirect(desktopState.phase, to.path)
    if (desktopRedirect) {
      next({ path: desktopRedirect, replace: true })
      return
    }
  }
}
```

该缓存只存当前 document；Tauri 从 sidecar origin 导航回 packaged origin 时会创建新 document，缓存自然重置，不会掩盖登录服务切换状态。

删除所有 `fetchOnboardingState`、`isOnboardingConfirmed`、`markOnboardingConfirmed` 逻辑。删除 composable 两个文件，并从 `user.ts` 删除 `resetOnboardingCache` import/call；登出仍只清认证态。

- [ ] **Step 5: 运行测试和桌面构建并提交**

```bash
cd frontend
npm run test -- src/router/desktopGuard.spec.ts src/stores/user.spec.ts src/utils/desktop/guard.spec.ts
npm run build:desktop
git add src/utils/desktop/setup.ts src/utils/desktop/index.ts src/router/desktopGuard.ts src/router/index.ts src/router/desktopGuard.spec.ts src/stores/user.ts src/stores/user.spec.ts
git rm src/composables/useOnboardingState.ts src/composables/useOnboardingState.spec.ts
git commit -m "feat(desktop): gate routes on native bootstrap state"
```

Expected: packaged origin 在没有 sidecar 时仍能进入 `/desktop-setup`，Web build 不包含 Tauri API。

---

### Task 5: 两步初始化、启动中和失败恢复界面

**Files:**
- Rewrite: `frontend/src/views/DesktopSetupWizard.vue`
- Modify: `frontend/src/router/desktopGuard.spec.ts`

**Interfaces:**
- Full scope: 登录服务 -> 本地存储 -> 保存/启动。
- Login-only scope: 仅登录服务，保留 root，不出现第二次目录弹窗。

- [ ] **Step 1: 在现有测试文件锁定服务目录与提交规则**

从 `setup.ts` 导出无副作用常量和 helper，并在 `desktopGuard.spec.ts` 覆盖：

```ts
export type DesktopLoginServiceMode = DesktopLoginMode | 'public_account' | 'trial_account'

export interface DesktopLoginServiceOption {
  mode: DesktopLoginServiceMode
  label: string
  defaultUrl: string
  enabled: boolean
}

export interface DesktopSetupInput {
  root_dir: string
  login: DesktopLoginConfig
}

export const DESKTOP_LOGIN_SERVICES: readonly DesktopLoginServiceOption[] = [
  { mode: 'control_plane', label: 'AI中台', defaultUrl: 'https://om-demo.dfy.definesys.cn', enabled: true },
  { mode: 'apaas', label: 'aPaaS平台', defaultUrl: 'https://apaas-trial.definesys.cn/backend', enabled: true },
  { mode: 'public_account', label: '公开账号', defaultUrl: '', enabled: false },
  { mode: 'trial_account', label: '试用账号', defaultUrl: '', enabled: false },
]

export function buildDesktopSetupInput(
  rootDir: string,
  mode: DesktopLoginMode,
  baseUrl: string,
): DesktopSetupInput {
  return { root_dir: rootDir, login: { mode, base_url: baseUrl } }
}
```

```ts
import { DESKTOP_LOGIN_SERVICES, buildDesktopSetupInput } from '@/utils/desktop/setup'

it('桌面登录服务只启用 AI中台和 aPaaS平台', () => {
  expect(DESKTOP_LOGIN_SERVICES).toEqual([
    { mode: 'control_plane', label: 'AI中台', defaultUrl: 'https://om-demo.dfy.definesys.cn', enabled: true },
    { mode: 'apaas', label: 'aPaaS平台', defaultUrl: 'https://apaas-trial.definesys.cn/backend', enabled: true },
    { mode: 'public_account', label: '公开账号', defaultUrl: '', enabled: false },
    { mode: 'trial_account', label: '试用账号', defaultUrl: '', enabled: false },
  ])
})

it('初始化提交不包含账号、密码、租户或模型字段', () => {
  expect(buildDesktopSetupInput('C:\\Users\\Administrator\\DolphinCode', 'control_plane', 'https://example.com'))
    .toEqual({
      root_dir: 'C:\\Users\\Administrator\\DolphinCode',
      login: { mode: 'control_plane', base_url: 'https://example.com' },
    })
})
```

`public_account` 与 `trial_account` 只存在于前端展示目录，不进入 `DesktopLoginMode` 或 Rust 配置。

- [ ] **Step 2: 运行测试确认失败**

```bash
cd frontend
npm run test -- src/router/desktopGuard.spec.ts
```

Expected: FAIL，服务目录和 helper 尚未定义。

- [ ] **Step 3: 重写两步向导**

`DesktopSetupWizard.vue` 使用以下状态：

```ts
const state = ref<DesktopStateSnapshot | null>(null)
const step = ref<0 | 1>(0)
const mode = ref<DesktopLoginMode>('control_plane')
const baseUrl = ref('https://om-demo.dfy.definesys.cn')
const rootDir = ref('')
const submitting = ref(false)
const connectionTesting = ref(false)
```

第一步固定显示四个服务选项；禁用项显示“暂未开放”。切换启用模式时，只在该模式尚未被用户编辑时填入默认 URL。URL 输入非法时阻止“下一步”，连接测试失败只显示错误，不阻止继续。

第二步显示根目录输入、文件夹图标按钮、只读预览：

```text
<root>/applications
<root>/.appdata
```

点击文件夹按钮只调用一次 `pickDirectory('选择 Dolphin Code 本地根目录')`，不弹第二次确认。点击“保存并进入登录”后不创建完成页，按钮区域按 `state.phase` 显示：

```text
saving_config    保存配置
starting_runtime 启动本地环境
starting_sidecar 打开登录页
```

每 300ms 轮询 `getDesktopState()`；`ready` 后由 Tauri 自行导航，组件不猜 sidecar URL。

- [ ] **Step 4: 实现 login-only 与恢复模式**

当 `setup_scope === 'login_only'` 时只显示第一步，根目录从 `state.config.root_dir` 保留且不编辑；按钮文案为“保存并重新登录”。

当 `phase === 'failed'` 时在同一页面显示：错误码、用户消息、“重试启动”、“打开日志目录”；full scope 额外显示“重新选择目录”。`DESKTOP_SETUP_CONFIG_INVALID` 直接回到可编辑两步表单。不得显示 token、完整环境变量或 Python traceback。

- [ ] **Step 5: 构建验证并提交**

```bash
cd frontend
npm run test -- src/router/desktopGuard.spec.ts src/utils/desktop/guard.spec.ts
npm run build:desktop
git add src/views/DesktopSetupWizard.vue src/utils/desktop/setup.ts src/router/desktopGuard.spec.ts
git commit -m "feat(desktop): add two-step first-run setup"
```

Expected: 页面只有两步，没有旧 aPaaS 凭据/LLM/API Key，也没有第三个完成页或双弹窗。

---

### Task 6: 登录服务摘要与桌面设置页

**Files:**
- Create: `frontend/src/views/DesktopSettings.vue`
- Modify: `frontend/src/views/Login.vue`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/components/v2/RailSidebar.vue`
- Modify: `frontend/src/components/v2/RailSidebar.spec.ts`

**Interfaces:**
- Login page consumes `DesktopStateSnapshot.config.login`。
- Settings updates login only and never mutates root directory。

- [ ] **Step 1: 在现有 RailSidebar 测试中写失败断言**

```ts
it('桌面用户菜单提供桌面设置且 Web 不显示', () => {
  expect(railSidebarSource).toContain("path: '/desktop-settings'")
  expect(railSidebarSource).toContain('v-if="isDesktop"')
  expect(railSidebarSource).toContain('桌面设置')
})
```

在 `desktopGuard.spec.ts` raw source 断言 `/desktop-settings` 为 `requiresAuth: true`，`Login.vue` 包含 `enterDesktopLoginSetup` 和服务摘要。

- [ ] **Step 2: 运行测试确认失败**

```bash
cd frontend
npm run test -- src/components/v2/RailSidebar.spec.ts src/router/desktopGuard.spec.ts
```

Expected: FAIL，入口和页面尚不存在。

- [ ] **Step 3: 修改登录页**

`Login.vue` 在标题支持文案下显示：

```vue
<div v-if="desktopService" class="login-service-row">
  <span>{{ desktopService.label }} · {{ desktopService.host }}</span>
  <button type="button" class="login-service-change" @click="changeDesktopService">
    更改登录服务
  </button>
</div>
```

`onMounted` 在桌面端调用 `getDesktopState()`，将 `control_plane` 映射为“AI中台”、`apaas` 映射为“aPaaS平台”，host 使用 `new URL(base_url).host`。`changeDesktopService` 先 `userStore.logout()`，再 `enterDesktopLoginSetup()`；不得用 Vue router 假装 sidecar 仍可用。

- [ ] **Step 4: 创建桌面设置页**

新增路由：

```ts
{
  path: '/desktop-settings',
  name: 'DesktopSettings',
  component: () => import('@/views/DesktopSettings.vue'),
  meta: { requiresAuth: true, tenantContext: 'none' },
}
```

页面使用 `BuilderFrame`，包含：登录模式二选一、服务地址输入、本地根目录只读输入、打开根目录按钮、打开日志目录按钮、保存按钮。根目录旁明确不提供编辑和迁移操作。

保存流程：校验 URL；`user.logout()` 清当前 sidecar origin 的认证态；调用 `updateDesktopLogin({ mode, base_url })`。Rust 持久化后切到 packaged 启动页并重启 sidecar，前端不热改旧会话。

- [ ] **Step 5: 增加用户菜单入口**

`RailSidebar.vue` 新增 `settings` 图标和仅桌面显示的菜单按钮，位置在主题切换之前：

```vue
<button v-if="isDesktop" type="button" class="theme-row" @click="go('/desktop-settings')">
  <span class="theme-row-icon" v-html="renderIcon('settings')" />
  <span class="theme-row-label">桌面设置</span>
</button>
```

保持“检查更新”和“退出登录”现有行为。

- [ ] **Step 6: 运行测试、构建并提交**

```bash
cd frontend
npm run test -- src/components/v2/RailSidebar.spec.ts src/router/desktopGuard.spec.ts src/utils/desktop/guard.spec.ts
npm run build:desktop
git add src/views/DesktopSettings.vue src/views/Login.vue src/router/index.ts src/components/v2/RailSidebar.vue src/components/v2/RailSidebar.spec.ts src/router/desktopGuard.spec.ts
git commit -m "feat(desktop): expose login service settings"
```

Expected: 登录页能返回单步服务选择，登录后设置页能修改服务，Web 端不显示桌面设置。

---

### Task 7: 失败诊断、日志和恢复命令

**Files:**
- Modify: `src-tauri/src/desktop_backend.rs`
- Modify: `frontend/src/views/DesktopSetupWizard.vue`
- Test: inline Rust tests in `src-tauri/src/desktop_backend.rs`
- Test: `frontend/src/router/desktopGuard.spec.ts`

**Interfaces:**
- Produces sanitized `<root>/.appdata/logs/desktop.log` and `sidecar.log`。
- Keeps all failures inside the main window。

- [ ] **Step 1: 写日志脱敏和错误映射失败测试**

```rust
#[test]
fn diagnostics_redact_tokens_and_passwords() {
    let line = sanitize_log_line("token=abc password=secret Authorization: Bearer xyz");
    assert!(!line.contains("abc"));
    assert!(!line.contains("secret"));
    assert!(!line.contains("xyz"));
    assert!(line.contains("[REDACTED]"));
}

#[test]
fn launch_failures_keep_distinct_codes() {
    assert_eq!(map_runtime_error("bind failed").code, "DESKTOP_SETUP_RUNTIME_START_FAILED");
    assert_eq!(map_sidecar_error("health timeout").code, "DESKTOP_SETUP_SIDECAR_START_FAILED");
}
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd src-tauri
cargo test desktop_backend --lib
```

Expected: FAIL，脱敏和错误映射函数尚不存在。

- [ ] **Step 3: 写入最小诊断日志**

`desktop_backend.rs` 在每次阶段切换、启动失败和 sidecar stdout/stderr 事件时追加 UTF-8 日志。每条日志包含时间、phase、code、message，不记录 launch env、Manager token、账号密码、JWT、加密密钥或认证响应。

`sanitize_log_line` 至少覆盖大小写不敏感的：`password=`、`token=`、`authorization:`、`api_key=`、`secret=`。日志文件打开失败不得覆盖原启动错误，只在内存错误消息后追加“日志写入失败”。

- [ ] **Step 4: 实现路径打开和重试约束**

`desktop_open_path(kind)` 只接受 `root` 或 `logs`，目标从当前已校验配置推导，禁止前端传任意路径。调用 `app.shell().open(path.to_string_lossy(), None)`。

`desktop_retry_start` 只在 `failed` 状态生效，先停止残留 sidecar，再按当前配置重启；根配置无效时返回 `DESKTOP_SETUP_CONFIG_INVALID` 并保持 full setup。并发点击使用 launch generation 合并，不启动两套 Manager/sidecar。

- [ ] **Step 5: 运行验证并提交**

```bash
cd src-tauri
cargo fmt --check
cargo test desktop_backend --lib
cargo check
cd ../frontend
npm run test -- src/router/desktopGuard.spec.ts
npm run build:desktop
git add src-tauri/src/desktop_backend.rs frontend/src/views/DesktopSetupWizard.vue frontend/src/router/desktopGuard.spec.ts
git commit -m "fix(desktop): keep startup failures recoverable"
```

Expected: Runtime/sidecar 失败有不同诊断码，窗口不退出、不刷新循环、不暴露秘密。

---

### Task 8: 定向回归与 Windows 单安装包

**Files:**
- Verify existing: `scripts/build-desktop-windows.ps1`
- Build output: `dist-desktop/windows/ruijing-<version>-windows-x86_64-setup.exe`

**Interfaces:**
- Produces one user-installed Tauri executable; sidecar remains an internal bundled binary。

- [ ] **Step 1: 运行精简定向测试**

```bash
cd src-tauri
cargo test desktop_config --lib
cargo test desktop_backend --lib
cargo test local_runtime --lib
cargo check

cd ../backend
.venv/bin/python -m pytest -q \
  tests/test_desktop_sidecar.py \
  tests/test_code_runtime_local_runtime.py

cd ../frontend
npm run test -- \
  src/router/desktopGuard.spec.ts \
  src/components/v2/RailSidebar.spec.ts \
  src/stores/user.spec.ts \
  src/utils/desktop/guard.spec.ts
npm run build:desktop
```

Expected: 全部 PASS；测试仍集中在现有文件和 Rust 内联模块，没有新增散落测试文件。

- [ ] **Step 2: 检查桌面源码中不再存在旧初始化合同**

```bash
test ! -e frontend/src/composables/useOnboardingState.ts
test ! -e frontend/src/composables/useOnboardingState.spec.ts
rg -n "fetchOnboardingState|isOnboardingConfirmed|配置 LLM 模型|平台租户ID|API Key" \
  frontend/src/views/DesktopSetupWizard.vue \
  frontend/src/router/index.ts \
  frontend/src/stores/user.ts
```

Expected: 两个旧 composable 文件不存在，三个目标文件无旧向导和旧守卫命中。

```bash
rg -n "LocalRuntimeApiServer::start\(&data_dir|APAAS_WORKSPACE_ROOT.*workspaces|console=True" \
  src-tauri/src backend/desktop_sidecar.py backend/ruijing-sidecar.spec
```

Expected: 无命中。

- [ ] **Step 3: 在 Windows 工作区构建单一安装包**

```powershell
Set-Location D:\workspaces\d-ai-code\apaas-builder-ai
.\scripts\build-desktop-windows.ps1 -Version 0.2.37 -Bundle nsis -SkipInstall
```

Expected output:

```text
dist-desktop\windows\ruijing-0.2.37-windows-x86_64-setup.exe
```

用户只安装并启动该客户端；`ruijing-sidecar.exe` 仍由 Tauri bundle 内部管理，不作为第二个安装包或启动入口。

- [ ] **Step 4: 做最小人工冒烟清单**

1. 清除或临时改名系统 AppData 下的 `bootstrap.json`，启动后立即看到两步向导，而不是命令行或空白页。
2. 保持默认 AI中台和默认 `%USERPROFILE%\DolphinCode`，保存后依次看到“保存配置 / 启动本地环境 / 打开登录页”。
3. 登录页显示“AI中台 · om-demo.dfy.definesys.cn”，验证码链路保持现有行为。
4. 新建本地应用默认目录落在 `%USERPROFILE%\DolphinCode\applications\<应用编码>`。
5. Runtime 文件落在 `%USERPROFILE%\DolphinCode\.appdata\runtime`，不再出现 `LOCAL_RUNTIME_MANAGER_UNAVAILABLE`、路径逃逸或 journal 拒绝访问。
6. 登录页“更改登录服务”只显示服务选择，不再次询问目录；设置页修改服务后退出旧会话并重启 sidecar。
7. 人为让 sidecar 启动失败，应用窗口内显示 `DESKTOP_SETUP_SIDECAR_START_FAILED`、重试和日志入口，进程不退出且无控制台弹窗。

- [ ] **Step 5: 确认实现分支收口**

```bash
git status --short
```

Expected: 输出为空；Tasks 1-7 的小提交已经覆盖全部改动，不创建空的“最终集成”提交，也不提交 `dist-desktop/`、PyInstaller `dist/` 或 Tauri `target/` 生成物。

---

## Self-Review

- Spec coverage: Tasks 1-8 覆盖首次配置、四项服务展示、两项启用、默认地址、默认根目录、原子 pointer/config、packaged 启动页、Manager/sidecar 顺序、applications/runtime 路径、登录摘要、单步改服务、设置页、失败恢复、日志、Windows 无控制台和单安装包。
- Critical path check: Rust Manager `data_root` 与 Python `runtime_data_dir` 都是 `<root>/.appdata/runtime`；sidecar `data_dir` 保持 `<root>/.appdata`；应用默认目录是 `<root>/applications`。
- Placeholder scan: 无占位标记、模糊错误处理或未定义的接口步骤。
- Type consistency: `DesktopLoginMode` 只包含 `control_plane|apaas`；禁用服务只存在于 UI catalog；Rust/TypeScript phase、scope、command 和错误码名称一致。
- Test scope: 不新增前端/Python测试文件；只使用 Rust 内联测试和已有测试文件，符合减少测试文件的要求。
