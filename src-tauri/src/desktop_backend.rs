use crate::desktop_config::{
    default_root_dir, normalize_login_url, DesktopConfig, DesktopConfigError, DesktopConfigStore,
    DesktopLoginConfig, DesktopLoginMode, DesktopPaths, DesktopSetupInput,
};
use crate::local_runtime::api::LocalRuntimeApiServer;
use crate::local_runtime::process_driver::agent_runtime_executable;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::sync::{Mutex, MutexGuard};
use std::thread;
use std::time::Duration;
use tauri::{AppHandle, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

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

#[derive(Debug, Clone, Serialize, thiserror::Error)]
#[error("{message}")]
pub struct DesktopBackendError {
    pub code: String,
    pub message: String,
}

impl DesktopBackendError {
    fn config(message: impl Into<String>) -> Self {
        Self {
            code: "DESKTOP_SETUP_CONFIG_INVALID".to_string(),
            message: message.into(),
        }
    }

    fn service(message: impl Into<String>) -> Self {
        Self {
            code: "DESKTOP_SETUP_SERVICE_UNREACHABLE".to_string(),
            message: message.into(),
        }
    }

    fn runtime(message: impl Into<String>) -> Self {
        Self {
            code: "DESKTOP_SETUP_RUNTIME_START_FAILED".to_string(),
            message: message.into(),
        }
    }

    fn sidecar(message: impl Into<String>) -> Self {
        Self {
            code: "DESKTOP_SETUP_SIDECAR_START_FAILED".to_string(),
            message: message.into(),
        }
    }
}

impl From<DesktopConfigError> for DesktopBackendError {
    fn from(error: DesktopConfigError) -> Self {
        Self {
            code: error.code,
            message: error.message,
        }
    }
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
    env: BTreeMap<String, String>,
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
                "--port".into(),
                port.to_string(),
                "--data-dir".into(),
                paths.data_dir.to_string_lossy().into_owned(),
                "--applications-root".into(),
                paths.applications_dir.to_string_lossy().into_owned(),
                "--runtime-data-dir".into(),
                paths.runtime_dir.to_string_lossy().into_owned(),
                "--login-mode".into(),
                mode.into(),
                "--login-base-url".into(),
                config.login.base_url.clone(),
            ],
            env: [
                (
                    "DOLPHIN_LOCAL_RUNTIME_MANAGER_URL".into(),
                    manager_url.into(),
                ),
                (
                    "DOLPHIN_LOCAL_RUNTIME_MANAGER_TOKEN".into(),
                    manager_token.into(),
                ),
            ]
            .into_iter()
            .collect(),
        }
    }

    #[cfg(test)]
    fn arg_value(&self, key: &str) -> &str {
        let index = self
            .args
            .iter()
            .position(|item| item == key)
            .expect("argument exists");
        self.args.get(index + 1).expect("argument value exists")
    }
}

struct DesktopBackendInner {
    phase: DesktopPhase,
    setup_scope: DesktopSetupScope,
    config: Option<DesktopConfig>,
    error: Option<DesktopBackendError>,
    packaged_url: tauri::Url,
    launch_generation: u64,
    runtime: Option<LocalRuntimeApiServer>,
    sidecar: Option<CommandChild>,
}

pub struct DesktopBackend {
    inner: Mutex<DesktopBackendInner>,
    config_store: DesktopConfigStore,
    default_root_dir: PathBuf,
    agent_runtime_root: PathBuf,
}

impl DesktopBackend {
    fn new(
        config_store: DesktopConfigStore,
        default_root_dir: PathBuf,
        agent_runtime_root: PathBuf,
        packaged_url: tauri::Url,
    ) -> Self {
        Self {
            inner: Mutex::new(DesktopBackendInner {
                phase: DesktopPhase::NeedsSetup,
                setup_scope: DesktopSetupScope::Full,
                config: None,
                error: None,
                packaged_url,
                launch_generation: 0,
                runtime: None,
                sidecar: None,
            }),
            config_store,
            default_root_dir,
            agent_runtime_root,
        }
    }

    fn lock(&self) -> MutexGuard<'_, DesktopBackendInner> {
        self.inner
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
    }

    fn snapshot(&self) -> DesktopStateSnapshot {
        let inner = self.lock();
        DesktopStateSnapshot {
            phase: inner.phase,
            setup_scope: inner.setup_scope,
            config: inner.config.clone(),
            default_root_dir: self.default_root_dir.clone(),
            error: inner.error.clone(),
        }
    }
}

fn next_generation(inner: &mut DesktopBackendInner) -> u64 {
    inner.launch_generation = inner.launch_generation.wrapping_add(1);
    inner.launch_generation
}

fn packaged_agent_runtime_root(handle: &AppHandle) -> PathBuf {
    if let Some(path) = std::env::var_os("DOLPHIN_AGENT_RUNTIME_PATH") {
        let path: PathBuf = path.into();
        return path
            .parent()
            .and_then(Path::parent)
            .map(Path::to_path_buf)
            .unwrap_or(path);
    }
    handle
        .path()
        .resource_dir()
        .expect("resource directory is available")
        .join("agent-runtime")
}

fn pick_free_port() -> u16 {
    std::net::TcpListener::bind("127.0.0.1:0")
        .and_then(|listener| listener.local_addr())
        .map(|address| address.port())
        .unwrap_or(8799)
}

fn stable_port(data_dir: &Path) -> u16 {
    let port_file = data_dir.join("ui_port");
    if let Ok(contents) = std::fs::read_to_string(&port_file) {
        if let Ok(port) = contents.trim().parse::<u16>() {
            if port != 0 && std::net::TcpListener::bind(("127.0.0.1", port)).is_ok() {
                return port;
            }
        }
    }
    let port = pick_free_port();
    let _ = std::fs::create_dir_all(data_dir);
    let _ = std::fs::write(port_file, port.to_string());
    port
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum HealthStatus {
    Healthy,
    Cancelled,
    TimedOut,
}

fn launch_is_active(app: &AppHandle, generation: u64, phase: DesktopPhase) -> bool {
    let state = app.state::<DesktopBackend>();
    let inner = state.lock();
    inner.launch_generation == generation && inner.phase == phase
}

fn wait_healthy(app: &AppHandle, generation: u64, port: u16) -> HealthStatus {
    let url = format!("http://127.0.0.1:{port}/api/health");
    for _ in 0..60 {
        if !launch_is_active(app, generation, DesktopPhase::StartingSidecar) {
            return HealthStatus::Cancelled;
        }
        if let Ok(response) = ureq::get(&url).timeout(Duration::from_secs(2)).call() {
            if response.status() == 200 {
                return HealthStatus::Healthy;
            }
        }
        thread::sleep(Duration::from_secs(1));
    }
    HealthStatus::TimedOut
}

fn navigate_packaged(
    app: &AppHandle,
    packaged_url: &tauri::Url,
) -> Result<(), DesktopBackendError> {
    let window = app
        .get_webview_window("main")
        .ok_or_else(|| DesktopBackendError::sidecar("桌面主窗口不可用"))?;
    window
        .navigate(packaged_url.clone())
        .map_err(|error| DesktopBackendError::sidecar(format!("无法打开桌面启动页面: {error}")))
}

fn navigate_ready(app: &AppHandle, port: u16) -> Result<(), DesktopBackendError> {
    let window = app
        .get_webview_window("main")
        .ok_or_else(|| DesktopBackendError::sidecar("桌面主窗口不可用"))?;
    let url = tauri::Url::parse(&format!("http://127.0.0.1:{port}/"))
        .map_err(|error| DesktopBackendError::sidecar(format!("本地业务地址无效: {error}")))?;
    window
        .navigate(url)
        .map_err(|error| DesktopBackendError::sidecar(format!("无法打开本地业务页面: {error}")))
}

fn set_launch_failed(app: &AppHandle, generation: u64, error: DesktopBackendError) {
    let state = app.state::<DesktopBackend>();
    let mut inner = state.lock();
    if inner.launch_generation != generation {
        return;
    }
    inner.phase = DesktopPhase::Failed;
    inner.error = Some(error);
    let packaged_url = inner.packaged_url.clone();
    let _ = navigate_packaged(app, &packaged_url);
}

fn log_sidecar_events(
    app: AppHandle,
    generation: u64,
    mut rx: tauri::async_runtime::Receiver<CommandEvent>,
) {
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(bytes) => {
                    print!("[sidecar] {}", String::from_utf8_lossy(&bytes));
                }
                CommandEvent::Stderr(bytes) => {
                    eprint!("[sidecar] {}", String::from_utf8_lossy(&bytes));
                }
                CommandEvent::Error(error) => {
                    eprintln!("[sidecar] process stream error: {error}");
                }
                CommandEvent::Terminated(payload) => {
                    let message = match (payload.code, payload.signal) {
                        (Some(code), _) => format!("sidecar exited with code {code}"),
                        (_, Some(signal)) => format!("sidecar terminated by signal {signal}"),
                        _ => "sidecar terminated unexpectedly".to_string(),
                    };
                    let state = app.state::<DesktopBackend>();
                    let mut inner = state.lock();
                    if inner.launch_generation == generation
                        && matches!(
                            inner.phase,
                            DesktopPhase::StartingSidecar | DesktopPhase::Ready
                        )
                    {
                        inner.sidecar.take();
                        inner.phase = DesktopPhase::Failed;
                        inner.error = Some(DesktopBackendError::sidecar(message));
                        let packaged_url = inner.packaged_url.clone();
                        let _ = navigate_packaged(&app, &packaged_url);
                    }
                    break;
                }
                _ => {}
            }
        }
    });
}

fn spawn_sidecar(
    app: AppHandle,
    generation: u64,
    config: DesktopConfig,
    manager_url: String,
    manager_token: String,
) {
    thread::spawn(move || {
        if !launch_is_active(&app, generation, DesktopPhase::StartingSidecar) {
            return;
        }

        let paths = DesktopPaths::from_root(config.root_dir.clone());
        let port = stable_port(&paths.data_dir);
        let state = app.state::<DesktopBackend>();
        let agent_runtime_path = agent_runtime_executable(&state.agent_runtime_root);
        let launch =
            SidecarLaunch::from_config(&config, port, manager_url.as_str(), manager_token.as_str());
        let mut command = match app.shell().sidecar("ruijing-sidecar") {
            Ok(command) => command.args(launch.args),
            Err(error) => {
                set_launch_failed(
                    &app,
                    generation,
                    DesktopBackendError::sidecar(format!("找不到桌面 sidecar: {error}")),
                );
                return;
            }
        };
        for (key, value) in launch.env {
            command = command.env(key, value);
        }
        command = command
            .env(
                "DOLPHIN_DESKTOP_DATA_DIR",
                paths.data_dir.to_string_lossy().as_ref(),
            )
            .env(
                "DOLPHIN_AGENT_RUNTIME_PATH",
                agent_runtime_path.to_string_lossy().as_ref(),
            )
            .env("CODING_USE_RUNAGENT", "1");

        let (rx, child) = match command.spawn() {
            Ok(result) => result,
            Err(error) => {
                set_launch_failed(
                    &app,
                    generation,
                    DesktopBackendError::sidecar(format!("无法启动桌面 sidecar: {error}")),
                );
                return;
            }
        };
        let mut child = Some(child);
        let replaced_child = {
            let state = app.state::<DesktopBackend>();
            let mut inner = state.lock();
            if inner.launch_generation != generation || inner.phase != DesktopPhase::StartingSidecar
            {
                None
            } else {
                inner
                    .sidecar
                    .replace(child.take().expect("spawned child exists"))
            }
        };
        if let Some(child) = child {
            stop_sidecar(child);
            return;
        }
        if let Some(child) = replaced_child {
            stop_sidecar(child);
        }
        log_sidecar_events(app.clone(), generation, rx);

        match wait_healthy(&app, generation, port) {
            HealthStatus::Healthy => {
                let state = app.state::<DesktopBackend>();
                let mut inner = state.lock();
                if inner.launch_generation != generation
                    || inner.phase != DesktopPhase::StartingSidecar
                {
                    return;
                }
                if let Err(error) = navigate_ready(&app, port) {
                    let child = inner.sidecar.take();
                    inner.phase = DesktopPhase::Failed;
                    inner.error = Some(error);
                    let packaged_url = inner.packaged_url.clone();
                    let _ = navigate_packaged(&app, &packaged_url);
                    drop(inner);
                    if let Some(child) = child {
                        stop_sidecar(child);
                    }
                    return;
                }
                inner.phase = DesktopPhase::Ready;
                inner.error = None;
            }
            HealthStatus::TimedOut => {
                let state = app.state::<DesktopBackend>();
                let child = {
                    let mut inner = state.lock();
                    if inner.launch_generation != generation
                        || inner.phase != DesktopPhase::StartingSidecar
                    {
                        None
                    } else {
                        let child = inner.sidecar.take();
                        inner.phase = DesktopPhase::Failed;
                        inner.error = Some(DesktopBackendError::sidecar("sidecar 健康检查超时"));
                        let packaged_url = inner.packaged_url.clone();
                        let _ = navigate_packaged(&app, &packaged_url);
                        child
                    }
                };
                if let Some(child) = child {
                    stop_sidecar(child);
                }
            }
            HealthStatus::Cancelled => {}
        }
    });
}

fn spawn_full_start(app: AppHandle, generation: u64, config: DesktopConfig) {
    thread::spawn(move || {
        if !launch_is_active(&app, generation, DesktopPhase::StartingRuntime) {
            return;
        }

        let paths = DesktopPaths::from_root(config.root_dir.clone());
        let agent_runtime_root = {
            let state = app.state::<DesktopBackend>();
            state.agent_runtime_root.clone()
        };
        let manager = match LocalRuntimeApiServer::start(&paths.runtime_dir, &agent_runtime_root) {
            Ok(manager) => manager,
            Err(error) => {
                set_launch_failed(
                    &app,
                    generation,
                    DesktopBackendError::runtime(format!(
                        "无法启动本地 Runtime Manager: {}",
                        error.message
                    )),
                );
                return;
            }
        };
        let manager_url = manager.base_url.clone();
        let manager_token = manager.token.clone();
        let mut manager = Some(manager);

        let accepted = {
            let state = app.state::<DesktopBackend>();
            let mut inner = state.lock();
            if inner.launch_generation == generation && inner.phase == DesktopPhase::StartingRuntime
            {
                inner.runtime = manager.take();
                inner.phase = DesktopPhase::StartingSidecar;
                true
            } else {
                false
            }
        };
        if !accepted {
            if let Some(mut manager) = manager {
                manager.shutdown();
            }
            return;
        }

        spawn_sidecar(app, generation, config, manager_url, manager_token);
    });
}

fn start_initial_config(app: AppHandle) {
    let state = app.state::<DesktopBackend>();
    match state.config_store.load() {
        Ok(None) => {
            let mut inner = state.lock();
            inner.phase = DesktopPhase::NeedsSetup;
            inner.setup_scope = DesktopSetupScope::Full;
            inner.config = None;
            inner.error = None;
        }
        Err(error) => {
            let mut inner = state.lock();
            inner.phase = DesktopPhase::NeedsSetup;
            inner.setup_scope = DesktopSetupScope::Full;
            inner.config = None;
            inner.error = Some(error.into());
        }
        Ok(Some(saved)) => {
            let config = saved.config;
            let generation = {
                let mut inner = state.lock();
                let generation = next_generation(&mut inner);
                inner.phase = DesktopPhase::StartingRuntime;
                inner.setup_scope = DesktopSetupScope::Full;
                inner.config = Some(config.clone());
                inner.error = None;
                generation
            };
            spawn_full_start(app, generation, config);
        }
    }
}

pub fn setup(app: &mut tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    let window = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
        .title("睿鲸 Builder")
        .inner_size(1440.0, 900.0)
        .visible(true)
        .disable_drag_drop_handler()
        .build()?;
    let packaged_url = window.url()?;
    let handle = app.handle().clone();
    let system_data_dir = handle.path().app_data_dir()?;
    let home_dir = handle.path().home_dir()?;
    app.manage(DesktopBackend::new(
        DesktopConfigStore::new(system_data_dir),
        default_root_dir(&home_dir),
        packaged_agent_runtime_root(&handle),
        packaged_url,
    ));
    start_initial_config(handle);
    Ok(())
}

#[tauri::command]
pub fn desktop_get_state(state: tauri::State<'_, DesktopBackend>) -> DesktopStateSnapshot {
    state.snapshot()
}

#[tauri::command]
pub fn desktop_save_setup(
    app: tauri::AppHandle,
    state: tauri::State<'_, DesktopBackend>,
    input: DesktopSetupInput,
) -> Result<DesktopStateSnapshot, DesktopBackendError> {
    let (generation, sidecar, runtime) = {
        let mut inner = state.lock();
        let generation = next_generation(&mut inner);
        inner.phase = DesktopPhase::SavingConfig;
        inner.setup_scope = DesktopSetupScope::Full;
        inner.error = None;
        (generation, inner.sidecar.take(), inner.runtime.take())
    };
    if let Some(sidecar) = sidecar {
        stop_sidecar(sidecar);
    }
    if let Some(mut runtime) = runtime {
        runtime.shutdown();
    }

    let saved = match state.config_store.save(input) {
        Ok(saved) => saved,
        Err(error) => {
            let error: DesktopBackendError = error.into();
            let mut inner = state.lock();
            if inner.launch_generation == generation {
                inner.phase = DesktopPhase::NeedsSetup;
                inner.setup_scope = DesktopSetupScope::Full;
                inner.error = Some(error.clone());
            }
            return Err(error);
        }
    };
    let config = saved.config;
    let launch_is_current = {
        let mut inner = state.lock();
        if inner.launch_generation != generation {
            false
        } else {
            inner.phase = DesktopPhase::StartingRuntime;
            inner.config = Some(config.clone());
            inner.error = None;
            true
        }
    };
    if !launch_is_current {
        return Ok(state.snapshot());
    }
    spawn_full_start(app, generation, config);
    Ok(state.snapshot())
}

#[tauri::command]
pub fn desktop_test_service(login: DesktopLoginConfig) -> Result<(), DesktopBackendError> {
    let url = normalize_login_url(&login.base_url).map_err(DesktopBackendError::from)?;
    let agent = ureq::AgentBuilder::new()
        .redirects(0)
        .timeout(Duration::from_secs(5))
        .build();
    match agent.get(&url).call() {
        Ok(response) if (200..500).contains(&response.status()) => Ok(()),
        Err(ureq::Error::Status(status, _)) if (200..500).contains(&status) => Ok(()),
        Ok(response) => Err(DesktopBackendError::service(format!(
            "服务返回不可用状态码 {}",
            response.status()
        ))),
        Err(ureq::Error::Status(status, _)) => Err(DesktopBackendError::service(format!(
            "服务返回不可用状态码 {status}"
        ))),
        Err(error) => Err(DesktopBackendError::service(format!(
            "无法连接登录服务: {error}"
        ))),
    }
}

#[tauri::command]
pub fn desktop_enter_login_setup(
    app: tauri::AppHandle,
    state: tauri::State<'_, DesktopBackend>,
) -> Result<(), DesktopBackendError> {
    let (sidecar, navigation_result) = {
        let mut inner = state.lock();
        if inner.config.is_none() {
            return Err(DesktopBackendError::config("桌面配置尚未初始化"));
        }
        next_generation(&mut inner);
        inner.phase = DesktopPhase::NeedsSetup;
        inner.setup_scope = DesktopSetupScope::LoginOnly;
        inner.error = None;
        let packaged_url = inner.packaged_url.clone();
        let navigation_result = navigate_packaged(&app, &packaged_url);
        (inner.sidecar.take(), navigation_result)
    };
    if let Some(sidecar) = sidecar {
        stop_sidecar(sidecar);
    }
    navigation_result
}

#[tauri::command]
pub fn desktop_retry_start(
    app: tauri::AppHandle,
    state: tauri::State<'_, DesktopBackend>,
) -> Result<DesktopStateSnapshot, DesktopBackendError> {
    let (generation, sidecar, previous_root) = {
        let mut inner = state.lock();
        if inner.phase != DesktopPhase::Failed {
            drop(inner);
            return Ok(state.snapshot());
        }
        let generation = next_generation(&mut inner);
        inner.phase = DesktopPhase::StartingRuntime;
        inner.error = None;
        (
            generation,
            inner.sidecar.take(),
            inner.config.as_ref().map(|config| config.root_dir.clone()),
        )
    };
    if let Some(sidecar) = sidecar {
        stop_sidecar(sidecar);
    }

    let saved = match state.config_store.load() {
        Ok(Some(saved)) => saved,
        Ok(None) => {
            let error = DesktopBackendError::config("桌面配置尚未初始化");
            let runtime = {
                let mut inner = state.lock();
                if inner.launch_generation == generation {
                    inner.phase = DesktopPhase::NeedsSetup;
                    inner.setup_scope = DesktopSetupScope::Full;
                    inner.config = None;
                    inner.error = Some(error.clone());
                    inner.runtime.take()
                } else {
                    None
                }
            };
            if let Some(mut runtime) = runtime {
                runtime.shutdown();
            }
            return Err(error);
        }
        Err(error) => {
            let error: DesktopBackendError = error.into();
            let runtime = {
                let mut inner = state.lock();
                if inner.launch_generation == generation {
                    inner.phase = DesktopPhase::NeedsSetup;
                    inner.setup_scope = DesktopSetupScope::Full;
                    inner.error = Some(error.clone());
                    inner.runtime.take()
                } else {
                    None
                }
            };
            if let Some(mut runtime) = runtime {
                runtime.shutdown();
            }
            return Err(error);
        }
    };

    let config = saved.config;
    let mut stale_runtime = None;
    let (launch_is_current, manager_credentials) = {
        let mut inner = state.lock();
        if inner.launch_generation != generation {
            (false, None)
        } else {
            inner.config = Some(config.clone());
            if previous_root.as_ref() != Some(&config.root_dir) {
                stale_runtime = inner.runtime.take();
            }
            let manager_credentials = if inner.runtime.is_some() {
                let credentials = inner
                    .runtime
                    .as_ref()
                    .map(|runtime| (runtime.base_url.clone(), runtime.token.clone()))
                    .expect("runtime was checked above");
                inner.phase = DesktopPhase::StartingSidecar;
                Some(credentials)
            } else {
                inner.phase = DesktopPhase::StartingRuntime;
                None
            };
            (true, manager_credentials)
        }
    };
    if !launch_is_current {
        return Ok(state.snapshot());
    }
    if let Some(mut runtime) = stale_runtime {
        runtime.shutdown();
    }
    if let Some((manager_url, manager_token)) = manager_credentials {
        spawn_sidecar(app, generation, config, manager_url, manager_token);
    } else {
        spawn_full_start(app, generation, config);
    }
    Ok(state.snapshot())
}

#[tauri::command]
pub fn desktop_update_login(
    app: tauri::AppHandle,
    state: tauri::State<'_, DesktopBackend>,
    login: DesktopLoginConfig,
) -> Result<DesktopStateSnapshot, DesktopBackendError> {
    let (generation, root_dir, sidecar, navigation_result) = {
        let mut inner = state.lock();
        let root_dir = inner
            .config
            .as_ref()
            .map(|config| config.root_dir.clone())
            .ok_or_else(|| DesktopBackendError::config("桌面配置尚未初始化"))?;
        let generation = next_generation(&mut inner);
        inner.phase = DesktopPhase::SavingConfig;
        inner.setup_scope = DesktopSetupScope::LoginOnly;
        inner.error = None;
        let packaged_url = inner.packaged_url.clone();
        let navigation_result = navigate_packaged(&app, &packaged_url);
        (
            generation,
            root_dir,
            inner.sidecar.take(),
            navigation_result,
        )
    };
    if let Some(sidecar) = sidecar {
        stop_sidecar(sidecar);
    }
    if let Err(error) = navigation_result {
        let mut inner = state.lock();
        if inner.launch_generation == generation {
            inner.phase = DesktopPhase::Failed;
            inner.error = Some(error.clone());
        }
        return Err(error);
    }

    let saved = match state.config_store.save(DesktopSetupInput {
        root_dir: root_dir.to_string_lossy().into_owned(),
        login,
    }) {
        Ok(saved) => saved,
        Err(error) => {
            let error: DesktopBackendError = error.into();
            let mut inner = state.lock();
            if inner.launch_generation == generation {
                inner.phase = DesktopPhase::NeedsSetup;
                inner.setup_scope = DesktopSetupScope::LoginOnly;
                inner.error = Some(error.clone());
            }
            return Err(error);
        }
    };
    let config = saved.config;
    let (launch_is_current, manager_credentials) = {
        let mut inner = state.lock();
        if inner.launch_generation != generation {
            (false, None)
        } else {
            inner.config = Some(config.clone());
            inner.error = None;
            let manager_credentials = if inner.runtime.is_some() {
                let credentials = inner
                    .runtime
                    .as_ref()
                    .map(|runtime| (runtime.base_url.clone(), runtime.token.clone()))
                    .expect("runtime was checked above");
                inner.phase = DesktopPhase::StartingSidecar;
                Some(credentials)
            } else {
                inner.phase = DesktopPhase::StartingRuntime;
                None
            };
            (true, manager_credentials)
        }
    };
    if !launch_is_current {
        return Ok(state.snapshot());
    }
    if let Some((manager_url, manager_token)) = manager_credentials {
        spawn_sidecar(app, generation, config, manager_url, manager_token);
    } else {
        spawn_full_start(app, generation, config);
    }
    Ok(state.snapshot())
}

#[tauri::command]
#[allow(deprecated)]
pub fn desktop_open_path(
    app: tauri::AppHandle,
    state: tauri::State<'_, DesktopBackend>,
    kind: DesktopPathKind,
) -> Result<(), DesktopBackendError> {
    let target = {
        let inner = state.lock();
        let config = inner
            .config
            .as_ref()
            .ok_or_else(|| DesktopBackendError::config("桌面配置尚未初始化"))?;
        let paths = DesktopPaths::from_root(config.root_dir.clone());
        match kind {
            DesktopPathKind::Root => paths.root_dir,
            DesktopPathKind::Logs => paths.logs_dir,
        }
    };
    app.shell()
        .open(target.to_string_lossy(), None)
        .map_err(|error| DesktopBackendError::config(format!("无法打开路径: {error}")))
}

pub fn handle_run_event(app: &AppHandle, event: RunEvent) {
    if !matches!(event, RunEvent::ExitRequested { .. } | RunEvent::Exit) {
        return;
    }
    let state = app.state::<DesktopBackend>();
    let (sidecar, runtime) = {
        let mut inner = state.lock();
        next_generation(&mut inner);
        (inner.sidecar.take(), inner.runtime.take())
    };
    if let Some(sidecar) = sidecar {
        stop_sidecar(sidecar);
    }
    if let Some(mut runtime) = runtime {
        runtime.shutdown();
    }
}

fn stop_sidecar(child: CommandChild) {
    let pid = child.pid();
    kill_sidecar_deep(pid);
    let _ = child.kill();
}

fn kill_sidecar_deep(bootloader_pid: u32) {
    #[cfg(windows)]
    {
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        let _ = std::process::Command::new("taskkill")
            .args(["/PID", &bootloader_pid.to_string(), "/T", "/F"])
            .creation_flags(CREATE_NO_WINDOW)
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }

    #[cfg(unix)]
    {
        let mut child_pids = Vec::new();
        if let Ok(output) = std::process::Command::new("pgrep")
            .args(["-P", &bootloader_pid.to_string()])
            .output()
        {
            for line in String::from_utf8_lossy(&output.stdout).lines() {
                if let Ok(child_pid) = line.trim().parse::<u32>() {
                    child_pids.push(child_pid);
                }
            }
        }
        let _ = std::process::Command::new("kill")
            .args(["-KILL", &bootloader_pid.to_string()])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
        for child_pid in child_pids {
            let _ = std::process::Command::new("kill")
                .args(["-KILL", &child_pid.to_string()])
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .status();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::desktop_config::{DesktopConfig, DesktopLoginConfig, DesktopLoginMode};
    use std::io::Write;
    use std::net::TcpListener;
    use std::path::PathBuf;

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
        assert_eq!(
            launch.arg_value("--applications-root"),
            applications.to_string_lossy().as_ref()
        );
        assert_eq!(
            launch.arg_value("--runtime-data-dir"),
            runtime.to_string_lossy().as_ref()
        );
        assert_eq!(launch.arg_value("--login-mode"), "control_plane");
        assert_eq!(
            launch.arg_value("--login-base-url"),
            "https://om-demo.dfy.definesys.cn"
        );
    }

    #[test]
    fn failed_runtime_does_not_collapse_to_legacy_manager_unavailable() {
        let error = DesktopBackendError::runtime("cannot bind local runtime manager");
        assert_eq!(error.code, "DESKTOP_SETUP_RUNTIME_START_FAILED");
        assert!(!error.message.contains("LOCAL_RUNTIME_MANAGER_UNAVAILABLE"));
    }

    #[test]
    fn service_test_treats_redirect_response_as_reachable() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            stream
                .write_all(
                    b"HTTP/1.1 302 Found\r\nLocation: http://127.0.0.1:1/unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
                )
                .unwrap();
        });

        let result = desktop_test_service(DesktopLoginConfig {
            mode: DesktopLoginMode::ControlPlane,
            base_url: format!("http://{address}"),
        });
        server.join().unwrap();

        assert!(
            result.is_ok(),
            "redirect response must be reachable: {result:?}"
        );
    }
}
