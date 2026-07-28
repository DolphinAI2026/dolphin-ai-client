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
use std::sync::mpsc::{self, Receiver, Sender};
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

#[derive(Debug, Default)]
struct LifecycleLeaseState {
    desired_generation: u64,
    active_generation: Option<u64>,
}

impl LifecycleLeaseState {
    fn request_generation(&mut self) -> u64 {
        self.desired_generation = self.desired_generation.wrapping_add(1);
        if self.desired_generation == 0 {
            self.desired_generation = 1;
        }
        self.desired_generation
    }

    fn try_begin(&mut self, generation: u64) -> bool {
        if self.active_generation.is_none() && self.desired_generation == generation {
            self.active_generation = Some(generation);
            true
        } else {
            false
        }
    }

    fn is_desired(&self, generation: u64) -> bool {
        self.desired_generation == generation
    }

    fn is_active_current(&self, generation: u64) -> bool {
        self.active_generation == Some(generation) && self.desired_generation == generation
    }

    fn finish(&mut self, generation: u64) {
        if self.active_generation == Some(generation) {
            self.active_generation = None;
        }
    }

    #[cfg(test)]
    fn active_generation(&self) -> Option<u64> {
        self.active_generation
    }
}

enum LifecycleIntent {
    Initialize {
        generation: u64,
    },
    SaveSetup {
        generation: u64,
        input: DesktopSetupInput,
    },
    Retry {
        generation: u64,
    },
    EnterLoginSetup {
        generation: u64,
    },
    UpdateLogin {
        generation: u64,
        login: DesktopLoginConfig,
    },
    SidecarTerminated {
        generation: u64,
        error: DesktopBackendError,
    },
    Shutdown {
        generation: u64,
    },
}

impl LifecycleIntent {
    fn generation(&self) -> u64 {
        match self {
            Self::Initialize { generation }
            | Self::SaveSetup { generation, .. }
            | Self::Retry { generation }
            | Self::EnterLoginSetup { generation }
            | Self::UpdateLogin { generation, .. }
            | Self::SidecarTerminated { generation, .. }
            | Self::Shutdown { generation } => *generation,
        }
    }
}

#[derive(Clone)]
struct LifecycleSupervisor {
    sender: Sender<LifecycleIntent>,
}

impl LifecycleSupervisor {
    fn channel() -> (Self, Receiver<LifecycleIntent>) {
        let (sender, receiver) = mpsc::channel();
        (Self { sender }, receiver)
    }

    fn submit(&self, intent: LifecycleIntent) -> Result<(), DesktopBackendError> {
        self.sender
            .send(intent)
            .map_err(|_| DesktopBackendError::runtime("桌面生命周期服务不可用，请重新启动应用"))
    }
}

struct DesktopBackendInner {
    phase: DesktopPhase,
    setup_scope: DesktopSetupScope,
    config: Option<DesktopConfig>,
    error: Option<DesktopBackendError>,
    packaged_url: tauri::Url,
    lease: LifecycleLeaseState,
    runtime: Option<LocalRuntimeApiServer>,
    sidecar: Option<CommandChild>,
    pending_sidecar_error: Option<(u64, DesktopBackendError)>,
    shutdown_requested: bool,
    shutdown_complete: bool,
}

pub struct DesktopBackend {
    inner: Mutex<DesktopBackendInner>,
    config_store: DesktopConfigStore,
    default_root_dir: PathBuf,
    agent_runtime_root: PathBuf,
    supervisor: LifecycleSupervisor,
}

impl DesktopBackend {
    fn new(
        config_store: DesktopConfigStore,
        default_root_dir: PathBuf,
        agent_runtime_root: PathBuf,
        packaged_url: tauri::Url,
        supervisor: LifecycleSupervisor,
    ) -> Self {
        Self {
            inner: Mutex::new(DesktopBackendInner {
                phase: DesktopPhase::NeedsSetup,
                setup_scope: DesktopSetupScope::Full,
                config: None,
                error: None,
                packaged_url,
                lease: LifecycleLeaseState::default(),
                runtime: None,
                sidecar: None,
                pending_sidecar_error: None,
                shutdown_requested: false,
                shutdown_complete: false,
            }),
            config_store,
            default_root_dir,
            agent_runtime_root,
            supervisor,
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

    fn submit(&self, intent: LifecycleIntent) -> Result<(), DesktopBackendError> {
        self.supervisor.submit(intent)
    }

    fn begin_operation(&self, generation: u64) -> bool {
        self.lock().lease.try_begin(generation)
    }

    fn finish_operation(&self, generation: u64) {
        self.lock().lease.finish(generation);
    }

    fn operation_is_current(&self, generation: u64, phase: DesktopPhase) -> bool {
        let inner = self.lock();
        inner.lease.is_active_current(generation) && inner.phase == phase
    }

    fn generation_is_desired(&self, generation: u64) -> bool {
        self.lock().lease.is_desired(generation)
    }
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

#[derive(Debug, Clone)]
enum HealthStatus {
    Healthy,
    Cancelled,
    TimedOut,
    Terminated(DesktopBackendError),
}

fn operation_is_current(app: &AppHandle, generation: u64, phase: DesktopPhase) -> bool {
    let state = app.state::<DesktopBackend>();
    state.operation_is_current(generation, phase)
}

fn wait_healthy(app: &AppHandle, generation: u64, port: u16) -> HealthStatus {
    let url = format!("http://127.0.0.1:{port}/api/health");
    for _ in 0..60 {
        if !operation_is_current(app, generation, DesktopPhase::StartingSidecar) {
            return HealthStatus::Cancelled;
        }
        let pending_error = {
            let state = app.state::<DesktopBackend>();
            let inner = state.lock();
            inner
                .pending_sidecar_error
                .as_ref()
                .filter(|(error_generation, _)| *error_generation == generation)
                .map(|(_, error)| error.clone())
        };
        if let Some(error) = pending_error {
            return HealthStatus::Terminated(error);
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
    let packaged_url = {
        let mut inner = state.lock();
        if !inner.lease.is_active_current(generation) {
            return;
        }
        inner.phase = DesktopPhase::Failed;
        inner.error = Some(error);
        inner.packaged_url.clone()
    };
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
                    let error = DesktopBackendError::sidecar(message);
                    let state = app.state::<DesktopBackend>();
                    {
                        let mut inner = state.lock();
                        if inner.lease.is_desired(generation)
                            && matches!(
                                inner.phase,
                                DesktopPhase::StartingSidecar | DesktopPhase::Ready
                            )
                        {
                            inner.pending_sidecar_error = Some((generation, error.clone()));
                        }
                    }
                    let _ = state.submit(LifecycleIntent::SidecarTerminated { generation, error });
                    break;
                }
                _ => {}
            }
        }
    });
}

fn spawn_sidecar(
    app: &AppHandle,
    generation: u64,
    config: &DesktopConfig,
    manager_url: String,
    manager_token: String,
) {
    if !operation_is_current(app, generation, DesktopPhase::StartingSidecar) {
        return;
    }

    let paths = DesktopPaths::from_root(config.root_dir.clone());
    let port = stable_port(&paths.data_dir);
    let state = app.state::<DesktopBackend>();
    let agent_runtime_path = agent_runtime_executable(&state.agent_runtime_root);
    let launch =
        SidecarLaunch::from_config(config, port, manager_url.as_str(), manager_token.as_str());
    let mut command = match app.shell().sidecar("ruijing-sidecar") {
        Ok(command) => command.args(launch.args),
        Err(error) => {
            set_launch_failed(
                app,
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
                app,
                generation,
                DesktopBackendError::sidecar(format!("无法启动桌面 sidecar: {error}")),
            );
            return;
        }
    };
    if !operation_is_current(app, generation, DesktopPhase::StartingSidecar) {
        stop_sidecar(child);
        return;
    }
    let replaced_child = {
        let mut inner = state.lock();
        inner.sidecar.replace(child)
    };
    if let Some(child) = replaced_child {
        stop_sidecar(child);
    }
    log_sidecar_events(app.clone(), generation, rx);

    let health = wait_healthy(app, generation, port);
    match health {
        HealthStatus::Healthy => {
            if !operation_is_current(app, generation, DesktopPhase::StartingSidecar) {
                let child = state.lock().sidecar.take();
                if let Some(child) = child {
                    stop_sidecar(child);
                }
                return;
            }
            if let Err(error) = navigate_ready(app, port) {
                let child = {
                    let mut inner = state.lock();
                    let child = inner.sidecar.take();
                    if inner.lease.is_active_current(generation) {
                        inner.phase = DesktopPhase::Failed;
                        inner.error = Some(error);
                    }
                    child
                };
                if let Some(child) = child {
                    stop_sidecar(child);
                }
                return;
            }
            let mut inner = state.lock();
            if inner.lease.is_active_current(generation) {
                inner.phase = DesktopPhase::Ready;
                inner.error = None;
                inner.pending_sidecar_error = None;
            }
        }
        HealthStatus::TimedOut | HealthStatus::Terminated(_) => {
            let error = match health {
                HealthStatus::Terminated(error) => error,
                _ => DesktopBackendError::sidecar("sidecar 健康检查超时"),
            };
            let child = {
                let mut inner = state.lock();
                let child = inner.sidecar.take();
                if inner.lease.is_active_current(generation) {
                    inner.phase = DesktopPhase::Failed;
                    inner.error = Some(error);
                    inner.pending_sidecar_error = None;
                }
                child
            };
            if let Some(child) = child {
                stop_sidecar(child);
            }
            let packaged_url = state.lock().packaged_url.clone();
            let _ = navigate_packaged(app, &packaged_url);
        }
        HealthStatus::Cancelled => {
            let child = state.lock().sidecar.take();
            if let Some(child) = child {
                stop_sidecar(child);
            }
        }
    }
}

fn run_full_start(app: &AppHandle, generation: u64, config: &DesktopConfig) {
    if !operation_is_current(app, generation, DesktopPhase::StartingRuntime) {
        return;
    }
    let state = app.state::<DesktopBackend>();
    let paths = DesktopPaths::from_root(config.root_dir.clone());
    let mut manager =
        match LocalRuntimeApiServer::start(&paths.runtime_dir, state.agent_runtime_root.clone()) {
            Ok(manager) => manager,
            Err(error) => {
                set_launch_failed(
                    app,
                    generation,
                    DesktopBackendError::runtime(format!(
                        "无法启动本地 Runtime Manager: {}",
                        error.message
                    )),
                );
                return;
            }
        };
    if !operation_is_current(app, generation, DesktopPhase::StartingRuntime) {
        manager.shutdown();
        return;
    }

    let manager_url = manager.base_url.clone();
    let manager_token = manager.token.clone();
    {
        let mut inner = state.lock();
        if !inner.lease.is_active_current(generation) {
            drop(inner);
            manager.shutdown();
            return;
        }
        inner.runtime = Some(manager);
        inner.phase = DesktopPhase::StartingSidecar;
    }
    spawn_sidecar(app, generation, config, manager_url, manager_token);
}

fn stop_resources(sidecar: Option<CommandChild>, runtime: Option<LocalRuntimeApiServer>) {
    if let Some(sidecar) = sidecar {
        stop_sidecar(sidecar);
    }
    if let Some(mut runtime) = runtime {
        runtime.shutdown();
    }
}

fn run_initialize(app: &AppHandle, generation: u64) {
    let state = app.state::<DesktopBackend>();
    match state.config_store.load() {
        Ok(None) => {
            let mut inner = state.lock();
            if inner.lease.is_active_current(generation) {
                inner.phase = DesktopPhase::NeedsSetup;
                inner.setup_scope = DesktopSetupScope::Full;
                inner.config = None;
                inner.error = None;
            }
        }
        Err(error) => {
            let mut inner = state.lock();
            if inner.lease.is_active_current(generation) {
                inner.phase = DesktopPhase::NeedsSetup;
                inner.setup_scope = DesktopSetupScope::Full;
                inner.config = None;
                inner.error = Some(error.into());
            }
        }
        Ok(Some(saved)) => {
            let config = saved.config;
            {
                let mut inner = state.lock();
                if !inner.lease.is_active_current(generation) {
                    return;
                }
                inner.phase = DesktopPhase::StartingRuntime;
                inner.setup_scope = DesktopSetupScope::Full;
                inner.config = Some(config.clone());
                inner.error = None;
            }
            run_full_start(app, generation, &config);
        }
    }
}

fn run_save_setup(app: &AppHandle, generation: u64, input: DesktopSetupInput) {
    let state = app.state::<DesktopBackend>();
    let (sidecar, runtime) = {
        let mut inner = state.lock();
        (inner.sidecar.take(), inner.runtime.take())
    };
    stop_resources(sidecar, runtime);
    if !state.operation_is_current(generation, DesktopPhase::SavingConfig) {
        return;
    }
    let saved = match state.config_store.save(input) {
        Ok(saved) => saved,
        Err(error) => {
            let mut inner = state.lock();
            if inner.lease.is_active_current(generation) {
                inner.phase = DesktopPhase::NeedsSetup;
                inner.setup_scope = DesktopSetupScope::Full;
                inner.error = Some(error.into());
            }
            return;
        }
    };
    let config = saved.config;
    {
        let mut inner = state.lock();
        if !inner.lease.is_active_current(generation) {
            return;
        }
        inner.phase = DesktopPhase::StartingRuntime;
        inner.config = Some(config.clone());
        inner.error = None;
    }
    run_full_start(app, generation, &config);
}

fn run_enter_login_setup(app: &AppHandle, generation: u64) {
    let state = app.state::<DesktopBackend>();
    let packaged_url = state.lock().packaged_url.clone();
    let navigation_result = navigate_packaged(app, &packaged_url);
    let sidecar = state.lock().sidecar.take();
    if let Some(sidecar) = sidecar {
        stop_sidecar(sidecar);
    }
    if let Err(error) = navigation_result {
        let mut inner = state.lock();
        if inner.lease.is_active_current(generation) {
            inner.phase = DesktopPhase::Failed;
            inner.error = Some(error);
        }
    }
}

fn run_retry(app: &AppHandle, generation: u64) {
    let state = app.state::<DesktopBackend>();
    let previous_root = state
        .lock()
        .config
        .as_ref()
        .map(|config| config.root_dir.clone());
    let sidecar = state.lock().sidecar.take();
    if let Some(sidecar) = sidecar {
        stop_sidecar(sidecar);
    }
    if !state.operation_is_current(generation, DesktopPhase::StartingRuntime) {
        return;
    }
    let saved = match state.config_store.load() {
        Ok(Some(saved)) => saved,
        Ok(None) => {
            let runtime = {
                let mut inner = state.lock();
                let runtime = inner.runtime.take();
                if inner.lease.is_active_current(generation) {
                    inner.phase = DesktopPhase::NeedsSetup;
                    inner.setup_scope = DesktopSetupScope::Full;
                    inner.config = None;
                    inner.error = Some(DesktopBackendError::config("桌面配置尚未初始化"));
                }
                runtime
            };
            stop_resources(None, runtime);
            return;
        }
        Err(error) => {
            let runtime = {
                let mut inner = state.lock();
                let runtime = inner.runtime.take();
                if inner.lease.is_active_current(generation) {
                    inner.phase = DesktopPhase::NeedsSetup;
                    inner.setup_scope = DesktopSetupScope::Full;
                    inner.error = Some(error.into());
                }
                runtime
            };
            stop_resources(None, runtime);
            return;
        }
    };
    let config = saved.config;
    let stale_runtime = {
        let mut inner = state.lock();
        if !inner.lease.is_active_current(generation) {
            return;
        }
        inner.config = Some(config.clone());
        if previous_root.as_ref() != Some(&config.root_dir) {
            inner.runtime.take()
        } else {
            None
        }
    };
    stop_resources(None, stale_runtime);
    if !state.generation_is_desired(generation) {
        return;
    }
    let manager_credentials = {
        let mut inner = state.lock();
        if let Some(runtime) = inner.runtime.as_ref() {
            let credentials = (runtime.base_url.clone(), runtime.token.clone());
            inner.phase = DesktopPhase::StartingSidecar;
            Some(credentials)
        } else {
            inner.phase = DesktopPhase::StartingRuntime;
            None
        }
    };
    if let Some((manager_url, manager_token)) = manager_credentials {
        spawn_sidecar(app, generation, &config, manager_url, manager_token);
    } else {
        run_full_start(app, generation, &config);
    }
}

fn run_update_login(app: &AppHandle, generation: u64, login: DesktopLoginConfig) {
    let state = app.state::<DesktopBackend>();
    let root_dir = match state
        .lock()
        .config
        .as_ref()
        .map(|config| config.root_dir.clone())
    {
        Some(root_dir) => root_dir,
        None => return,
    };
    let packaged_url = state.lock().packaged_url.clone();
    let navigation_result = navigate_packaged(app, &packaged_url);
    let sidecar = state.lock().sidecar.take();
    if let Some(sidecar) = sidecar {
        stop_sidecar(sidecar);
    }
    if let Err(error) = navigation_result {
        let mut inner = state.lock();
        if inner.lease.is_active_current(generation) {
            inner.phase = DesktopPhase::Failed;
            inner.error = Some(error);
        }
        return;
    }
    if !state.operation_is_current(generation, DesktopPhase::SavingConfig) {
        return;
    }
    let saved = match state.config_store.save(DesktopSetupInput {
        root_dir: root_dir.to_string_lossy().into_owned(),
        login,
    }) {
        Ok(saved) => saved,
        Err(error) => {
            let mut inner = state.lock();
            if inner.lease.is_active_current(generation) {
                inner.phase = DesktopPhase::NeedsSetup;
                inner.setup_scope = DesktopSetupScope::LoginOnly;
                inner.error = Some(error.into());
            }
            return;
        }
    };
    let config = saved.config;
    let manager_credentials = {
        let mut inner = state.lock();
        if !inner.lease.is_active_current(generation) {
            return;
        }
        inner.config = Some(config.clone());
        inner.error = None;
        if let Some(runtime) = inner.runtime.as_ref() {
            let credentials = (runtime.base_url.clone(), runtime.token.clone());
            inner.phase = DesktopPhase::StartingSidecar;
            Some(credentials)
        } else {
            inner.phase = DesktopPhase::StartingRuntime;
            None
        }
    };
    if let Some((manager_url, manager_token)) = manager_credentials {
        spawn_sidecar(app, generation, &config, manager_url, manager_token);
    } else {
        run_full_start(app, generation, &config);
    }
}

fn run_sidecar_terminated(app: &AppHandle, generation: u64, error: DesktopBackendError) {
    let state = app.state::<DesktopBackend>();
    let (sidecar, packaged_url) = {
        let mut inner = state.lock();
        if !inner.lease.is_active_current(generation)
            || !matches!(
                inner.phase,
                DesktopPhase::StartingSidecar | DesktopPhase::Ready | DesktopPhase::Failed
            )
        {
            return;
        }
        let sidecar = inner.sidecar.take();
        inner.pending_sidecar_error = None;
        inner.phase = DesktopPhase::Failed;
        inner.error = Some(error);
        (sidecar, inner.packaged_url.clone())
    };
    if let Some(sidecar) = sidecar {
        stop_sidecar(sidecar);
    }
    let _ = navigate_packaged(app, &packaged_url);
}

fn lifecycle_worker(app: AppHandle, receiver: Receiver<LifecycleIntent>) {
    while let Ok(intent) = receiver.recv() {
        let generation = intent.generation();
        let state = app.state::<DesktopBackend>();
        if !state.begin_operation(generation) {
            continue;
        }
        let shutdown = matches!(intent, LifecycleIntent::Shutdown { .. });
        match intent {
            LifecycleIntent::Initialize { .. } => run_initialize(&app, generation),
            LifecycleIntent::SaveSetup { input, .. } => run_save_setup(&app, generation, input),
            LifecycleIntent::Retry { .. } => run_retry(&app, generation),
            LifecycleIntent::EnterLoginSetup { .. } => run_enter_login_setup(&app, generation),
            LifecycleIntent::UpdateLogin { login, .. } => run_update_login(&app, generation, login),
            LifecycleIntent::SidecarTerminated { error, .. } => {
                run_sidecar_terminated(&app, generation, error)
            }
            LifecycleIntent::Shutdown { .. } => {
                let (sidecar, runtime) = {
                    let mut inner = state.lock();
                    (inner.sidecar.take(), inner.runtime.take())
                };
                stop_resources(sidecar, runtime);
                state.lock().shutdown_complete = true;
            }
        }
        state.finish_operation(generation);
        if shutdown {
            app.exit(0);
            break;
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
    let (supervisor, receiver) = LifecycleSupervisor::channel();
    app.manage(DesktopBackend::new(
        DesktopConfigStore::new(system_data_dir),
        default_root_dir(&home_dir),
        packaged_agent_runtime_root(&handle),
        packaged_url,
        supervisor,
    ));
    let worker_handle = handle.clone();
    thread::spawn(move || lifecycle_worker(worker_handle, receiver));
    let state = handle.state::<DesktopBackend>();
    let generation = state.lock().lease.request_generation();
    state.submit(LifecycleIntent::Initialize { generation })?;
    Ok(())
}

#[tauri::command]
pub fn desktop_get_state(state: tauri::State<'_, DesktopBackend>) -> DesktopStateSnapshot {
    state.snapshot()
}

#[tauri::command]
pub fn desktop_save_setup(
    state: tauri::State<'_, DesktopBackend>,
    input: DesktopSetupInput,
) -> Result<DesktopStateSnapshot, DesktopBackendError> {
    let generation = {
        let mut inner = state.lock();
        let generation = inner.lease.request_generation();
        inner.phase = DesktopPhase::SavingConfig;
        inner.setup_scope = DesktopSetupScope::Full;
        inner.error = None;
        generation
    };
    state.submit(LifecycleIntent::SaveSetup { generation, input })?;
    Ok(state.snapshot())
}

fn desktop_test_service_blocking(login: DesktopLoginConfig) -> Result<(), DesktopBackendError> {
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
pub async fn desktop_test_service(login: DesktopLoginConfig) -> Result<(), DesktopBackendError> {
    tauri::async_runtime::spawn_blocking(move || desktop_test_service_blocking(login))
        .await
        .map_err(|error| {
            DesktopBackendError::service(format!("登录服务测试任务执行失败: {error}"))
        })?
}

#[tauri::command]
pub fn desktop_enter_login_setup(
    state: tauri::State<'_, DesktopBackend>,
) -> Result<(), DesktopBackendError> {
    let generation = {
        let mut inner = state.lock();
        if inner.config.is_none() {
            return Err(DesktopBackendError::config("桌面配置尚未初始化"));
        }
        let generation = inner.lease.request_generation();
        inner.phase = DesktopPhase::NeedsSetup;
        inner.setup_scope = DesktopSetupScope::LoginOnly;
        inner.error = None;
        generation
    };
    state.submit(LifecycleIntent::EnterLoginSetup { generation })
}

#[tauri::command]
pub fn desktop_retry_start(
    state: tauri::State<'_, DesktopBackend>,
) -> Result<DesktopStateSnapshot, DesktopBackendError> {
    let generation = {
        let mut inner = state.lock();
        if inner.phase != DesktopPhase::Failed {
            drop(inner);
            return Ok(state.snapshot());
        }
        let generation = inner.lease.request_generation();
        inner.phase = DesktopPhase::StartingRuntime;
        inner.error = None;
        generation
    };
    state.submit(LifecycleIntent::Retry { generation })?;
    Ok(state.snapshot())
}

#[tauri::command]
pub fn desktop_update_login(
    state: tauri::State<'_, DesktopBackend>,
    login: DesktopLoginConfig,
) -> Result<DesktopStateSnapshot, DesktopBackendError> {
    let generation = {
        let mut inner = state.lock();
        if inner.config.is_none() {
            return Err(DesktopBackendError::config("桌面配置尚未初始化"));
        }
        let generation = inner.lease.request_generation();
        inner.phase = DesktopPhase::SavingConfig;
        inner.setup_scope = DesktopSetupScope::LoginOnly;
        inner.error = None;
        generation
    };
    state.submit(LifecycleIntent::UpdateLogin { generation, login })?;
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
    if let RunEvent::ExitRequested { api, .. } = event {
        let state = app.state::<DesktopBackend>();
        let generation = {
            let mut inner = state.lock();
            if inner.shutdown_complete {
                return;
            }
            api.prevent_exit();
            if inner.shutdown_requested {
                return;
            }
            inner.shutdown_requested = true;
            inner.lease.request_generation()
        };
        if let Err(error) = state.submit(LifecycleIntent::Shutdown { generation }) {
            eprintln!("[desktop] failed to submit shutdown: {error}");
            state.lock().shutdown_complete = true;
            app.exit(1);
        }
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
    fn superseded_prepared_generation_cannot_enter_external_start() {
        let mut lease = LifecycleLeaseState::default();
        let stale = lease.request_generation();
        let current = lease.request_generation();

        assert!(!lease.try_begin(stale));
        assert!(lease.try_begin(current));
    }

    #[test]
    fn next_generation_waits_for_active_generation_cleanup() {
        let mut lease = LifecycleLeaseState::default();
        let active = lease.request_generation();
        assert!(lease.try_begin(active));

        let next = lease.request_generation();
        assert!(!lease.try_begin(next));
        assert_eq!(lease.active_generation(), Some(active));

        lease.finish(active);
        assert!(lease.try_begin(next));
    }

    #[test]
    fn lifecycle_submission_does_not_execute_cleanup_on_caller() {
        let (supervisor, receiver) = LifecycleSupervisor::channel();
        supervisor
            .submit(LifecycleIntent::Shutdown { generation: 7 })
            .unwrap();

        assert!(matches!(
            receiver.try_recv(),
            Ok(LifecycleIntent::Shutdown { generation: 7 })
        ));
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

        let result = desktop_test_service_blocking(DesktopLoginConfig {
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
