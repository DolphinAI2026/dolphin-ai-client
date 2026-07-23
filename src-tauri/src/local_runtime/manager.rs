use super::contract::{
    InstanceState, InstanceStatus, LocalRuntimeError, LocalRuntimeErrorCode, ProcessIdentity,
    ReconcileResult, StartRequest,
};
use super::journal::{JournalRecord, JournalStore};
use chrono::Utc;
use std::collections::HashMap;
use std::fs::{self, OpenOptions};
use std::io::Read;
use std::net::SocketAddr;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

const SANDBOX_TOKEN_FILE: &str = "sandbox-token";

pub trait RuntimeDriver {
    fn spawn(
        &self,
        request: &StartRequest,
        ownership_nonce: &str,
    ) -> Result<ProcessIdentity, LocalRuntimeError>;
    fn wait_ready(&self, request: &StartRequest) -> Result<(), LocalRuntimeError>;
    fn stop(&self, pid: u32) -> Result<(), LocalRuntimeError>;
    fn identity(&self, pid: u32) -> Result<Option<ProcessIdentity>, LocalRuntimeError>;
}

pub struct LocalRuntimeManager<D> {
    data_root: PathBuf,
    journal: JournalStore,
    driver: D,
    active: Mutex<HashMap<String, InstanceStatus>>,
}

impl<D: RuntimeDriver> LocalRuntimeManager<D> {
    pub fn new(data_root: impl Into<PathBuf>, driver: D) -> Self {
        let data_root = data_root.into();
        Self {
            journal: JournalStore::new(data_root.join("local-runtimes")),
            data_root,
            driver,
            active: Mutex::new(HashMap::new()),
        }
    }

    pub fn start(&self, request: StartRequest) -> Result<InstanceStatus, LocalRuntimeError> {
        validate_request(&self.data_root, &request)?;
        let _lock = ScopeLock::acquire(&self.data_root, &request.runtime_scope_id)?;
        let mut active = self.active.lock().map_err(|_| {
            LocalRuntimeError::new(
                LocalRuntimeErrorCode::JournalFailed,
                "local runtime state lock is poisoned",
            )
        })?;
        if let Some(existing) = active.get(&request.runtime_scope_id) {
            if existing.sandbox_instance_id == request.sandbox_instance_id {
                return Ok(existing.clone());
            }
            return Err(LocalRuntimeError::new(
                LocalRuntimeErrorCode::InstanceConflict,
                "another local runtime instance is already active for this scope",
            ));
        }
        if let Some(record) = self.journal.load(&request.runtime_scope_id)? {
            match self.driver.identity(record.pid)? {
                Some(identity)
                    if identity.process_started_at == record.process_started_at
                        && identity.ownership_nonce == record.ownership_nonce
                        && record.sandbox_instance_id == request.sandbox_instance_id =>
                {
                    self.driver.wait_ready(&request)?;
                    let status = status_from_record(&request, &record);
                    active.insert(status.runtime_scope_id.clone(), status.clone());
                    return Ok(status);
                }
                Some(identity)
                    if identity.process_started_at == record.process_started_at
                        && identity.ownership_nonce == record.ownership_nonce =>
                {
                    return Err(LocalRuntimeError::new(
                        LocalRuntimeErrorCode::InstanceConflict,
                        "another local runtime instance is already active for this scope",
                    ))
                }
                _ => self.journal.remove(&request.runtime_scope_id)?,
            }
        }

        let nonce = format!(
            "runtime-{}-{}",
            std::process::id(),
            Utc::now().timestamp_nanos_opt().unwrap_or_default()
        );
        let identity = self.driver.spawn(&request, &nonce)?;
        let record = JournalRecord {
            runtime_scope_id: request.runtime_scope_id.clone(),
            application_id: request.application_id.clone(),
            sandbox_instance_id: request.sandbox_instance_id.clone(),
            pid: identity.pid,
            process_started_at: identity.process_started_at.clone(),
            ownership_nonce: identity.ownership_nonce.clone(),
            worktree_path: request.worktree_path.clone(),
            state: InstanceState::Starting,
            updated_at: Utc::now(),
        };
        if let Err(error) = self.journal.write(&record) {
            let _ = self.driver.stop(identity.pid);
            return Err(error);
        }
        if let Err(error) = self.driver.wait_ready(&request) {
            let _ = self.driver.stop(identity.pid);
            let _ = self.journal.remove(&request.runtime_scope_id);
            return Err(error);
        }
        if let Err(error) = self.journal.write(&JournalRecord {
            state: InstanceState::Ready,
            updated_at: Utc::now(),
            ..record
        }) {
            let _ = self.driver.stop(identity.pid);
            let _ = self.journal.remove(&request.runtime_scope_id);
            return Err(error);
        }
        let status = InstanceStatus {
            runtime_scope_id: request.runtime_scope_id.clone(),
            application_id: request.application_id.clone(),
            sandbox_instance_id: request.sandbox_instance_id.clone(),
            state: InstanceState::Ready,
            pid: identity.pid,
            runtime_base_url: format!("http://{}", request.runtime_addr),
            builder_url: format!("http://{}/builder/", request.runtime_addr),
            started_at: Utc::now().to_rfc3339(),
        };
        active.insert(status.runtime_scope_id.clone(), status.clone());
        Ok(status)
    }

    pub fn status(
        &self,
        runtime_scope_id: &str,
    ) -> Result<Option<InstanceStatus>, LocalRuntimeError> {
        Ok(self
            .active
            .lock()
            .map_err(|_| {
                LocalRuntimeError::new(
                    LocalRuntimeErrorCode::JournalFailed,
                    "local runtime state lock is poisoned",
                )
            })?
            .get(runtime_scope_id)
            .cloned())
    }

    pub fn stop(
        &self,
        runtime_scope_id: &str,
        sandbox_instance_id: &str,
    ) -> Result<InstanceStatus, LocalRuntimeError> {
        let _lock = ScopeLock::acquire(&self.data_root, runtime_scope_id)?;
        let mut active = self.active.lock().map_err(|_| {
            LocalRuntimeError::new(
                LocalRuntimeErrorCode::JournalFailed,
                "local runtime state lock is poisoned",
            )
        })?;
        let status = active.get(runtime_scope_id).cloned().ok_or_else(|| {
            LocalRuntimeError::new(
                LocalRuntimeErrorCode::InstanceConflict,
                "local runtime instance is not active",
            )
        })?;
        if status.sandbox_instance_id != sandbox_instance_id {
            return Err(LocalRuntimeError::new(
                LocalRuntimeErrorCode::InstanceConflict,
                "local runtime instance generation conflicts",
            ));
        }
        let record = self.journal.load(runtime_scope_id)?.ok_or_else(|| {
            LocalRuntimeError::new(
                LocalRuntimeErrorCode::JournalFailed,
                "local runtime instance is missing its journal",
            )
        })?;
        match self.driver.identity(record.pid)? {
            Some(identity)
                if identity.process_started_at == record.process_started_at
                    && identity.ownership_nonce == record.ownership_nonce => {}
            _ => {
                return Err(LocalRuntimeError::new(
                    LocalRuntimeErrorCode::ReconcileIdentityMismatch,
                    "local runtime process identity no longer matches its journal",
                ))
            }
        }
        self.journal.write(&JournalRecord {
            state: InstanceState::Stopping,
            updated_at: Utc::now(),
            ..record
        })?;
        self.driver.stop(status.pid)?;
        self.journal.remove(runtime_scope_id)?;
        active.remove(runtime_scope_id);
        Ok(InstanceStatus {
            state: InstanceState::Stopped,
            ..status
        })
    }

    pub fn reconcile(&self) -> Vec<ReconcileResult> {
        let records = match self.journal.list() {
            Ok(records) => records,
            Err(_) => {
                return vec![ReconcileResult {
                    runtime_scope_id: String::new(),
                    sandbox_instance_id: String::new(),
                    error_code: Some(LocalRuntimeErrorCode::JournalFailed),
                }]
            }
        };
        records
            .into_iter()
            .map(|record| {
                let _scope_lock = ScopeLock::acquire(&self.data_root, &record.runtime_scope_id);
                if _scope_lock.is_err() {
                    return ReconcileResult {
                        runtime_scope_id: record.runtime_scope_id,
                        sandbox_instance_id: record.sandbox_instance_id,
                        error_code: Some(LocalRuntimeErrorCode::JournalFailed),
                    };
                }
                let error_code = match self.driver.identity(record.pid) {
                    Ok(Some(identity))
                        if identity.process_started_at == record.process_started_at
                            && identity.ownership_nonce == record.ownership_nonce =>
                    {
                        match self.driver.stop(record.pid) {
                            Ok(()) => self
                                .journal
                                .remove(&record.runtime_scope_id)
                                .err()
                                .map(|error| error.code),
                            Err(error) => Some(error.code),
                        }
                    }
                    Ok(_) => Some(LocalRuntimeErrorCode::ReconcileIdentityMismatch),
                    Err(error) => Some(error.code),
                };
                ReconcileResult {
                    runtime_scope_id: record.runtime_scope_id,
                    sandbox_instance_id: record.sandbox_instance_id,
                    error_code,
                }
            })
            .collect()
    }
}

fn status_from_record(request: &StartRequest, record: &JournalRecord) -> InstanceStatus {
    InstanceStatus {
        runtime_scope_id: record.runtime_scope_id.clone(),
        application_id: record.application_id.clone(),
        sandbox_instance_id: record.sandbox_instance_id.clone(),
        state: InstanceState::Ready,
        pid: record.pid,
        runtime_base_url: format!("http://{}", request.runtime_addr),
        builder_url: format!("http://{}/builder/", request.runtime_addr),
        started_at: record.updated_at.to_rfc3339(),
    }
}

fn validate_request(data_root: &Path, request: &StartRequest) -> Result<(), LocalRuntimeError> {
    for value in [
        &request.runtime_scope_id,
        &request.application_id,
        &request.sandbox_instance_id,
    ] {
        if value.is_empty()
            || value.len() > 160
            || !value
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
        {
            return Err(LocalRuntimeError::new(
                LocalRuntimeErrorCode::InvalidRequest,
                "local runtime identifier is invalid",
            ));
        }
    }
    let address: SocketAddr = request.runtime_addr.parse().map_err(|_| {
        LocalRuntimeError::new(
            LocalRuntimeErrorCode::InvalidRequest,
            "runtime address is invalid",
        )
    })?;
    if !address.ip().is_loopback() || address.port() == 0 {
        return Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::InvalidRequest,
            "runtime address must be a non-zero loopback address",
        ));
    }
    let worktree = canonical(&request.worktree_path)?;
    let git_common = canonical(&request.git_common_dir)?;
    let codex_home = canonical(&request.codex_home)?;
    let runtime_dir = canonical(&request.runtime_dir)?;
    let runtime_context = canonical(&request.runtime_context_path)?;
    let agent_runtime = canonical(&request.agent_runtime_path)?;
    let root = canonical(data_root)?;
    let scope_root = root.join("local-runtimes").join(&request.runtime_scope_id);
    let expected_codex_home = canonical(&scope_root.join("codex-home"))?;
    let expected_runtime_dir = canonical(
        &scope_root
            .join("instances")
            .join(&request.sandbox_instance_id),
    )?;
    let expected_runtime_context = canonical(&expected_runtime_dir.join("runtime-context.json"))?;
    if !git_common.is_dir()
        || !agent_runtime.is_file()
        || actual_git_common_dir(&worktree)? != git_common
    {
        return Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::InvalidRequest,
            "managed Git worktree or runtime executable is invalid",
        ));
    }
    if !codex_home.starts_with(&root)
        || !runtime_dir.starts_with(&root)
        || !runtime_context.starts_with(&runtime_dir)
        || codex_home != expected_codex_home
        || runtime_dir != expected_runtime_dir
        || runtime_context != expected_runtime_context
    {
        return Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::InvalidRequest,
            "runtime paths escape desktop data directory",
        ));
    }
    if overlaps(&worktree, &codex_home)
        || overlaps(&worktree, &runtime_dir)
        || overlaps(&codex_home, &runtime_dir)
    {
        return Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::InvalidRequest,
            "runtime paths must not overlap",
        ));
    }
    for (key, value) in &request.environment {
        if !allowed_environment_key(key) {
            return Err(LocalRuntimeError::new(
                LocalRuntimeErrorCode::InvalidRequest,
                "runtime environment contains an unsupported key",
            ));
        }
        if matches!(key.as_str(), "APAAS_MODEL_PROVIDER_PATH")
            && !canonical(Path::new(value))?.starts_with(&runtime_dir)
        {
            return Err(LocalRuntimeError::new(
                LocalRuntimeErrorCode::InvalidRequest,
                "runtime secret path escapes instance directory",
            ));
        }
    }
    let sandbox_token_path = request
        .environment
        .get("APAAS_SANDBOX_TOKEN_PATH")
        .ok_or_else(|| {
            LocalRuntimeError::new(
                LocalRuntimeErrorCode::InvalidRequest,
                "runtime sandbox token path is required",
            )
        })?;
    validate_sandbox_token_path(sandbox_token_path, &runtime_dir)?;
    Ok(())
}

fn validate_sandbox_token_path(value: &str, runtime_dir: &Path) -> Result<(), LocalRuntimeError> {
    if value.is_empty() || value.contains('\0') {
        return Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::InvalidRequest,
            "runtime sandbox token path is invalid",
        ));
    }
    let expected = runtime_dir.join(SANDBOX_TOKEN_FILE);
    if Path::new(value) != expected {
        return Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::InvalidRequest,
            "runtime sandbox token path escapes instance directory",
        ));
    }
    let metadata = fs::symlink_metadata(&expected).map_err(|_| {
        LocalRuntimeError::new(
            LocalRuntimeErrorCode::InvalidRequest,
            "runtime sandbox token path is invalid",
        )
    })?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o777 != 0o600 {
            return Err(LocalRuntimeError::new(
                LocalRuntimeErrorCode::InvalidRequest,
                "runtime sandbox token file is invalid",
            ));
        }
    }
    if metadata.file_type().is_symlink() || !metadata.is_file() || metadata.len() == 0 {
        return Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::InvalidRequest,
            "runtime sandbox token file is invalid",
        ));
    }
    let token = fs::read(&expected).map_err(|_| {
        LocalRuntimeError::new(
            LocalRuntimeErrorCode::InvalidRequest,
            "runtime sandbox token file is invalid",
        )
    })?;
    if token.is_empty() || token.contains(&0) {
        return Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::InvalidRequest,
            "runtime sandbox token file is invalid",
        ));
    }
    Ok(())
}

pub(crate) fn read_sandbox_token(request: &StartRequest) -> Result<String, LocalRuntimeError> {
    let runtime_dir = canonical(&request.runtime_dir)?;
    let token_path = request
        .environment
        .get("APAAS_SANDBOX_TOKEN_PATH")
        .ok_or_else(|| {
            LocalRuntimeError::new(
                LocalRuntimeErrorCode::InvalidRequest,
                "runtime sandbox token path is required",
            )
        })?;
    validate_sandbox_token_path(token_path, &runtime_dir)?;

    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW);
    }
    let mut token_file = options.open(token_path).map_err(|_| {
        LocalRuntimeError::new(
            LocalRuntimeErrorCode::InvalidRequest,
            "runtime sandbox token file is invalid",
        )
    })?;
    let metadata = token_file.metadata().map_err(|_| {
        LocalRuntimeError::new(
            LocalRuntimeErrorCode::InvalidRequest,
            "runtime sandbox token file is invalid",
        )
    })?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o777 != 0o600 {
            return Err(LocalRuntimeError::new(
                LocalRuntimeErrorCode::InvalidRequest,
                "runtime sandbox token file is invalid",
            ));
        }
    }
    if !metadata.is_file() || metadata.len() == 0 {
        return Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::InvalidRequest,
            "runtime sandbox token file is invalid",
        ));
    }
    let mut token = String::new();
    token_file.read_to_string(&mut token).map_err(|_| {
        LocalRuntimeError::new(
            LocalRuntimeErrorCode::InvalidRequest,
            "runtime sandbox token file is invalid",
        )
    })?;
    if token.is_empty() || token.contains('\0') {
        return Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::InvalidRequest,
            "runtime sandbox token file is invalid",
        ));
    }
    Ok(token)
}

fn canonical(path: &Path) -> Result<PathBuf, LocalRuntimeError> {
    fs::canonicalize(path).map_err(|_| {
        LocalRuntimeError::new(
            LocalRuntimeErrorCode::InvalidRequest,
            "runtime path does not exist or is invalid",
        )
    })
}

fn actual_git_common_dir(worktree: &Path) -> Result<PathBuf, LocalRuntimeError> {
    let marker = worktree.join(".git");
    if marker.is_dir() {
        return canonical(&marker);
    }
    let contents = fs::read_to_string(&marker).map_err(|_| {
        LocalRuntimeError::new(
            LocalRuntimeErrorCode::InvalidRequest,
            "managed Git worktree is missing its .git marker",
        )
    })?;
    let target = contents
        .strip_prefix("gitdir: ")
        .or_else(|| contents.strip_prefix("gitdir:"))
        .map(str::trim)
        .filter(|path| !path.is_empty())
        .ok_or_else(|| {
            LocalRuntimeError::new(
                LocalRuntimeErrorCode::InvalidRequest,
                "managed Git worktree has an invalid .git marker",
            )
        })?;
    let target = PathBuf::from(target);
    let git_dir = if target.is_absolute() {
        target
    } else {
        worktree.join(target)
    };
    canonical(&git_dir)
}

fn overlaps(left: &Path, right: &Path) -> bool {
    left.starts_with(right) || right.starts_with(left)
}

fn allowed_environment_key(key: &str) -> bool {
    matches!(
        key,
        "APAAS_RUNTIME_CONTEXT_PATH"
            | "APAAS_MODEL_PROVIDER_PATH"
            | "APAAS_WORKSPACE_INIT_MODE"
            | "APAAS_CI_HANDOFF_MODE"
            | "APAAS_CODEX_SESSION_MODE"
            | "APAAS_REPO_WORKSPACE_PATH"
            | "APAAS_WORKSPACE_PATH"
            | "APAAS_RUNTIME_WORKSPACE_PATH"
            | "APAAS_CODEX_HOME"
            | "APAAS_RUNTIME_ADDR"
            | "APAAS_AUTH_MODE"
            | "APAAS_SANDBOX_TOKEN_PATH"
    )
}

struct ScopeLock(std::fs::File);
impl ScopeLock {
    fn acquire(data_root: &Path, scope: &str) -> Result<Self, LocalRuntimeError> {
        let path = data_root.join("local-runtimes").join(scope);
        fs::create_dir_all(&path).map_err(|_| {
            LocalRuntimeError::new(
                LocalRuntimeErrorCode::JournalFailed,
                "cannot create local runtime scope",
            )
        })?;
        #[cfg(unix)]
        use std::os::unix::fs::OpenOptionsExt;
        let mut options = OpenOptions::new();
        options.read(true).write(true).create(true);
        #[cfg(unix)]
        options.custom_flags(libc::O_NOFOLLOW);
        let file = options.open(path.join("runtime.lock")).map_err(|_| {
            LocalRuntimeError::new(
                LocalRuntimeErrorCode::JournalFailed,
                "cannot open local runtime lock",
            )
        })?;
        #[cfg(unix)]
        unsafe {
            if libc::flock(std::os::fd::AsRawFd::as_raw_fd(&file), libc::LOCK_EX) != 0 {
                return Err(LocalRuntimeError::new(
                    LocalRuntimeErrorCode::JournalFailed,
                    "cannot acquire local runtime lock",
                ));
            }
        }
        Ok(Self(file))
    }
}
impl Drop for ScopeLock {
    fn drop(&mut self) {
        #[cfg(unix)]
        unsafe {
            libc::flock(std::os::fd::AsRawFd::as_raw_fd(&self.0), libc::LOCK_UN);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[cfg(unix)]
    use std::os::unix::fs::PermissionsExt;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::time::{SystemTime, UNIX_EPOCH};

    struct FakeDriver {
        spawns: AtomicUsize,
        stops: AtomicUsize,
        identity: Option<ProcessIdentity>,
    }
    impl RuntimeDriver for FakeDriver {
        fn spawn(
            &self,
            _request: &StartRequest,
            nonce: &str,
        ) -> Result<ProcessIdentity, LocalRuntimeError> {
            self.spawns.fetch_add(1, Ordering::SeqCst);
            Ok(ProcessIdentity {
                pid: 41001,
                process_started_at: "start".into(),
                ownership_nonce: nonce.into(),
            })
        }
        fn wait_ready(&self, _: &StartRequest) -> Result<(), LocalRuntimeError> {
            Ok(())
        }
        fn stop(&self, _: u32) -> Result<(), LocalRuntimeError> {
            self.stops.fetch_add(1, Ordering::SeqCst);
            Ok(())
        }
        fn identity(&self, _: u32) -> Result<Option<ProcessIdentity>, LocalRuntimeError> {
            Ok(self.identity.clone())
        }
    }

    fn request(root: &Path, instance: &str) -> StartRequest {
        let worktree = root.join("worktree");
        let git_common = worktree.join(".git");
        let scope = root.join("local-runtimes").join("scope-a");
        let runtime = scope.join("instances").join(instance);
        let codex = scope.join("codex-home");
        fs::create_dir_all(&git_common).unwrap();
        fs::create_dir_all(&codex).unwrap();
        fs::create_dir_all(&runtime).unwrap();
        fs::write(runtime.join("runtime-context.json"), "{}").unwrap();
        fs::write(runtime.join("model-provider.json"), "{}").unwrap();
        fs::write(runtime.join("sandbox-token"), "entry-token").unwrap();
        #[cfg(unix)]
        fs::set_permissions(
            runtime.join("sandbox-token"),
            std::fs::Permissions::from_mode(0o600),
        )
        .unwrap();
        let executable = root.join("agent-runtime");
        fs::write(&executable, "#!/bin/sh\n").unwrap();
        StartRequest {
            runtime_scope_id: "scope-a".into(),
            application_id: "app-a".into(),
            sandbox_instance_id: instance.into(),
            workspace_id: "workspace-a".into(),
            worktree_path: worktree,
            git_common_dir: git_common,
            codex_home: codex,
            runtime_dir: runtime.clone(),
            runtime_context_path: runtime.join("runtime-context.json"),
            agent_runtime_path: executable,
            runtime_addr: "127.0.0.1:41001".into(),
            environment: [
                (
                    "APAAS_MODEL_PROVIDER_PATH".into(),
                    runtime.join("model-provider.json").display().to_string(),
                ),
                (
                    "APAAS_SANDBOX_TOKEN_PATH".into(),
                    runtime.join("sandbox-token").display().to_string(),
                ),
            ]
            .into_iter()
            .collect(),
        }
    }

    fn temp_root() -> PathBuf {
        let root = std::env::temp_dir().join(format!(
            "orcamatrix-manager-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir_all(&root).unwrap();
        root
    }

    #[test]
    fn repeated_start_of_same_instance_is_idempotent() {
        let root = temp_root();
        let driver = FakeDriver {
            spawns: AtomicUsize::new(0),
            stops: AtomicUsize::new(0),
            identity: None,
        };
        let manager = LocalRuntimeManager::new(&root, driver);
        let request = request(&root, "instance-a");
        let first = manager.start(request.clone()).unwrap();
        let second = manager.start(request).unwrap();
        assert_eq!(first.pid, second.pid);
        assert_eq!(manager.driver.spawns.load(Ordering::SeqCst), 1);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn another_instance_for_same_scope_conflicts() {
        let root = temp_root();
        let manager = LocalRuntimeManager::new(
            &root,
            FakeDriver {
                spawns: AtomicUsize::new(0),
                stops: AtomicUsize::new(0),
                identity: None,
            },
        );
        manager.start(request(&root, "instance-a")).unwrap();
        let error = manager.start(request(&root, "instance-b")).unwrap_err();
        assert_eq!(error.code, LocalRuntimeErrorCode::InstanceConflict);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn recovered_same_instance_is_idempotent_without_respawning() {
        let root = temp_root();
        let first_manager = LocalRuntimeManager::new(
            &root,
            FakeDriver {
                spawns: AtomicUsize::new(0),
                stops: AtomicUsize::new(0),
                identity: None,
            },
        );
        let request = request(&root, "instance-a");
        first_manager.start(request.clone()).unwrap();
        let record = first_manager.journal.load("scope-a").unwrap().unwrap();
        drop(first_manager);

        let recovered_driver = FakeDriver {
            spawns: AtomicUsize::new(0),
            stops: AtomicUsize::new(0),
            identity: Some(ProcessIdentity {
                pid: record.pid,
                process_started_at: record.process_started_at.clone(),
                ownership_nonce: record.ownership_nonce.clone(),
            }),
        };
        let manager = LocalRuntimeManager::new(&root, recovered_driver);
        let status = manager.start(request).unwrap();
        assert_eq!(status.sandbox_instance_id, "instance-a");
        assert_eq!(manager.driver.spawns.load(Ordering::SeqCst), 0);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn reconcile_does_not_kill_a_reused_pid() {
        let root = temp_root();
        let driver = FakeDriver {
            spawns: AtomicUsize::new(0),
            stops: AtomicUsize::new(0),
            identity: Some(ProcessIdentity {
                pid: 41001,
                process_started_at: "different-start-time".into(),
                ownership_nonce: "other-nonce".into(),
            }),
        };
        let manager = LocalRuntimeManager::new(&root, driver);
        manager
            .journal
            .write(&JournalRecord {
                runtime_scope_id: "scope-a".into(),
                application_id: "app-a".into(),
                sandbox_instance_id: "instance-a".into(),
                pid: 41001,
                process_started_at: "expected-start-time".into(),
                ownership_nonce: "expected-nonce".into(),
                worktree_path: root.join("worktree"),
                state: InstanceState::Ready,
                updated_at: Utc::now(),
            })
            .unwrap();
        let result = manager.reconcile();
        assert_eq!(
            result[0].error_code,
            Some(LocalRuntimeErrorCode::ReconcileIdentityMismatch)
        );
        assert_eq!(manager.driver.stops.load(Ordering::SeqCst), 0);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn request_allows_only_the_contained_sandbox_token_file() {
        let root = temp_root();
        let request = request(&root, "instance-a");
        assert!(validate_request(&root, &request).is_ok());

        let outside = root.join("outside-token");
        fs::write(&outside, "outside-token").unwrap();
        let mut escaped = request.clone();
        escaped.environment.insert(
            "APAAS_SANDBOX_TOKEN_PATH".into(),
            outside.display().to_string(),
        );
        let error = validate_request(&root, &escaped).unwrap_err();
        assert_eq!(error.code, LocalRuntimeErrorCode::InvalidRequest);

        let mut missing = request;
        missing.environment.remove("APAAS_SANDBOX_TOKEN_PATH");
        let error = validate_request(&root, &missing).unwrap_err();
        assert_eq!(error.code, LocalRuntimeErrorCode::InvalidRequest);
        fs::remove_dir_all(root).unwrap();
    }
}
