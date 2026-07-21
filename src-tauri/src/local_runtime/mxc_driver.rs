use super::contract::{LocalRuntimeError, LocalRuntimeErrorCode, ProcessIdentity, StartRequest};
use super::manager::RuntimeDriver;
use mxc_sdk::policy::{FilesystemSection, NetworkSection};
use mxc_sdk::{Sandbox, SandboxPolicy};
use std::collections::HashMap;
use std::ffi::OsString;
use std::fs;
use std::path::Path;
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

const MXC_SDK_VERSION: &str = "0.7.0";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProbeResult {
    pub platform: String,
    pub mxc_version: String,
    pub backend: String,
    pub supported: bool,
    pub reason: Option<String>,
}

pub fn probe() -> Result<ProbeResult, LocalRuntimeError> {
    let platform = std::env::consts::OS;
    if platform != "linux" {
        return Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::UnsupportedPlatform,
            format!(
                "MXC local runtime requires Linux Bubblewrap, but the host platform is {platform}"
            ),
        ));
    }

    let support = mxc_sdk::platform_support();
    if !support.is_supported {
        return Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::ProbeFailed,
            support.reason.unwrap_or_else(|| {
                "MXC reported that the Linux Bubblewrap backend is unavailable".to_string()
            }),
        ));
    }

    if !support
        .available_methods
        .iter()
        .any(|method| method == "bubblewrap")
    {
        return Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::ProbeFailed,
            format!(
                "MXC reported supported methods ({}) but not the required Linux Bubblewrap backend",
                support.available_methods.join(", ")
            ),
        ));
    }

    Ok(ProbeResult {
        platform: platform.to_string(),
        mxc_version: MXC_SDK_VERSION.to_string(),
        backend: "bubblewrap".to_string(),
        supported: true,
        reason: None,
    })
}

pub fn configure_bubblewrap_from_appliance(appliance_root: &Path) -> Result<(), LocalRuntimeError> {
    let appliance_root = fs::canonicalize(appliance_root).map_err(|_| {
        LocalRuntimeError::new(
            LocalRuntimeErrorCode::InvalidRequest,
            "local runtime appliance is unavailable",
        )
    })?;
    let bwrap = appliance_root.join("bin").join("bwrap");
    if !bwrap.is_file() {
        return Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::InvalidRequest,
            "local runtime appliance is missing Bubblewrap",
        ));
    }
    let path = bubblewrap_path_with_appliance(std::env::var_os("PATH"), &appliance_root);
    std::env::set_var("PATH", path);
    Ok(())
}

fn bubblewrap_path_with_appliance(existing: Option<OsString>, appliance_root: &Path) -> OsString {
    let mut paths = vec![appliance_root.join("bin")];
    if let Some(existing) = existing {
        paths.extend(std::env::split_paths(&existing));
    }
    std::env::join_paths(paths).expect("local runtime appliance path does not contain separators")
}

pub struct MxcRuntimeDriver {
    sandboxes: Mutex<HashMap<u32, Sandbox>>,
    appliance_root: Option<std::path::PathBuf>,
}

impl Default for MxcRuntimeDriver {
    fn default() -> Self {
        Self::new()
    }
}

impl MxcRuntimeDriver {
    pub fn new() -> Self {
        Self {
            sandboxes: Mutex::new(HashMap::new()),
            appliance_root: None,
        }
    }

    pub fn with_appliance_root(appliance_root: impl Into<std::path::PathBuf>) -> Self {
        Self {
            sandboxes: Mutex::new(HashMap::new()),
            appliance_root: Some(appliance_root.into()),
        }
    }
}

impl RuntimeDriver for MxcRuntimeDriver {
    fn spawn(
        &self,
        request: &StartRequest,
        ownership_nonce: &str,
    ) -> Result<ProcessIdentity, LocalRuntimeError> {
        probe()?;
        let appliance_root = self.readonly_appliance_root(request)?;
        let policy = SandboxPolicy {
            version: format!("{MXC_SDK_VERSION}-alpha"),
            filesystem: Some(FilesystemSection {
                readwrite_paths: vec![
                    request.worktree_path.display().to_string(),
                    request.git_common_dir.display().to_string(),
                    request.codex_home.display().to_string(),
                    request.runtime_dir.display().to_string(),
                ],
                readonly_paths: vec![appliance_root.display().to_string()],
                denied_paths: Vec::new(),
                clear_policy_on_exit: Some(true),
            }),
            network: Some(NetworkSection {
                allow_outbound: true,
                allow_local_network: true,
                allowed_hosts: Vec::new(),
                blocked_hosts: Vec::new(),
                proxy: None,
            }),
            ui: None,
            timeout_ms: None,
        };
        let name = format!("orcamatrix-{}", request.runtime_scope_id);
        let mut sandbox_request =
            mxc_sdk::build_request(&policy, Some(&name)).map_err(|error| {
                LocalRuntimeError::new(
                    LocalRuntimeErrorCode::SpawnFailed,
                    format!("cannot build MXC sandbox request: {error}"),
                )
            })?;
        let mut environment = filtered_environment(request, ownership_nonce)?;
        environment.extend(appliance_environment(&appliance_root));
        sandbox_request
            .set_working_directory(request.worktree_path.display().to_string())
            .set_env(environment);
        sandbox_request.set_script(shell_quote(&request.agent_runtime_path));
        let mut sandbox = mxc_sdk::spawn_sandbox(sandbox_request).map_err(|error| {
            LocalRuntimeError::new(
                LocalRuntimeErrorCode::SpawnFailed,
                format!("cannot start MXC local runtime: {error}"),
            )
        })?;
        let pid = sandbox.id();
        let identity = match process_identity(pid) {
            Ok(Some(identity)) => identity,
            Ok(None) => {
                cleanup_failed_sandbox(&mut sandbox);
                return Err(LocalRuntimeError::new(
                    LocalRuntimeErrorCode::SpawnFailed,
                    "MXC returned a process that exited before its identity was available",
                ));
            }
            Err(error) => {
                cleanup_failed_sandbox(&mut sandbox);
                return Err(error);
            }
        };
        if identity.ownership_nonce != ownership_nonce {
            cleanup_failed_sandbox(&mut sandbox);
            return Err(LocalRuntimeError::new(
                LocalRuntimeErrorCode::SpawnFailed,
                "MXC process did not receive the required ownership nonce",
            ));
        }
        let mut sandboxes = match self.sandboxes.lock() {
            Ok(sandboxes) => sandboxes,
            Err(_) => {
                cleanup_failed_sandbox(&mut sandbox);
                return Err(LocalRuntimeError::new(
                    LocalRuntimeErrorCode::SpawnFailed,
                    "MXC sandbox registry lock is poisoned",
                ));
            }
        };
        sandboxes.insert(pid, sandbox);
        Ok(identity)
    }

    fn wait_ready(&self, runtime_addr: &str) -> Result<(), LocalRuntimeError> {
        let url = format!("http://{runtime_addr}/api/status");
        let agent = ureq::AgentBuilder::new()
            .timeout_connect(Duration::from_secs(1))
            .timeout_read(Duration::from_secs(1))
            .build();
        let deadline = Instant::now() + Duration::from_secs(30);
        while Instant::now() < deadline {
            if agent
                .get(&url)
                .call()
                .map(|response| response.status() == 200)
                .unwrap_or(false)
            {
                return Ok(());
            }
            thread::sleep(Duration::from_millis(200));
        }
        Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::ReadinessFailed,
            "MXC local runtime did not become ready within 30 seconds",
        ))
    }

    fn stop(&self, pid: u32) -> Result<(), LocalRuntimeError> {
        let sandbox = self
            .sandboxes
            .lock()
            .map_err(|_| {
                LocalRuntimeError::new(
                    LocalRuntimeErrorCode::StopFailed,
                    "MXC sandbox registry lock is poisoned",
                )
            })?
            .remove(&pid);
        let Some(mut sandbox) = sandbox else {
            return stop_owned_residual(pid);
        };
        let deadline = Instant::now() + Duration::from_secs(5);
        while Instant::now() < deadline {
            match sandbox.try_wait() {
                Ok(Some(_)) => return Ok(()),
                Ok(None) => thread::sleep(Duration::from_millis(100)),
                Err(error) => {
                    return Err(LocalRuntimeError::new(
                        LocalRuntimeErrorCode::StopFailed,
                        format!("cannot inspect MXC local runtime: {error}"),
                    ))
                }
            }
        }
        sandbox.kill().map_err(|error| {
            LocalRuntimeError::new(
                LocalRuntimeErrorCode::StopFailed,
                format!("cannot kill MXC local runtime: {error}"),
            )
        })?;
        sandbox.wait().map_err(|error| {
            LocalRuntimeError::new(
                LocalRuntimeErrorCode::StopFailed,
                format!("cannot wait for MXC local runtime: {error}"),
            )
        })?;
        Ok(())
    }

    fn identity(&self, pid: u32) -> Result<Option<ProcessIdentity>, LocalRuntimeError> {
        process_identity(pid)
    }
}

impl MxcRuntimeDriver {
    fn readonly_appliance_root(
        &self,
        request: &StartRequest,
    ) -> Result<std::path::PathBuf, LocalRuntimeError> {
        let agent_runtime = std::fs::canonicalize(&request.agent_runtime_path).map_err(|_| {
            LocalRuntimeError::new(
                LocalRuntimeErrorCode::InvalidRequest,
                "agent runtime executable is unavailable",
            )
        })?;
        if let Some(configured_root) = &self.appliance_root {
            let root = std::fs::canonicalize(configured_root).map_err(|_| {
                LocalRuntimeError::new(
                    LocalRuntimeErrorCode::InvalidRequest,
                    "local runtime appliance is unavailable",
                )
            })?;
            if !agent_runtime.starts_with(&root) {
                return Err(LocalRuntimeError::new(
                    LocalRuntimeErrorCode::InvalidRequest,
                    "agent runtime executable is outside the trusted local appliance",
                ));
            }
            return Ok(root);
        }
        parent_directory(&agent_runtime).map(std::path::Path::to_path_buf)
    }
}

fn appliance_environment(appliance_root: &Path) -> Vec<(String, String)> {
    let root = appliance_root.display().to_string();
    vec![
        (
            "APAAS_CODEX_APP_SERVER_BINARY".to_string(),
            format!("{root}/codex/bin/codex"),
        ),
        (
            "APAAS_AGENTIC_PACK_DIR".to_string(),
            format!("{root}/agentic-coding-pack"),
        ),
        ("AGENTIC_ROOT".to_string(), format!("{root}/agentic-coding")),
        (
            "AGENTIC_PACK_PYTHON".to_string(),
            format!("{root}/agentic-coding/.venv/bin/python"),
        ),
    ]
}

fn cleanup_failed_sandbox(sandbox: &mut Sandbox) {
    let _ = sandbox.kill();
    let _ = sandbox.wait();
}

fn filtered_environment(
    request: &StartRequest,
    ownership_nonce: &str,
) -> Result<Vec<(String, String)>, LocalRuntimeError> {
    let mut environment = Vec::with_capacity(request.environment.len() + 1);
    for (key, value) in &request.environment {
        if !is_allowed_environment_key(key) || value.contains('\0') {
            return Err(LocalRuntimeError::new(
                LocalRuntimeErrorCode::InvalidRequest,
                "MXC runtime environment contains an unsupported value",
            ));
        }
        environment.push((key.clone(), value.clone()));
    }
    environment.push((
        "APAAS_RUNTIME_OWNERSHIP_NONCE".to_string(),
        ownership_nonce.to_string(),
    ));
    Ok(environment)
}

fn is_allowed_environment_key(key: &str) -> bool {
    matches!(
        key,
        "APAAS_RUNTIME_CONTEXT_PATH"
            | "APAAS_MODEL_PROVIDER_PATH"
            | "APAAS_CI_PROVIDER_PATH"
            | "APAAS_WORKSPACE_INIT_MODE"
            | "APAAS_CI_HANDOFF_MODE"
            | "APAAS_REPO_WORKSPACE_PATH"
            | "APAAS_WORKSPACE_PATH"
            | "APAAS_RUNTIME_WORKSPACE_PATH"
            | "APAAS_CODEX_HOME"
            | "APAAS_RUNTIME_ADDR"
            | "APAAS_AUTH_MODE"
    )
}

fn stop_owned_residual(pid: u32) -> Result<(), LocalRuntimeError> {
    #[cfg(not(target_os = "linux"))]
    {
        let _ = pid;
        return Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::StopFailed,
            "a retained MXC sandbox handle is required on this platform",
        ));
    }
    #[cfg(target_os = "linux")]
    {
        let pid = i32::try_from(pid).map_err(|_| {
            LocalRuntimeError::new(
                LocalRuntimeErrorCode::StopFailed,
                "MXC local runtime PID is invalid",
            )
        })?;
        signal_process(pid, libc::SIGTERM)?;
        if wait_for_process_exit(pid, Duration::from_secs(5)) {
            return Ok(());
        }
        signal_process(pid, libc::SIGKILL)?;
        if wait_for_process_exit(pid, Duration::from_secs(5)) {
            return Ok(());
        }
        Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::StopFailed,
            "owned MXC local runtime did not exit after termination",
        ))
    }
}

#[cfg(target_os = "linux")]
fn signal_process(pid: i32, signal: i32) -> Result<(), LocalRuntimeError> {
    let result = unsafe { libc::kill(pid, signal) };
    if result == 0 || std::io::Error::last_os_error().raw_os_error() == Some(libc::ESRCH) {
        Ok(())
    } else {
        Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::StopFailed,
            format!(
                "cannot signal owned MXC local runtime: {}",
                std::io::Error::last_os_error()
            ),
        ))
    }
}

#[cfg(target_os = "linux")]
fn wait_for_process_exit(pid: i32, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if !Path::new(&format!("/proc/{pid}")).exists() {
            return true;
        }
        thread::sleep(Duration::from_millis(100));
    }
    !Path::new(&format!("/proc/{pid}")).exists()
}

fn parent_directory(path: &Path) -> Result<&Path, LocalRuntimeError> {
    path.parent().ok_or_else(|| {
        LocalRuntimeError::new(
            LocalRuntimeErrorCode::InvalidRequest,
            "agent runtime executable has no parent directory",
        )
    })
}

fn shell_quote(path: &Path) -> String {
    format!("'{}'", path.display().to_string().replace('\'', "'\\''"))
}

fn process_identity(pid: u32) -> Result<Option<ProcessIdentity>, LocalRuntimeError> {
    #[cfg(not(target_os = "linux"))]
    {
        let _ = pid;
        return Ok(None);
    }
    #[cfg(target_os = "linux")]
    {
        let stat_path = format!("/proc/{pid}/stat");
        let stat = match fs::read_to_string(&stat_path) {
            Ok(value) => value,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(error) => {
                return Err(LocalRuntimeError::new(
                    LocalRuntimeErrorCode::ReconcileIdentityMismatch,
                    format!("cannot read runtime process stat: {error}"),
                ))
            }
        };
        let (_, fields) = stat.rsplit_once(')').ok_or_else(|| {
            LocalRuntimeError::new(
                LocalRuntimeErrorCode::ReconcileIdentityMismatch,
                "runtime process stat is malformed",
            )
        })?;
        let process_started_at = fields
            .split_whitespace()
            .nth(19)
            .ok_or_else(|| {
                LocalRuntimeError::new(
                    LocalRuntimeErrorCode::ReconcileIdentityMismatch,
                    "runtime process start time is unavailable",
                )
            })?
            .to_string();
        let environment = match fs::read(format!("/proc/{pid}/environ")) {
            Ok(value) => value,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(error) => {
                return Err(LocalRuntimeError::new(
                    LocalRuntimeErrorCode::ReconcileIdentityMismatch,
                    format!("cannot read runtime process environment: {error}"),
                ))
            }
        };
        let ownership_nonce = environment
            .split(|byte| *byte == 0)
            .find_map(|entry| entry.strip_prefix(b"APAAS_RUNTIME_OWNERSHIP_NONCE="))
            .and_then(|value| String::from_utf8(value.to_vec()).ok());
        Ok(ownership_nonce.map(|ownership_nonce| ProcessIdentity {
            pid,
            process_started_at,
            ownership_nonce,
        }))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn linux_probe_reports_bubblewrap_or_a_blocking_reason() {
        let result = probe();
        match result {
            Ok(value) => {
                assert_eq!(value.platform, "linux");
                assert_eq!(value.backend, "bubblewrap");
                assert!(value.supported);
            }
            Err(error) => {
                assert!(matches!(
                    error.code,
                    LocalRuntimeErrorCode::UnsupportedPlatform | LocalRuntimeErrorCode::ProbeFailed
                ));
                assert!(!error.message.is_empty());
            }
        }
    }

    #[test]
    fn filtered_environment_is_explicit_and_injects_ownership_nonce() {
        let request = StartRequest {
            runtime_scope_id: "scope-a".into(),
            application_id: "app-a".into(),
            sandbox_instance_id: "instance-a".into(),
            workspace_id: "workspace-a".into(),
            worktree_path: "/tmp/worktree".into(),
            git_common_dir: "/tmp/git-common".into(),
            codex_home: "/tmp/codex".into(),
            runtime_dir: "/tmp/runtime".into(),
            runtime_context_path: "/tmp/runtime/runtime-context.json".into(),
            agent_runtime_path: "/opt/agent-runtime/agent-runtime".into(),
            runtime_addr: "127.0.0.1:41001".into(),
            environment: [
                ("APAAS_RUNTIME_ADDR".into(), "127.0.0.1:41001".into()),
                ("UNTRUSTED_HOST_ENV".into(), "must-not-pass".into()),
            ]
            .into_iter()
            .collect(),
        };
        let error = filtered_environment(&request, "nonce-a").unwrap_err();
        assert_eq!(error.code, LocalRuntimeErrorCode::InvalidRequest);

        let mut allowed = request;
        allowed.environment.remove("UNTRUSTED_HOST_ENV");
        let environment = filtered_environment(&allowed, "nonce-a").unwrap();
        assert!(environment
            .iter()
            .any(|(key, value)| { key == "APAAS_RUNTIME_OWNERSHIP_NONCE" && value == "nonce-a" }));
        assert!(!environment.iter().any(|(key, _)| key == "PATH"));
    }

    #[test]
    fn appliance_environment_uses_only_the_trusted_appliance_root() {
        let root = Path::new("/opt/dolphin/agent-runtime");
        let environment = appliance_environment(root);

        assert!(environment
            .iter()
            .all(|(_, value)| value.starts_with("/opt/dolphin/agent-runtime/")));
        assert!(environment.iter().any(|(key, value)| {
            key == "APAAS_CODEX_APP_SERVER_BINARY"
                && value == "/opt/dolphin/agent-runtime/codex/bin/codex"
        }));
        assert!(environment.iter().any(|(key, value)| {
            key == "APAAS_AGENTIC_PACK_DIR"
                && value == "/opt/dolphin/agent-runtime/agentic-coding-pack"
        }));
    }

    #[test]
    fn trusted_appliance_rejects_an_external_agent_runtime() {
        let unique = format!(
            "orcamatrix-local-runtime-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("system clock is after epoch")
                .as_nanos()
        );
        let root = std::env::temp_dir().join(unique);
        let appliance = root.join("appliance");
        let outside = root.join("outside-agent-runtime");
        std::fs::create_dir_all(&appliance).expect("create appliance");
        std::fs::write(&outside, "#!/bin/sh\n").expect("create external runtime");

        let request = StartRequest {
            runtime_scope_id: "scope-a".into(),
            application_id: "app-a".into(),
            sandbox_instance_id: "instance-a".into(),
            workspace_id: "workspace-a".into(),
            worktree_path: "/tmp/worktree".into(),
            git_common_dir: "/tmp/git-common".into(),
            codex_home: "/tmp/codex".into(),
            runtime_dir: "/tmp/runtime".into(),
            runtime_context_path: "/tmp/runtime/runtime-context.json".into(),
            agent_runtime_path: outside,
            runtime_addr: "127.0.0.1:41001".into(),
            environment: Default::default(),
        };
        let driver = MxcRuntimeDriver::with_appliance_root(&appliance);

        let error = driver.readonly_appliance_root(&request).unwrap_err();
        assert_eq!(error.code, LocalRuntimeErrorCode::InvalidRequest);
        assert!(error
            .message
            .contains("outside the trusted local appliance"));

        std::fs::remove_dir_all(root).expect("clean test directory");
    }

    #[test]
    fn appliance_bubblewrap_path_precedes_the_existing_path() {
        let appliance = Path::new("/opt/dolphin/agent-runtime");
        let path = bubblewrap_path_with_appliance(
            Some(std::ffi::OsString::from("/usr/local/bin:/usr/bin")),
            appliance,
        );

        assert_eq!(
            path,
            std::ffi::OsString::from("/opt/dolphin/agent-runtime/bin:/usr/local/bin:/usr/bin")
        );
    }
}
