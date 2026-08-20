use crate::desktop_config::{
    default_root_dir, normalize_login_url, DesktopConfig, DesktopConfigError, DesktopConfigStore,
    DesktopLoginConfig, DesktopLoginMode, DesktopPaths, DesktopSetupInput,
    SystemAssistantExecutionMode, WorkspaceEntryScope,
};
use crate::desktop_discovery::{
    discover, discover_with_timeout, login_config, DesktopDiscoveryError,
};
use crate::local_runtime::api::LocalRuntimeApiServer;
use crate::local_runtime::process_driver::agent_runtime_executable;
use serde::{Deserialize, Serialize};
use std::any::Any;
use std::collections::BTreeMap;
use std::fs::OpenOptions;
use std::io::{self, Write};
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, Receiver, Sender, SyncSender, TrySendError};
use std::sync::{Arc, Mutex, MutexGuard};
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

impl DesktopPhase {
    fn as_str(self) -> &'static str {
        match self {
            Self::NeedsSetup => "needs_setup",
            Self::SavingConfig => "saving_config",
            Self::StartingRuntime => "starting_runtime",
            Self::StartingSidecar => "starting_sidecar",
            Self::Ready => "ready",
            Self::Failed => "failed",
        }
    }
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
            message: sanitize_log_line(&message.into()),
        }
    }

    fn sidecar(message: impl Into<String>) -> Self {
        Self {
            code: "DESKTOP_SETUP_SIDECAR_START_FAILED".to_string(),
            message: sanitize_log_line(&message.into()),
        }
    }
}

fn map_sidecar_error(message: impl Into<String>) -> DesktopBackendError {
    DesktopBackendError::sidecar(message)
}

fn map_runtime_error(message: impl Into<String>) -> DesktopBackendError {
    DesktopBackendError::runtime(message)
}

fn sanitize_log_line(line: &str) -> String {
    let flattened = line
        .chars()
        .map(|character| {
            if matches!(character, '\r' | '\n' | '\t') || character.is_control() {
                ' '
            } else {
                character
            }
        })
        .collect::<String>();
    let flattened = flattened.trim();
    if flattened.is_empty() {
        return "(empty)".to_string();
    }

    if let Ok(mut value) = serde_json::from_str::<serde_json::Value>(flattened) {
        sanitize_json_value(&mut value);
        return serde_json::to_string(&value).unwrap_or_else(|_| "[REDACTED]".to_string());
    }

    sanitize_non_json_line(flattened)
}

fn normalize_sensitive_key(key: &str) -> String {
    key.chars()
        .filter(|character| character.is_ascii_alphanumeric())
        .map(|character| character.to_ascii_lowercase())
        .collect()
}

fn is_sensitive_key(key: &str) -> bool {
    let normalized = normalize_sensitive_key(key);
    normalized == "authorization"
        || normalized.ends_with("password")
        || normalized.ends_with("token")
        || normalized.ends_with("apikey")
        || normalized.ends_with("secret")
        || normalized.ends_with("encryptionkey")
        || normalized.ends_with("privatekey")
        || normalized.ends_with("authenticationresponse")
}

fn sanitize_json_value(value: &mut serde_json::Value) {
    match value {
        serde_json::Value::Object(object) => {
            for (key, value) in object.iter_mut() {
                if is_sensitive_key(key) {
                    *value = serde_json::Value::String("[REDACTED]".to_string());
                } else {
                    sanitize_json_value(value);
                }
            }
        }
        serde_json::Value::Array(items) => {
            for item in items {
                sanitize_json_value(item);
            }
        }
        serde_json::Value::String(value) => {
            let sanitized = sanitize_non_json_line(value);
            if sanitized == "[REDACTED]" {
                *value = sanitized;
            }
        }
        _ => {}
    }
}

fn sanitize_non_json_line(line: &str) -> String {
    let lowercase = line.to_ascii_lowercase();
    if lowercase.contains("traceback")
        || contains_sensitive_assignment(line)
        || contains_bearer_credential(line)
        || contains_jwt(line)
        || contains_sensitive_url(line)
    {
        return "[REDACTED]".to_string();
    }

    line.to_string()
}

fn contains_sensitive_assignment(line: &str) -> bool {
    for (start, _) in line.char_indices() {
        let tail = &line[start..];
        for (offset, character) in tail.char_indices() {
            if offset > 80 {
                break;
            }
            if matches!(character, ':' | '=') {
                let key = tail[..offset].trim().trim_matches(['"', '\'']);
                if is_sensitive_key(key) {
                    return true;
                }
                break;
            }
            if !(character.is_ascii_alphanumeric()
                || character.is_ascii_whitespace()
                || matches!(character, '_' | '-' | '"' | '\''))
            {
                break;
            }
        }
    }
    false
}

fn contains_bearer_credential(line: &str) -> bool {
    let lowercase = line.to_ascii_lowercase();
    lowercase.match_indices("bearer").any(|(index, marker)| {
        let before = lowercase[..index].chars().next_back();
        let after = &lowercase[index + marker.len()..];
        before.is_none_or(|character| !character.is_ascii_alphanumeric())
            && after
                .chars()
                .next()
                .is_some_and(|character| character.is_ascii_whitespace())
            && !after.trim().is_empty()
    })
}

fn contains_jwt(line: &str) -> bool {
    line.split(|character: char| {
        character.is_whitespace()
            || matches!(
                character,
                '"' | '\'' | ',' | ';' | '(' | ')' | '[' | ']' | '{' | '}'
            )
    })
    .any(|candidate| {
        let parts = candidate.split('.').collect::<Vec<_>>();
        parts.len() == 3
            && parts[0].starts_with("eyJ")
            && parts.iter().all(|part| {
                !part.is_empty()
                    && part.chars().all(|character| {
                        character.is_ascii_alphanumeric() || matches!(character, '-' | '_')
                    })
            })
    })
}

fn contains_sensitive_url(line: &str) -> bool {
    let lowercase = line.to_ascii_lowercase();
    let mut offset = 0;
    while offset < line.len() {
        let tail = &lowercase[offset..];
        let http = tail.find("http://");
        let https = tail.find("https://");
        let Some(relative_start) = [http, https].into_iter().flatten().min() else {
            break;
        };
        let start = offset + relative_start;
        let end = line[start..]
            .char_indices()
            .find_map(|(relative, character)| {
                (relative > 0
                    && (character.is_whitespace() || matches!(character, '"' | '\'' | '<' | '>')))
                .then_some(start + relative)
            })
            .unwrap_or(line.len());
        let candidate = line[start..end]
            .trim_end_matches([',', ';', ')', ']', '}'])
            .trim();
        if let Ok(url) = tauri::Url::parse(candidate) {
            if !url.username().is_empty()
                || url.password().is_some()
                || url.query_pairs().any(|(key, _)| is_sensitive_key(&key))
            {
                return true;
            }
        }
        offset = start + 1;
    }
    false
}

#[derive(Debug, Clone)]
struct DiagnosticRecord {
    logs_dir: PathBuf,
    file_name: &'static str,
    phase: DesktopPhase,
    code: String,
    message: String,
}

#[derive(Debug, Clone)]
struct SidecarLogContext {
    generation: u64,
    logs_dir: PathBuf,
}

impl DiagnosticRecord {
    fn new(
        logs_dir: PathBuf,
        file_name: &'static str,
        phase: DesktopPhase,
        code: impl Into<String>,
        message: impl Into<String>,
    ) -> Self {
        Self {
            logs_dir,
            file_name,
            phase,
            code: code.into(),
            message: message.into(),
        }
    }
}

#[derive(Clone)]
struct DiagnosticSink {
    sender: SyncSender<DiagnosticRecord>,
    failed: Arc<AtomicBool>,
}

impl DiagnosticSink {
    fn new() -> Self {
        Self::from_writer(128, write_diagnostic_log)
    }

    fn from_writer(
        capacity: usize,
        writer: impl Fn(&DiagnosticRecord) -> io::Result<()> + Send + 'static,
    ) -> Self {
        let (sender, receiver) = mpsc::sync_channel::<DiagnosticRecord>(capacity);
        let failed = Arc::new(AtomicBool::new(false));
        let writer_failed = failed.clone();
        if thread::Builder::new()
            .name("desktop-diagnostics".to_string())
            .spawn(move || {
                while let Ok(record) = receiver.recv() {
                    if writer(&record).is_err() {
                        writer_failed.store(true, Ordering::Release);
                    }
                }
            })
            .is_err()
        {
            failed.store(true, Ordering::Release);
        }
        Self { sender, failed }
    }

    fn enqueue(&self, record: DiagnosticRecord) {
        if matches!(
            self.sender.try_send(record),
            Err(TrySendError::Full(_)) | Err(TrySendError::Disconnected(_))
        ) {
            self.failed.store(true, Ordering::Release);
        }
    }

    fn has_failed(&self) -> bool {
        self.failed.load(Ordering::Acquire)
    }
}

fn write_diagnostic_log(record: &DiagnosticRecord) -> io::Result<()> {
    std::fs::create_dir_all(&record.logs_dir)?;
    let mut file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(record.logs_dir.join(record.file_name))?;
    writeln!(
        file,
        "time={} phase={} code={} message={}",
        chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Millis, true),
        record.phase.as_str(),
        sanitize_log_line(&record.code),
        sanitize_log_line(&record.message),
    )
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

fn control_plane_code_base_url(config: &DesktopConfig) -> String {
    if let Some(url) = config
        .discovery
        .as_ref()
        .and_then(|discovery| discovery.products.code.base_url.clone())
        .filter(|url| !url.trim().is_empty())
    {
        return url;
    }
    let base_url = config.login.base_url.trim_end_matches('/');
    if base_url.ends_with("/control-plane") {
        base_url.to_string()
    } else {
        format!("{base_url}/control-plane")
    }
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
        let code_base_url = if config.login.mode == DesktopLoginMode::ControlPlane {
            control_plane_code_base_url(config)
        } else {
            String::new()
        };
        let login_base_url = config
            .discovery
            .as_ref()
            .and_then(|discovery| discovery.auth.api_base_url.clone())
            .filter(|url| !url.trim().is_empty())
            .unwrap_or_else(|| config.login.base_url.clone());
        let system_git_enabled = config
            .discovery
            .as_ref()
            .map(|discovery| discovery.remote_capabilities.system_git)
            .unwrap_or(false);
        let system_assistant_execution_mode = match config.system_assistant_execution_mode {
            SystemAssistantExecutionMode::Local => "local",
            SystemAssistantExecutionMode::Remote => "remote",
        };
        let system_assistant_remote_enabled = config
            .discovery
            .as_ref()
            .map(|discovery| discovery.remote_capabilities.system_assistant_remote)
            .unwrap_or(false);
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
                "--parent-pid".into(),
                std::process::id().to_string(),
                "--login-mode".into(),
                mode.into(),
                "--login-base-url".into(),
                login_base_url,
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
                ("DOLPHIN_CODE_CONTROL_PLANE_URL".into(), code_base_url),
                (
                    "DOLPHIN_SYSTEM_GIT_ENABLED".into(),
                    system_git_enabled.to_string(),
                ),
                (
                    "DOLPHIN_SYSTEM_ASSISTANT_EXECUTION_MODE".into(),
                    system_assistant_execution_mode.into(),
                ),
                (
                    "DOLPHIN_SYSTEM_ASSISTANT_REMOTE_ENABLED".into(),
                    system_assistant_remote_enabled.to_string(),
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

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ShutdownRequestStatus {
    Pending,
    Complete,
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
    sidecar_generation: Option<u64>,
    pending_sidecar_error: Option<(u64, DesktopBackendError)>,
    worker_failed: bool,
    shutdown_requested: bool,
    shutdown_generation: Option<u64>,
    shutdown_intent_enqueued: bool,
    shutdown_recovery_started: bool,
    shutdown_complete: bool,
    diagnostics: DiagnosticSink,
}

impl DesktopBackendInner {
    fn write_diagnostic(
        &self,
        file_name: &'static str,
        phase: DesktopPhase,
        code: &str,
        message: &str,
    ) {
        let Some(config) = self.config.as_ref() else {
            return;
        };
        let logs_dir = DesktopPaths::from_root(config.root_dir.clone()).logs_dir;
        self.diagnostics.enqueue(DiagnosticRecord::new(
            logs_dir, file_name, phase, code, message,
        ));
    }

    fn prepare_sidecar_diagnostic(
        &self,
        context: &SidecarLogContext,
        code: &str,
        message: &str,
    ) -> Option<(DiagnosticSink, DiagnosticRecord)> {
        if self.sidecar_generation != Some(context.generation)
            || !self.lease.is_desired(context.generation)
        {
            return None;
        }
        Some((
            self.diagnostics.clone(),
            DiagnosticRecord::new(
                context.logs_dir.clone(),
                "sidecar.log",
                self.phase,
                code,
                message,
            ),
        ))
    }

    fn transition_to(&mut self, phase: DesktopPhase, message: &str) {
        self.phase = phase;
        self.write_diagnostic("desktop.log", phase, "DESKTOP_SETUP_PHASE_CHANGED", message);
    }

    fn fail(&mut self, mut error: DesktopBackendError) {
        self.phase = DesktopPhase::Failed;
        self.write_diagnostic(
            "desktop.log",
            DesktopPhase::Failed,
            &error.code,
            &error.message,
        );
        if self.diagnostics.has_failed() && !error.message.contains("日志写入失败") {
            error.message.push_str("；日志写入失败");
        }
        self.error = Some(error);
    }

    fn visible_error(&self) -> Option<DesktopBackendError> {
        self.error.clone().map(|mut error| {
            if self.diagnostics.has_failed() && !error.message.contains("日志写入失败") {
                error.message.push_str("；日志写入失败");
            }
            error
        })
    }

    fn take_sidecar(&mut self) -> Option<CommandChild> {
        self.sidecar_generation = None;
        self.sidecar.take()
    }

    fn publish_ready_for_navigation(&mut self, generation: u64) -> bool {
        if !self.lease.is_active_current(generation) || self.phase != DesktopPhase::StartingSidecar
        {
            return false;
        }
        self.transition_to(DesktopPhase::Ready, "本地桌面服务已就绪");
        self.error = None;
        self.pending_sidecar_error = None;
        true
    }

    fn fail_ready_navigation(&mut self, generation: u64, error: DesktopBackendError) -> bool {
        if !self.lease.is_active_current(generation) || self.phase != DesktopPhase::Ready {
            return false;
        }
        self.take_sidecar();
        self.pending_sidecar_error = None;
        self.fail(error);
        true
    }
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
                sidecar_generation: None,
                pending_sidecar_error: None,
                worker_failed: false,
                shutdown_requested: false,
                shutdown_generation: None,
                shutdown_intent_enqueued: false,
                shutdown_recovery_started: false,
                shutdown_complete: false,
                diagnostics: DiagnosticSink::new(),
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
        self.snapshot_from_inner(&inner)
    }

    fn snapshot_from_inner(&self, inner: &DesktopBackendInner) -> DesktopStateSnapshot {
        DesktopStateSnapshot {
            phase: inner.phase,
            setup_scope: inner.setup_scope,
            config: inner.config.clone(),
            default_root_dir: self.default_root_dir.clone(),
            error: inner.visible_error(),
        }
    }

    fn ensure_accepting(inner: &DesktopBackendInner) -> Result<(), DesktopBackendError> {
        if inner.shutdown_requested {
            return Err(DesktopBackendError::runtime("桌面应用正在退出"));
        }
        if inner.worker_failed {
            return Err(inner.visible_error().unwrap_or_else(|| {
                DesktopBackendError::runtime("桌面生命周期服务不可用，请重新启动应用")
            }));
        }
        Ok(())
    }

    fn record_worker_failure(inner: &mut DesktopBackendInner, error: DesktopBackendError) {
        inner.worker_failed = true;
        inner.shutdown_intent_enqueued = false;
        inner.pending_sidecar_error = None;
        inner.fail(error);
    }

    fn submit_locked(
        &self,
        inner: &mut DesktopBackendInner,
        intent: LifecycleIntent,
    ) -> Result<(), DesktopBackendError> {
        if let Err(error) = self.supervisor.submit(intent) {
            Self::record_worker_failure(inner, error.clone());
            return Err(error);
        }
        Ok(())
    }

    fn queue_initialize(&self) -> Result<(), DesktopBackendError> {
        let mut inner = self.lock();
        Self::ensure_accepting(&inner)?;
        let generation = inner.lease.request_generation();
        self.submit_locked(&mut inner, LifecycleIntent::Initialize { generation })
    }

    fn queue_save_setup(
        &self,
        input: DesktopSetupInput,
    ) -> Result<DesktopStateSnapshot, DesktopBackendError> {
        let mut inner = self.lock();
        Self::ensure_accepting(&inner)?;
        let generation = inner.lease.request_generation();
        inner.transition_to(DesktopPhase::SavingConfig, "保存桌面配置");
        inner.setup_scope = DesktopSetupScope::Full;
        inner.error = None;
        self.submit_locked(&mut inner, LifecycleIntent::SaveSetup { generation, input })?;
        Ok(self.snapshot_from_inner(&inner))
    }

    fn queue_retry(&self) -> Result<DesktopStateSnapshot, DesktopBackendError> {
        let mut inner = self.lock();
        Self::ensure_accepting(&inner)?;
        if inner.phase != DesktopPhase::Failed {
            return Ok(self.snapshot_from_inner(&inner));
        }
        let generation = inner.lease.request_generation();
        inner.transition_to(DesktopPhase::StartingRuntime, "重试准备桌面服务");
        inner.error = None;
        self.submit_locked(&mut inner, LifecycleIntent::Retry { generation })?;
        Ok(self.snapshot_from_inner(&inner))
    }

    fn queue_enter_login_setup(&self) -> Result<(), DesktopBackendError> {
        let mut inner = self.lock();
        Self::ensure_accepting(&inner)?;
        if inner.config.is_none() {
            return Err(DesktopBackendError::config("桌面配置尚未初始化"));
        }
        let generation = inner.lease.request_generation();
        inner.transition_to(DesktopPhase::NeedsSetup, "进入登录服务配置");
        inner.setup_scope = DesktopSetupScope::LoginOnly;
        inner.error = None;
        self.submit_locked(&mut inner, LifecycleIntent::EnterLoginSetup { generation })
    }

    fn queue_update_login(
        &self,
        login: DesktopLoginConfig,
    ) -> Result<DesktopStateSnapshot, DesktopBackendError> {
        let mut inner = self.lock();
        Self::ensure_accepting(&inner)?;
        if inner.config.is_none() {
            return Err(DesktopBackendError::config("桌面配置尚未初始化"));
        }
        let generation = inner.lease.request_generation();
        inner.transition_to(DesktopPhase::SavingConfig, "保存登录服务配置");
        inner.setup_scope = DesktopSetupScope::LoginOnly;
        inner.error = None;
        self.submit_locked(
            &mut inner,
            LifecycleIntent::UpdateLogin { generation, login },
        )?;
        Ok(self.snapshot_from_inner(&inner))
    }

    fn update_workspace_entry_scope(
        &self,
        scope: WorkspaceEntryScope,
    ) -> Result<DesktopStateSnapshot, DesktopBackendError> {
        let mut inner = self.lock();
        Self::ensure_accepting(&inner)?;
        let config = inner
            .config
            .as_ref()
            .ok_or_else(|| DesktopBackendError::config("桌面配置尚未初始化"))?;
        let saved = self
            .config_store
            .save_current_root(workspace_scope_update_input(config, scope))?;
        inner.config = Some(saved.config);
        Ok(self.snapshot_from_inner(&inner))
    }

    fn persist_login_update(
        &self,
        generation: u64,
        login: DesktopLoginConfig,
    ) -> Result<Option<DesktopConfig>, DesktopBackendError> {
        let mut inner = self.lock();
        if !inner.lease.is_active_current(generation) || inner.phase != DesktopPhase::SavingConfig {
            return Ok(None);
        }
        let config = inner
            .config
            .as_ref()
            .ok_or_else(|| DesktopBackendError::config("桌面配置尚未初始化"))?;
        let saved = self.config_store.save_current_root(DesktopSetupInput {
            root_dir: config.root_dir.to_string_lossy().into_owned(),
            login,
            workspace_entry_scope: config.workspace_entry_scope,
            discovery_url: Some(config.discovery_url.clone()),
            discovery: config.discovery.clone(),
            local_ai_enabled: config.local_ai_enabled,
            system_assistant_execution_mode: config.system_assistant_execution_mode,
        })?;
        let config = saved.config;
        inner.config = Some(config.clone());
        Ok(Some(config))
    }

    fn queue_sidecar_terminated(
        &self,
        generation: u64,
        error: DesktopBackendError,
    ) -> Result<bool, DesktopBackendError> {
        let mut inner = self.lock();
        if inner.shutdown_requested || inner.worker_failed {
            return Ok(false);
        }
        if !inner.lease.is_desired(generation)
            || !matches!(
                inner.phase,
                DesktopPhase::StartingSidecar | DesktopPhase::Ready
            )
        {
            return Ok(false);
        }
        inner.pending_sidecar_error = Some((generation, error.clone()));
        self.submit_locked(
            &mut inner,
            LifecycleIntent::SidecarTerminated { generation, error },
        )?;
        Ok(true)
    }

    fn queue_shutdown(&self) -> Result<ShutdownRequestStatus, DesktopBackendError> {
        let mut inner = self.lock();
        if inner.shutdown_complete {
            return Ok(ShutdownRequestStatus::Complete);
        }
        inner.shutdown_requested = true;
        if inner.shutdown_intent_enqueued {
            return Ok(ShutdownRequestStatus::Pending);
        }
        if inner.worker_failed {
            return Err(inner.visible_error().unwrap_or_else(|| {
                DesktopBackendError::runtime("桌面生命周期服务不可用，请重新启动应用")
            }));
        }
        let generation = match inner.shutdown_generation {
            Some(generation) => generation,
            None => {
                let generation = inner.lease.request_generation();
                inner.shutdown_generation = Some(generation);
                generation
            }
        };
        self.submit_locked(&mut inner, LifecycleIntent::Shutdown { generation })?;
        inner.shutdown_intent_enqueued = true;
        Ok(ShutdownRequestStatus::Pending)
    }

    fn shutdown_complete(&self) -> bool {
        self.lock().shutdown_complete
    }

    fn begin_shutdown_recovery(&self) -> bool {
        let mut inner = self.lock();
        if inner.shutdown_complete || inner.shutdown_recovery_started {
            return false;
        }
        inner.shutdown_recovery_started = true;
        true
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

fn workspace_scope_update_input(
    config: &DesktopConfig,
    scope: WorkspaceEntryScope,
) -> DesktopSetupInput {
    DesktopSetupInput {
        root_dir: config.root_dir.to_string_lossy().into_owned(),
        login: config.login.clone(),
        workspace_entry_scope: scope,
        discovery_url: Some(config.discovery_url.clone()),
        discovery: config.discovery.clone(),
        local_ai_enabled: config.local_ai_enabled,
        system_assistant_execution_mode: config.system_assistant_execution_mode,
    }
}

const PACKAGED_AGENT_RUNTIME_RELATIVE_DIR: &str = "resources/agent-runtime";

fn packaged_agent_runtime_root(handle: &AppHandle) -> PathBuf {
    if let Some(path) = std::env::var_os("DOLPHIN_AGENT_RUNTIME_PATH") {
        let path: PathBuf = path.into();
        return path
            .parent()
            .and_then(Path::parent)
            .map(Path::to_path_buf)
            .unwrap_or(path);
    }
    let resource_dir = handle
        .path()
        .resource_dir()
        .expect("resource directory is available");
    let bundled_root = resource_dir.join(PACKAGED_AGENT_RUNTIME_RELATIVE_DIR);
    if bundled_root.exists() {
        return bundled_root;
    }
    let legacy_root = resource_dir.join("agent-runtime");
    if legacy_root.exists() {
        return legacy_root;
    }
    bundled_root
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

fn is_packaged_app_url(url: &tauri::Url) -> bool {
    url.scheme() == "tauri" || url.host_str() == Some("tauri.localhost")
}

fn navigate_ready(app: &AppHandle, port: u16) -> Result<(), DesktopBackendError> {
    let window = app
        .get_webview_window("main")
        .ok_or_else(|| DesktopBackendError::sidecar("桌面主窗口不可用"))?;
    let current_url = window
        .url()
        .map_err(|error| DesktopBackendError::sidecar(format!("无法读取桌面启动页面: {error}")))?;
    if is_packaged_app_url(&current_url) {
        app.state::<DesktopBackend>().lock().packaged_url = current_url;
    }
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
        inner.fail(error);
        inner.packaged_url.clone()
    };
    let _ = navigate_packaged(app, &packaged_url);
}

fn enqueue_sidecar_diagnostic(
    app: &AppHandle,
    context: &SidecarLogContext,
    code: &str,
    message: &str,
) -> bool {
    let state = app.state::<DesktopBackend>();
    let prepared = {
        let inner = state.lock();
        inner.prepare_sidecar_diagnostic(context, code, message)
    };
    let Some((sink, record)) = prepared else {
        return false;
    };
    sink.enqueue(record);
    true
}

fn log_sidecar_events(
    app: AppHandle,
    context: SidecarLogContext,
    mut rx: tauri::async_runtime::Receiver<CommandEvent>,
) {
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(bytes) => {
                    enqueue_sidecar_diagnostic(
                        &app,
                        &context,
                        "DESKTOP_SIDECAR_STDOUT",
                        &String::from_utf8_lossy(&bytes),
                    );
                }
                CommandEvent::Stderr(bytes) => {
                    enqueue_sidecar_diagnostic(
                        &app,
                        &context,
                        "DESKTOP_SIDECAR_STDERR",
                        &String::from_utf8_lossy(&bytes),
                    );
                }
                CommandEvent::Error(error) => {
                    enqueue_sidecar_diagnostic(
                        &app,
                        &context,
                        "DESKTOP_SIDECAR_STREAM_ERROR",
                        &error,
                    );
                }
                CommandEvent::Terminated(payload) => {
                    let message = match (payload.code, payload.signal) {
                        (Some(code), _) => format!("sidecar exited with code {code}"),
                        (_, Some(signal)) => format!("sidecar terminated by signal {signal}"),
                        _ => "sidecar terminated unexpectedly".to_string(),
                    };
                    let error = map_sidecar_error(message);
                    enqueue_sidecar_diagnostic(
                        &app,
                        &context,
                        "DESKTOP_SIDECAR_TERMINATED",
                        &error.message,
                    );
                    let state = app.state::<DesktopBackend>();
                    let _ = state.queue_sidecar_terminated(context.generation, error);
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
    let log_context = SidecarLogContext {
        generation,
        logs_dir: paths.logs_dir.clone(),
    };
    let port = stable_port(&paths.data_dir);
    let state = app.state::<DesktopBackend>();
    let agent_runtime_path = agent_runtime_executable(&state.agent_runtime_root);
    let launch =
        SidecarLaunch::from_config(config, port, manager_url.as_str(), manager_token.as_str());
    let diagnostic_sink = state.lock().diagnostics.clone();
    diagnostic_sink.enqueue(DiagnosticRecord::new(
        log_context.logs_dir.clone(),
        "sidecar.log",
        DesktopPhase::StartingSidecar,
        "DESKTOP_SIDECAR_STARTING",
        "启动 sidecar 进程",
    ));
    let mut command = match app.shell().sidecar("dolphin-ai-sidecar") {
        Ok(command) => command.args(launch.args),
        Err(error) => {
            set_launch_failed(
                app,
                generation,
                map_sidecar_error(format!("找不到桌面 sidecar: {error}")),
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
                map_sidecar_error(format!("无法启动桌面 sidecar: {error}")),
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
        let replaced = inner.sidecar.replace(child);
        inner.sidecar_generation = Some(generation);
        replaced
    };
    if let Some(child) = replaced_child {
        stop_sidecar(child);
    }
    log_sidecar_events(app.clone(), log_context, rx);

    let health = wait_healthy(app, generation, port);
    match health {
        HealthStatus::Healthy => {
            if !operation_is_current(app, generation, DesktopPhase::StartingSidecar) {
                let child = state.lock().take_sidecar();
                if let Some(child) = child {
                    stop_sidecar(child);
                }
                return;
            }
            if !state.lock().publish_ready_for_navigation(generation) {
                let child = state.lock().take_sidecar();
                if let Some(child) = child {
                    stop_sidecar(child);
                }
                return;
            }
            if let Err(error) = navigate_ready(app, port) {
                let child = {
                    let mut inner = state.lock();
                    let child = inner.sidecar.take();
                    if inner.fail_ready_navigation(generation, error) {
                        child
                    } else {
                        inner.sidecar = child;
                        None
                    }
                };
                if let Some(child) = child {
                    stop_sidecar(child);
                }
                return;
            }
        }
        HealthStatus::TimedOut | HealthStatus::Terminated(_) => {
            let error = match health {
                HealthStatus::Terminated(error) => error,
                _ => map_sidecar_error("sidecar 健康检查超时"),
            };
            let child = {
                let mut inner = state.lock();
                let child = inner.take_sidecar();
                if inner.lease.is_active_current(generation) {
                    inner.fail(error);
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
            let child = state.lock().take_sidecar();
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
                    map_runtime_error(format!("无法启动本地 Runtime Manager: {}", error.message)),
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
        inner.transition_to(DesktopPhase::StartingSidecar, "启动桌面服务");
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

fn refresh_discovery_on_start(
    store: &DesktopConfigStore,
    config: DesktopConfig,
) -> (DesktopConfig, Option<DesktopBackendError>) {
    let document = match discover_with_timeout(&config.discovery_url, Duration::from_secs(4)) {
        Ok(document) => document,
        Err(error) => {
            return (
                config,
                Some(DesktopBackendError {
                    code: "DESKTOP_DISCOVERY_REFRESH_FAILED".into(),
                    message: format!(
                        "启动时刷新远程 Discovery 失败，继续使用上次配置：{}",
                        error.message
                    ),
                }),
            );
        }
    };
    let login = match login_config(&document) {
        Ok(login) => login,
        Err(error) => {
            return (
                config,
                Some(DesktopBackendError {
                    code: "DESKTOP_DISCOVERY_REFRESH_FAILED".into(),
                    message: format!(
                        "启动时刷新远程认证配置失败，继续使用上次配置：{}",
                        error.message
                    ),
                }),
            );
        }
    };
    let input = DesktopSetupInput {
        root_dir: config.root_dir.to_string_lossy().into_owned(),
        login,
        workspace_entry_scope: config.workspace_entry_scope,
        discovery_url: Some(config.discovery_url.clone()),
        discovery: Some(document),
        local_ai_enabled: config.local_ai_enabled,
        system_assistant_execution_mode: config.system_assistant_execution_mode,
    };
    match store.save_current_root(input) {
        Ok(saved) => (saved.config, None),
        Err(error) => (
            config,
            Some(DesktopBackendError {
                code: "DESKTOP_DISCOVERY_REFRESH_SAVE_FAILED".into(),
                message: format!(
                    "远程 Discovery 已刷新但未能保存，继续使用上次配置：{}",
                    error.message
                ),
            }),
        ),
    }
}

fn run_initialize(app: &AppHandle, generation: u64) {
    let state = app.state::<DesktopBackend>();
    match state.config_store.load() {
        Ok(None) => {
            let mut inner = state.lock();
            if inner.lease.is_active_current(generation) {
                inner.transition_to(DesktopPhase::NeedsSetup, "等待桌面首次配置");
                inner.setup_scope = DesktopSetupScope::Full;
                inner.config = None;
                inner.error = None;
            }
        }
        Err(error) => {
            let mut inner = state.lock();
            if inner.lease.is_active_current(generation) {
                inner.transition_to(DesktopPhase::NeedsSetup, "桌面配置无效，等待重新配置");
                inner.setup_scope = DesktopSetupScope::Full;
                inner.config = None;
                inner.error = Some(error.into());
            }
        }
        Ok(Some(saved)) => {
            let (config, discovery_warning) =
                refresh_discovery_on_start(&state.config_store, saved.config);
            {
                let mut inner = state.lock();
                if !inner.lease.is_active_current(generation) {
                    return;
                }
                inner.setup_scope = DesktopSetupScope::Full;
                inner.config = Some(config.clone());
                if let Some(warning) = discovery_warning {
                    inner.write_diagnostic(
                        "desktop.log",
                        DesktopPhase::StartingRuntime,
                        &warning.code,
                        &warning.message,
                    );
                }
                inner.transition_to(DesktopPhase::StartingRuntime, "准备桌面服务");
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
        (inner.take_sidecar(), inner.runtime.take())
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
                inner.transition_to(DesktopPhase::NeedsSetup, "桌面配置保存失败");
                inner.setup_scope = DesktopSetupScope::Full;
                inner.error = Some(error.into());
            }
            return;
        }
    };
    let (config, discovery_warning) = refresh_discovery_on_start(&state.config_store, saved.config);
    {
        let mut inner = state.lock();
        if !inner.lease.is_active_current(generation) {
            return;
        }
        inner.config = Some(config.clone());
        if let Some(warning) = discovery_warning {
            inner.write_diagnostic(
                "desktop.log",
                DesktopPhase::StartingRuntime,
                &warning.code,
                &warning.message,
            );
        }
        inner.transition_to(DesktopPhase::StartingRuntime, "准备桌面服务");
        inner.error = None;
    }
    run_full_start(app, generation, &config);
}

fn run_enter_login_setup(app: &AppHandle, generation: u64) {
    let state = app.state::<DesktopBackend>();
    let packaged_url = state.lock().packaged_url.clone();
    let navigation_result = navigate_packaged(app, &packaged_url);
    let sidecar = state.lock().take_sidecar();
    if let Some(sidecar) = sidecar {
        stop_sidecar(sidecar);
    }
    if let Err(error) = navigation_result {
        let mut inner = state.lock();
        if inner.lease.is_active_current(generation) {
            inner.fail(error);
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
    let sidecar = state.lock().take_sidecar();
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
                    inner.setup_scope = DesktopSetupScope::Full;
                    inner.config = None;
                    inner.error = Some(DesktopBackendError::config("桌面配置尚未初始化"));
                    inner.transition_to(DesktopPhase::NeedsSetup, "重试时缺少桌面配置");
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
                    inner.setup_scope = DesktopSetupScope::Full;
                    inner.error = Some(error.into());
                    inner.transition_to(DesktopPhase::NeedsSetup, "重试时桌面配置无效");
                }
                runtime
            };
            stop_resources(None, runtime);
            return;
        }
    };
    let (config, discovery_warning) = refresh_discovery_on_start(&state.config_store, saved.config);
    let stale_runtime = {
        let mut inner = state.lock();
        if !inner.lease.is_active_current(generation) {
            return;
        }
        inner.config = Some(config.clone());
        if let Some(warning) = discovery_warning {
            inner.write_diagnostic(
                "desktop.log",
                DesktopPhase::StartingRuntime,
                &warning.code,
                &warning.message,
            );
        }
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
            inner.transition_to(DesktopPhase::StartingSidecar, "重试启动桌面服务");
            Some(credentials)
        } else {
            inner.transition_to(
                DesktopPhase::StartingRuntime,
                "重试启动本地 Runtime Manager",
            );
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
    let packaged_url = {
        let inner = state.lock();
        if inner.config.is_none() {
            return;
        }
        inner.packaged_url.clone()
    };
    let navigation_result = navigate_packaged(app, &packaged_url);
    let sidecar = state.lock().take_sidecar();
    if let Some(sidecar) = sidecar {
        stop_sidecar(sidecar);
    }
    if let Err(error) = navigation_result {
        let mut inner = state.lock();
        if inner.lease.is_active_current(generation) {
            inner.fail(error);
        }
        return;
    }
    if !state.operation_is_current(generation, DesktopPhase::SavingConfig) {
        return;
    }
    let config = match state.persist_login_update(generation, login) {
        Ok(Some(config)) => config,
        Ok(None) => return,
        Err(error) => {
            let mut inner = state.lock();
            if inner.lease.is_active_current(generation) {
                inner.transition_to(DesktopPhase::NeedsSetup, "登录服务配置保存失败");
                inner.setup_scope = DesktopSetupScope::LoginOnly;
                inner.error = Some(error);
            }
            return;
        }
    };
    let manager_credentials = {
        let mut inner = state.lock();
        if !inner.lease.is_active_current(generation) {
            return;
        }
        inner.error = None;
        if let Some(runtime) = inner.runtime.as_ref() {
            let credentials = (runtime.base_url.clone(), runtime.token.clone());
            inner.transition_to(DesktopPhase::StartingSidecar, "重新启动桌面服务");
            Some(credentials)
        } else {
            inner.transition_to(
                DesktopPhase::StartingRuntime,
                "重新启动本地 Runtime Manager",
            );
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
        let sidecar = inner.take_sidecar();
        inner.pending_sidecar_error = None;
        inner.fail(error);
        (sidecar, inner.packaged_url.clone())
    };
    if let Some(sidecar) = sidecar {
        stop_sidecar(sidecar);
    }
    let _ = navigate_packaged(app, &packaged_url);
}

struct LifecycleLeaseRelease<F: FnOnce()> {
    release: Option<F>,
}

impl<F: FnOnce()> LifecycleLeaseRelease<F> {
    fn new(release: F) -> Self {
        Self {
            release: Some(release),
        }
    }
}

impl<F: FnOnce()> Drop for LifecycleLeaseRelease<F> {
    fn drop(&mut self) {
        if let Some(release) = self.release.take() {
            release();
        }
    }
}

fn panic_message(payload: &(dyn Any + Send)) -> String {
    if let Some(message) = payload.downcast_ref::<&str>() {
        (*message).to_string()
    } else if let Some(message) = payload.downcast_ref::<String>() {
        message.clone()
    } else {
        "unknown panic".to_string()
    }
}

fn run_guarded_worker_operation<Operation, Release, Recover>(
    operation: Operation,
    release: Release,
    recover: Recover,
) -> bool
where
    Operation: FnOnce(),
    Release: FnOnce(),
    Recover: FnOnce(String),
{
    let _lease_release = LifecycleLeaseRelease::new(release);
    match catch_unwind(AssertUnwindSafe(operation)) {
        Ok(()) => true,
        Err(payload) => {
            let message = panic_message(payload.as_ref());
            let _ = catch_unwind(AssertUnwindSafe(|| recover(message)));
            false
        }
    }
}

fn recover_worker_failure(app: &AppHandle, panic_message: String) {
    let state = app.state::<DesktopBackend>();
    let (sidecar, runtime, shutdown_requested) = {
        let mut inner = state.lock();
        let error = DesktopBackendError::runtime(format!(
            "桌面生命周期处理异常，请重新启动应用: {panic_message}"
        ));
        DesktopBackend::record_worker_failure(&mut inner, error);
        (
            inner.take_sidecar(),
            inner.runtime.take(),
            inner.shutdown_requested,
        )
    };
    let _ = catch_unwind(AssertUnwindSafe(|| stop_resources(sidecar, runtime)));
    if shutdown_requested {
        state.lock().shutdown_complete = true;
        app.exit(1);
    }
}

fn lifecycle_worker(app: AppHandle, receiver: Receiver<LifecycleIntent>) {
    while let Ok(intent) = receiver.recv() {
        let generation = intent.generation();
        let state = app.state::<DesktopBackend>();
        if !state.begin_operation(generation) {
            continue;
        }
        let shutdown = matches!(intent, LifecycleIntent::Shutdown { .. });
        let completed = run_guarded_worker_operation(
            || match intent {
                LifecycleIntent::Initialize { .. } => run_initialize(&app, generation),
                LifecycleIntent::SaveSetup { input, .. } => run_save_setup(&app, generation, input),
                LifecycleIntent::Retry { .. } => run_retry(&app, generation),
                LifecycleIntent::EnterLoginSetup { .. } => run_enter_login_setup(&app, generation),
                LifecycleIntent::UpdateLogin { login, .. } => {
                    run_update_login(&app, generation, login)
                }
                LifecycleIntent::SidecarTerminated { error, .. } => {
                    run_sidecar_terminated(&app, generation, error)
                }
                LifecycleIntent::Shutdown { .. } => {
                    let (sidecar, runtime) = {
                        let mut inner = state.lock();
                        (inner.take_sidecar(), inner.runtime.take())
                    };
                    stop_resources(sidecar, runtime);
                    let mut inner = state.lock();
                    inner.shutdown_intent_enqueued = false;
                    inner.shutdown_complete = true;
                }
            },
            || state.finish_operation(generation),
            |message| recover_worker_failure(&app, message),
        );
        if !completed {
            break;
        }
        if shutdown {
            app.exit(0);
            break;
        }
    }
}

pub fn setup(app: &mut tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    let window = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
        .title("DolphinAI")
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
    handle.state::<DesktopBackend>().queue_initialize()?;
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
    state.queue_save_setup(input)
}

#[tauri::command]
pub async fn desktop_discover_service(
    url: String,
) -> Result<crate::desktop_config::DesktopDiscoveryDocument, DesktopBackendError> {
    tauri::async_runtime::spawn_blocking(move || discover(&url))
        .await
        .map_err(|error| DesktopBackendError::service(format!("Discovery 任务执行失败: {error}")))?
        .map_err(|error: DesktopDiscoveryError| DesktopBackendError {
            code: error.code,
            message: error.message,
        })
}

fn desktop_test_service_blocking(login: DesktopLoginConfig) -> Result<(), DesktopBackendError> {
    let url = normalize_login_url(&login.base_url).map_err(DesktopBackendError::from)?;
    let agent = ureq::AgentBuilder::new()
        .redirects(0)
        .timeout(Duration::from_secs(5))
        .build();
    match agent.get(&url).call() {
        Ok(response) if desktop_service_status_reachable(response.status()) => Ok(()),
        Err(ureq::Error::Status(status, _)) if desktop_service_status_reachable(status) => Ok(()),
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

fn desktop_service_status_reachable(status: u16) -> bool {
    (200..500).contains(&status)
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
    state.queue_enter_login_setup()
}

#[tauri::command]
pub fn desktop_retry_start(
    state: tauri::State<'_, DesktopBackend>,
) -> Result<DesktopStateSnapshot, DesktopBackendError> {
    state.queue_retry()
}

#[tauri::command]
pub fn desktop_update_login(
    state: tauri::State<'_, DesktopBackend>,
    login: DesktopLoginConfig,
) -> Result<DesktopStateSnapshot, DesktopBackendError> {
    state.queue_update_login(login)
}

#[tauri::command]
pub fn desktop_update_workspace_entry_scope(
    state: tauri::State<'_, DesktopBackend>,
    scope: WorkspaceEntryScope,
) -> Result<DesktopStateSnapshot, DesktopBackendError> {
    state.update_workspace_entry_scope(scope)
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
        if state.shutdown_complete() {
            return;
        }
        api.prevent_exit();
        match state.queue_shutdown() {
            Ok(ShutdownRequestStatus::Pending) => {}
            Ok(ShutdownRequestStatus::Complete) => app.exit(0),
            Err(error) => {
                eprintln!("[desktop] failed to submit shutdown: {error}");
                if state.begin_shutdown_recovery() {
                    let app = app.clone();
                    thread::spawn(move || {
                        let state = app.state::<DesktopBackend>();
                        let (sidecar, runtime) = {
                            let mut inner = state.lock();
                            (inner.take_sidecar(), inner.runtime.take())
                        };
                        let _ = catch_unwind(AssertUnwindSafe(|| stop_resources(sidecar, runtime)));
                        state.lock().shutdown_complete = true;
                        app.exit(1);
                    });
                }
            }
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
    use crate::desktop_config::{
        DesktopConfig, DesktopLoginConfig, DesktopLoginMode, WorkspaceEntryScope,
    };
    use std::cell::{Cell, RefCell};
    use std::fs;
    use std::io::{Read, Write};
    use std::net::TcpListener;
    use std::path::PathBuf;

    fn unique_backend_test_dir(label: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "dolphin-desktop-backend-{label}-{}-{}",
            std::process::id(),
            chrono::Utc::now().timestamp_nanos_opt().unwrap_or_default(),
        ))
    }

    fn fixture_config(mode: DesktopLoginMode) -> DesktopConfig {
        DesktopConfig {
            schema_version: 1,
            root_dir: PathBuf::from("/tmp/DolphinAI"),
            login: DesktopLoginConfig {
                mode,
                base_url: "https://om-demo.dfy.definesys.cn".to_string(),
            },
            workspace_entry_scope: WorkspaceEntryScope::Both,
            discovery_url: "https://om-demo.dfy.definesys.cn".to_string(),
            discovery: None,
            local_ai_enabled: true,
            system_assistant_execution_mode: SystemAssistantExecutionMode::Local,
        }
    }

    fn fixture_backend(supervisor: LifecycleSupervisor) -> DesktopBackend {
        let backend = DesktopBackend::new(
            DesktopConfigStore::new(std::env::temp_dir().join("dolphin-desktop-tests")),
            PathBuf::from("/tmp/DolphinAI"),
            PathBuf::from("/tmp/agent-runtime"),
            tauri::Url::parse("tauri://localhost/index.html").unwrap(),
            supervisor,
        );
        backend.lock().config = Some(fixture_config(DesktopLoginMode::ControlPlane));
        backend
    }

    fn fixture_setup_input() -> DesktopSetupInput {
        DesktopSetupInput {
            root_dir: "/tmp/DolphinAI".to_string(),
            login: DesktopLoginConfig {
                mode: DesktopLoginMode::ControlPlane,
                base_url: "https://om-demo.dfy.definesys.cn".to_string(),
            },
            workspace_entry_scope: WorkspaceEntryScope::Both,
            discovery_url: None,
            discovery: None,
            local_ai_enabled: true,
            system_assistant_execution_mode: SystemAssistantExecutionMode::Local,
        }
    }

    #[test]
    fn workspace_scope_update_input_preserves_login_and_root() {
        let config = fixture_config(DesktopLoginMode::Apaas);
        let input = workspace_scope_update_input(&config, WorkspaceEntryScope::Apaas);
        assert_eq!(PathBuf::from(input.root_dir), config.root_dir);
        assert_eq!(input.login, config.login);
        assert_eq!(input.workspace_entry_scope, WorkspaceEntryScope::Apaas);
    }

    #[test]
    fn startup_refreshes_and_persists_remote_capabilities_from_discovery() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let discovery_url = format!("http://{address}");
        let response_body = format!(
            r#"{{"schema_version":1,"deployment_id":"test","platform":{{"type":"control_plane","name":"DolphinAI"}},"auth":{{"provider":"control_plane","login_url":"{discovery_url}","api_base_url":"{discovery_url}"}},"products":{{"builder":{{"enabled":false}},"code":{{"enabled":true,"base_url":"{discovery_url}/control-plane"}}}},"remote_capabilities":{{"models":true,"mcp":true,"skills":true,"knowledge_bases":true,"system_git":true}},"local_ai":{{"enabled":true,"allowed_kinds":["model"],"bridge_protocol_version":1}}}}"#
        );
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut request = [0_u8; 2048];
            let _ = stream.read(&mut request).unwrap();
            write!(
                stream,
                "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                response_body.len(),
                response_body,
            )
            .unwrap();
        });
        let temp = unique_backend_test_dir("discovery-refresh");
        let store = DesktopConfigStore::new(temp.join("system"));
        let mut input = fixture_setup_input();
        input.root_dir = temp.join("DolphinAI").to_string_lossy().into_owned();
        input.discovery_url = Some(discovery_url);
        let saved = store.save(input).unwrap();

        let (refreshed, warning) = refresh_discovery_on_start(&store, saved.config);

        server.join().unwrap();
        assert!(warning.is_none());
        assert!(
            refreshed
                .discovery
                .as_ref()
                .unwrap()
                .remote_capabilities
                .system_git
        );
        assert!(
            store
                .load()
                .unwrap()
                .unwrap()
                .config
                .discovery
                .unwrap()
                .remote_capabilities
                .system_git
        );
        fs::remove_dir_all(temp).unwrap();
    }

    #[test]
    fn packaged_app_url_rejects_initial_blank_page() {
        assert!(!is_packaged_app_url(
            &tauri::Url::parse("about:blank").unwrap()
        ));
        assert!(is_packaged_app_url(
            &tauri::Url::parse("http://tauri.localhost/desktop-setup").unwrap()
        ));
        assert!(is_packaged_app_url(
            &tauri::Url::parse("tauri://localhost/desktop-setup").unwrap()
        ));
    }

    #[test]
    fn in_flight_login_update_preserves_newer_workspace_scope() {
        let temp = unique_backend_test_dir("workspace-scope-login-update");
        let config_store = DesktopConfigStore::new(temp.join("system"));
        let mut setup_input = fixture_setup_input();
        setup_input.root_dir = temp.join("DolphinAI").to_string_lossy().into_owned();
        let saved = config_store.save(setup_input).unwrap();
        let (supervisor, receiver) = LifecycleSupervisor::channel();
        let backend = DesktopBackend::new(
            config_store.clone(),
            saved.config.root_dir.clone(),
            PathBuf::from("/tmp/agent-runtime"),
            tauri::Url::parse("tauri://localhost/index.html").unwrap(),
            supervisor,
        );
        backend.lock().config = Some(saved.config);

        backend
            .queue_update_login(fixture_config(DesktopLoginMode::Apaas).login)
            .unwrap();
        let (generation, login) = match receiver.recv().unwrap() {
            LifecycleIntent::UpdateLogin { generation, login } => (generation, login),
            _ => panic!("expected login update intent"),
        };
        assert!(backend.begin_operation(generation));

        backend
            .update_workspace_entry_scope(WorkspaceEntryScope::AiPlatform)
            .unwrap();
        let config = backend
            .persist_login_update(generation, login)
            .unwrap()
            .unwrap();

        let loaded = config_store.load().unwrap().unwrap().config;
        assert_eq!(config, loaded);
        assert_eq!(
            loaded.workspace_entry_scope,
            WorkspaceEntryScope::AiPlatform
        );

        fs::remove_dir_all(temp).unwrap();
    }

    #[test]
    fn control_plane_sidecar_contract_uses_applications_and_runtime_dirs() {
        let config = fixture_config(DesktopLoginMode::ControlPlane);
        let launch =
            SidecarLaunch::from_config(&config, 8799, "http://127.0.0.1:9001", "manager-token");
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
            launch.arg_value("--parent-pid"),
            std::process::id().to_string()
        );
        assert_eq!(
            launch.arg_value("--login-base-url"),
            "https://om-demo.dfy.definesys.cn"
        );
        assert_eq!(
            launch.env.get("DOLPHIN_LOCAL_RUNTIME_MANAGER_URL"),
            Some(&"http://127.0.0.1:9001".to_string())
        );
        assert_eq!(
            launch.env.get("DOLPHIN_CODE_CONTROL_PLANE_URL"),
            Some(&"https://om-demo.dfy.definesys.cn/control-plane".to_string())
        );
    }

    #[test]
    fn failed_runtime_does_not_collapse_to_legacy_manager_unavailable() {
        let error = DesktopBackendError::runtime("cannot bind local runtime manager");
        assert_eq!(error.code, "DESKTOP_SETUP_RUNTIME_START_FAILED");
        assert!(!error.message.contains("LOCAL_RUNTIME_MANAGER_UNAVAILABLE"));
    }

    #[test]
    fn diagnostics_reject_adversarial_secret_syntax() {
        for (line, secret) in [
            ("token=abc password=secret Authorization: Bearer xyz", "xyz"),
            (
                r#"response={"access_token":"access-value"}"#,
                "access-value",
            ),
            ("api_key=api-value", "api-value"),
            ("secret=secret-value", "secret-value"),
            (
                "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.signature",
                "signature",
            ),
            (
                "Traceback (most recent call last):\n  File \"app.py\", line 1",
                "app.py",
            ),
            ("Authorization : Bearer auth-space", "auth-space"),
            ("Authorization=auth-equals", "auth-equals"),
            (
                r#"{"nested":{"token" : "json-token"},"ok":"visible"}"#,
                "json-token",
            ),
            ("password : password-colon", "password-colon"),
            ("apiKey=camel-key", "camel-key"),
            ("Bearer bearer-only", "bearer-only"),
            (
                "urls https://safe.example/path https://user:url-pass@example.test/path?x=1",
                "url-pass",
            ),
            (
                "queries https://safe.example/?x=1 https://example.test/?apiKey=query-key",
                "query-key",
            ),
        ] {
            let sanitized = sanitize_log_line(line);
            assert!(
                !sanitized.contains(secret),
                "secret {secret:?} leaked from {line:?} as {sanitized:?}"
            );
            assert!(sanitized.contains("[REDACTED]"));
        }
    }

    #[test]
    fn nested_json_redacts_sensitive_keys_recursively() {
        let sanitized = sanitize_log_line(
            r#"{"items":[{"apiKey":"api-json"},{"profile":{"password":"pass-json"}}],"ok":"visible"}"#,
        );
        let value: serde_json::Value = serde_json::from_str(&sanitized).unwrap();

        assert_eq!(value["items"][0]["apiKey"], "[REDACTED]");
        assert_eq!(value["items"][1]["profile"]["password"], "[REDACTED]");
        assert_eq!(value["ok"], "visible");
        assert!(!sanitized.contains("api-json"));
        assert!(!sanitized.contains("pass-json"));
    }

    #[test]
    fn launch_failures_keep_distinct_codes() {
        assert_eq!(
            map_runtime_error("bind failed").code,
            "DESKTOP_SETUP_RUNTIME_START_FAILED"
        );
        assert_eq!(
            map_sidecar_error("health timeout").code,
            "DESKTOP_SETUP_SIDECAR_START_FAILED"
        );
    }

    #[test]
    fn diagnostic_log_is_utf8_structured_and_sanitized() {
        let logs_dir = std::env::temp_dir().join(format!(
            "dolphin-desktop-diagnostics-{}-{}",
            std::process::id(),
            chrono::Utc::now().timestamp_nanos_opt().unwrap_or_default()
        ));
        write_diagnostic_log(&DiagnosticRecord::new(
            logs_dir.clone(),
            "desktop.log",
            DesktopPhase::Failed,
            "DESKTOP_SETUP_RUNTIME_START_FAILED",
            "bind failed token=manager-secret",
        ))
        .unwrap();

        let contents = std::fs::read_to_string(logs_dir.join("desktop.log")).unwrap();
        assert!(contents.contains("time="));
        assert!(contents.contains("phase=failed"));
        assert!(contents.contains("code=DESKTOP_SETUP_RUNTIME_START_FAILED"));
        assert!(contents.contains("message=[REDACTED]"));
        assert!(!contents.contains("manager-secret"));
        assert_eq!(contents.lines().count(), 1);

        std::fs::remove_dir_all(logs_dir).unwrap();
    }

    #[test]
    fn launch_failure_preserves_error_when_diagnostic_log_cannot_open() {
        let blocked_root = std::env::temp_dir().join(format!(
            "dolphin-desktop-blocked-log-{}-{}",
            std::process::id(),
            chrono::Utc::now().timestamp_nanos_opt().unwrap_or_default()
        ));
        std::fs::write(&blocked_root, b"not a directory").unwrap();
        let (supervisor, _receiver) = LifecycleSupervisor::channel();
        let backend = fixture_backend(supervisor);
        {
            let mut inner = backend.lock();
            inner.config.as_mut().unwrap().root_dir = blocked_root.clone();
            inner.fail(map_runtime_error("bind failed"));
        }

        for _ in 0..100 {
            if backend.lock().diagnostics.has_failed() {
                break;
            }
            thread::sleep(Duration::from_millis(5));
        }

        let error = backend.snapshot().error.unwrap();
        assert_eq!(error.code, "DESKTOP_SETUP_RUNTIME_START_FAILED");
        assert_eq!(error.message, "bind failed；日志写入失败");

        std::fs::remove_file(blocked_root).unwrap();
    }

    #[test]
    fn stale_sidecar_generation_is_dropped_and_log_path_stays_frozen() {
        let (supervisor, _receiver) = LifecycleSupervisor::channel();
        let backend = fixture_backend(supervisor);
        let old_logs = PathBuf::from("/old-root/.appdata/logs");
        let new_logs = PathBuf::from("/new-root/.appdata/logs");

        let old_context = {
            let mut inner = backend.lock();
            let generation = inner.lease.request_generation();
            inner.sidecar_generation = Some(generation);
            inner.phase = DesktopPhase::Ready;
            SidecarLogContext {
                generation,
                logs_dir: old_logs.clone(),
            }
        };

        let old_record = backend
            .lock()
            .prepare_sidecar_diagnostic(&old_context, "STDOUT", "old event")
            .expect("current generation event is accepted")
            .1;
        assert_eq!(old_record.logs_dir, old_logs);

        {
            let mut inner = backend.lock();
            inner.config.as_mut().unwrap().root_dir = PathBuf::from("/new-root");
            let new_generation = inner.lease.request_generation();
            inner.sidecar_generation = Some(new_generation);
            let new_context = SidecarLogContext {
                generation: new_generation,
                logs_dir: new_logs.clone(),
            };
            let new_record = inner
                .prepare_sidecar_diagnostic(&new_context, "STDOUT", "new event")
                .expect("replacement generation event is accepted")
                .1;
            assert_eq!(new_record.logs_dir, new_logs);
        }

        assert!(backend
            .lock()
            .prepare_sidecar_diagnostic(&old_context, "STDOUT", "late old event")
            .is_none());
    }

    #[test]
    fn blocked_bounded_diagnostic_sink_never_holds_backend_mutex() {
        use std::sync::{Arc, Barrier};

        let writer_started = Arc::new(Barrier::new(2));
        let writer_release = Arc::new(Barrier::new(2));
        let started = writer_started.clone();
        let release = writer_release.clone();
        let sink = DiagnosticSink::from_writer(1, move |_| {
            started.wait();
            release.wait();
            Ok(())
        });
        let (supervisor, _receiver) = LifecycleSupervisor::channel();
        let backend = fixture_backend(supervisor);
        backend.lock().diagnostics = sink.clone();

        backend
            .lock()
            .transition_to(DesktopPhase::StartingRuntime, "first");
        writer_started.wait();
        backend
            .lock()
            .transition_to(DesktopPhase::StartingSidecar, "queued");
        backend
            .lock()
            .transition_to(DesktopPhase::Ready, "queue overflow");

        assert!(
            sink.has_failed(),
            "full bounded queue marks diagnostics failed"
        );
        assert!(
            backend.inner.try_lock().is_ok(),
            "blocked log writer must not retain backend state mutex"
        );
        writer_release.wait();
    }

    #[test]
    fn desktop_path_kind_rejects_arbitrary_paths() {
        assert!(serde_json::from_str::<DesktopPathKind>(r#""root""#).is_ok());
        assert!(serde_json::from_str::<DesktopPathKind>(r#""logs""#).is_ok());
        assert!(serde_json::from_str::<DesktopPathKind>(r#""/tmp/arbitrary""#).is_err());
    }

    #[test]
    fn retry_is_failed_only_and_single_flight() {
        let (supervisor, receiver) = LifecycleSupervisor::channel();
        let backend = fixture_backend(supervisor);
        let initial_generation = backend.lock().lease.desired_generation;

        backend.lock().phase = DesktopPhase::Ready;
        assert_eq!(backend.queue_retry().unwrap().phase, DesktopPhase::Ready);
        assert_eq!(backend.lock().lease.desired_generation, initial_generation);
        assert!(matches!(
            receiver.try_recv(),
            Err(mpsc::TryRecvError::Empty)
        ));

        backend.lock().phase = DesktopPhase::Failed;
        let first = backend.queue_retry().unwrap();
        let retry_generation = backend.lock().lease.desired_generation;
        let second = backend.queue_retry().unwrap();
        assert_eq!(first.phase, DesktopPhase::StartingRuntime);
        assert_eq!(second.phase, DesktopPhase::StartingRuntime);
        assert_eq!(backend.lock().lease.desired_generation, retry_generation);
        assert!(matches!(
            receiver.try_recv(),
            Ok(LifecycleIntent::Retry { generation }) if generation == retry_generation
        ));
        assert!(matches!(
            receiver.try_recv(),
            Err(mpsc::TryRecvError::Empty)
        ));
    }

    #[test]
    fn ready_is_published_before_navigation_and_navigation_failure_is_stable() {
        let (supervisor, _receiver) = LifecycleSupervisor::channel();
        let backend = fixture_backend(supervisor);
        let generation = {
            let mut inner = backend.lock();
            let generation = inner.lease.request_generation();
            assert!(inner.lease.try_begin(generation));
            inner.phase = DesktopPhase::StartingSidecar;
            generation
        };

        {
            let mut inner = backend.lock();
            assert!(inner.publish_ready_for_navigation(generation));
            assert_eq!(inner.phase, DesktopPhase::Ready);
            assert!(inner.error.is_none());
        }

        let error = DesktopBackendError::sidecar("navigation failed");
        {
            let mut inner = backend.lock();
            assert!(inner.fail_ready_navigation(generation, error));
            assert_eq!(inner.phase, DesktopPhase::Failed);
            assert_eq!(inner.error.as_ref().unwrap().message, "navigation failed");
            assert!(inner.sidecar.is_none());
            assert!(inner.sidecar_generation.is_none());
        }
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
    fn shutdown_barrier_rejects_normal_intents_without_advancing_generation() {
        let (supervisor, receiver) = LifecycleSupervisor::channel();
        let backend = fixture_backend(supervisor);
        backend.lock().phase = DesktopPhase::Failed;

        assert_eq!(
            backend.queue_shutdown().unwrap(),
            ShutdownRequestStatus::Pending
        );
        let shutdown_generation = backend.lock().lease.desired_generation;

        assert!(backend.queue_retry().is_err());
        assert!(backend.queue_save_setup(fixture_setup_input()).is_err());
        assert!(backend.queue_enter_login_setup().is_err());
        assert!(backend
            .queue_update_login(fixture_setup_input().login)
            .is_err());
        assert_eq!(
            backend.queue_shutdown().unwrap(),
            ShutdownRequestStatus::Pending
        );

        assert_eq!(backend.lock().lease.desired_generation, shutdown_generation);
        assert!(matches!(
            receiver.try_recv(),
            Ok(LifecycleIntent::Shutdown { generation }) if generation == shutdown_generation
        ));
        assert!(matches!(
            receiver.try_recv(),
            Err(mpsc::TryRecvError::Empty)
        ));
    }

    #[test]
    fn disconnected_supervisor_stabilizes_state_and_rejects_future_commands() {
        let (supervisor, receiver) = LifecycleSupervisor::channel();
        drop(receiver);
        let backend = fixture_backend(supervisor);

        let error = backend.queue_save_setup(fixture_setup_input()).unwrap_err();
        let generation_after_failure = backend.lock().lease.desired_generation;
        let snapshot = backend.snapshot();

        assert_eq!(error.code, "DESKTOP_SETUP_RUNTIME_START_FAILED");
        assert_eq!(snapshot.phase, DesktopPhase::Failed);
        assert_eq!(
            snapshot.error.as_ref().map(|item| item.code.as_str()),
            Some(error.code.as_str())
        );
        assert!(backend.queue_retry().is_err());
        assert_eq!(
            backend.lock().lease.desired_generation,
            generation_after_failure
        );
    }

    #[test]
    fn handler_panic_releases_active_lease_and_runs_failure_cleanup() {
        let lease = RefCell::new(LifecycleLeaseState::default());
        let generation = lease.borrow_mut().request_generation();
        assert!(lease.borrow_mut().try_begin(generation));
        let phase = Cell::new(DesktopPhase::StartingRuntime);
        let cleanup_called = Cell::new(false);

        let completed = run_guarded_worker_operation(
            || panic!("handler failed"),
            || lease.borrow_mut().finish(generation),
            |_| {
                phase.set(DesktopPhase::Failed);
                cleanup_called.set(true);
            },
        );

        assert!(!completed);
        assert_eq!(lease.borrow().active_generation(), None);
        assert_eq!(phase.get(), DesktopPhase::Failed);
        assert!(cleanup_called.get());
    }

    #[test]
    fn service_test_treats_redirect_response_as_reachable() {
        assert!(desktop_service_status_reachable(302));
    }
}
