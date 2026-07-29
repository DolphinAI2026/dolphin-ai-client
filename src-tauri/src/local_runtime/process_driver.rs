use super::contract::{LocalRuntimeError, LocalRuntimeErrorCode, ProcessIdentity, StartRequest};
use super::manager::{read_sandbox_token, RuntimeDriver};
use std::collections::{BTreeMap, HashMap};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};
#[cfg(any(test, all(unix, not(any(target_os = "linux", target_os = "macos")))))]
use std::time::{SystemTime, UNIX_EPOCH};

pub(crate) const READINESS_TIMEOUT: Duration = Duration::from_secs(120);
pub(crate) const STOP_TIMEOUT: Duration = Duration::from_secs(5);
const RETAINED_FORCE_KILL_CONFIRMATION_RESERVE: Duration = Duration::from_secs(1);
const WINDOWS_CREATE_NO_WINDOW: u32 = 0x0800_0000;

#[derive(Debug, Clone, PartialEq, Eq)]
struct AppliancePaths {
    agent_runtime: PathBuf,
    codex: PathBuf,
    python: PathBuf,
}

fn appliance_paths_for_platform(appliance_root: &Path, windows: bool) -> AppliancePaths {
    let (agent_runtime, codex, python) = if windows {
        (
            "bin/agent-runtime.exe",
            "codex/bin/codex.exe",
            "agentic-coding/.venv/Scripts/python.exe",
        )
    } else {
        (
            "bin/agent-runtime",
            "codex/bin/codex",
            "agentic-coding/.venv/bin/python",
        )
    };
    AppliancePaths {
        agent_runtime: appliance_root.join(agent_runtime),
        codex: appliance_root.join(codex),
        python: appliance_root.join(python),
    }
}

fn appliance_paths(appliance_root: &Path) -> AppliancePaths {
    appliance_paths_for_platform(appliance_root, cfg!(target_os = "windows"))
}

pub(crate) fn agent_runtime_executable(appliance_root: &Path) -> PathBuf {
    appliance_paths(appliance_root).agent_runtime
}

#[cfg(target_os = "windows")]
#[repr(C)]
#[derive(Clone, Copy)]
struct FileTime {
    dw_low_date_time: u32,
    dw_high_date_time: u32,
}

#[cfg(target_os = "windows")]
unsafe extern "system" {
    fn GetProcessTimes(
        process: *mut std::ffi::c_void,
        creation_time: *mut FileTime,
        exit_time: *mut FileTime,
        kernel_time: *mut FileTime,
        user_time: *mut FileTime,
    ) -> i32;
    fn OpenProcess(
        desired_access: u32,
        inherit_handle: i32,
        process_id: u32,
    ) -> *mut std::ffi::c_void;
    fn CloseHandle(handle: *mut std::ffi::c_void) -> i32;
    fn QueryFullProcessImageNameW(
        process: *mut std::ffi::c_void,
        flags: u32,
        executable_name: *mut u16,
        size: *mut u32,
    ) -> i32;
    fn TerminateProcess(process: *mut std::ffi::c_void, exit_code: u32) -> i32;
    fn WaitForSingleObject(handle: *mut std::ffi::c_void, milliseconds: u32) -> u32;
}

#[cfg(target_os = "windows")]
const WINDOWS_PROCESS_TERMINATE: u32 = 0x0001;
#[cfg(target_os = "windows")]
const WINDOWS_PROCESS_QUERY_LIMITED_INFORMATION: u32 = 0x1000;
#[cfg(target_os = "windows")]
const WINDOWS_SYNCHRONIZE: u32 = 0x0010_0000;
#[cfg(target_os = "windows")]
const WINDOWS_WAIT_OBJECT_0: u32 = 0;
#[cfg(target_os = "windows")]
const WINDOWS_WAIT_TIMEOUT: u32 = 258;

struct LocalProcess {
    child: Child,
    identity: ProcessIdentity,
}

pub struct LocalProcessRuntimeDriver {
    processes: Mutex<HashMap<u32, LocalProcess>>,
    recovered_processes: Mutex<HashMap<u32, ProcessIdentity>>,
    appliance_root: PathBuf,
}

impl LocalProcessRuntimeDriver {
    pub fn with_appliance_root(appliance_root: impl Into<PathBuf>) -> Self {
        Self {
            processes: Mutex::new(HashMap::new()),
            recovered_processes: Mutex::new(HashMap::new()),
            appliance_root: appliance_root.into(),
        }
    }

    pub fn validate_agent_runtime(
        &self,
        request: &StartRequest,
    ) -> Result<PathBuf, LocalRuntimeError> {
        trusted_appliance_root(request, Some(&self.appliance_root))
    }
}

fn configure_runtime_command<F>(command: &mut Command, windows: bool, apply_creation_flags: F)
where
    F: FnOnce(&mut Command, u32),
{
    if windows {
        apply_creation_flags(command, WINDOWS_CREATE_NO_WINDOW);
    }
}

fn prepared_runtime_command<F>(
    request: &StartRequest,
    runtime_environment: impl IntoIterator<Item = (String, String)>,
    appliance_environment: impl IntoIterator<Item = (String, String)>,
    windows: bool,
    apply_creation_flags: F,
) -> Command
where
    F: FnOnce(&mut Command, u32),
{
    let mut command = Command::new(&request.agent_runtime_path);
    command.current_dir(&request.worktree_path).env_clear();
    for (key, value) in runtime_environment {
        command.env(key, value);
    }
    for (key, value) in appliance_environment {
        command.env(key, value);
    }
    configure_runtime_command(&mut command, windows, apply_creation_flags);
    command
}

#[cfg(target_os = "windows")]
fn apply_windows_creation_flags(command: &mut Command, flags: u32) {
    use std::os::windows::process::CommandExt;
    command.creation_flags(flags);
}

#[cfg(not(target_os = "windows"))]
fn apply_windows_creation_flags(command: &mut Command, flags: u32) {
    let _ = (command, flags);
}

#[cfg(any(test, all(unix, not(any(target_os = "linux", target_os = "macos")))))]
fn retained_process_identity(
    pid: u32,
    ownership_nonce: &str,
    started_at: SystemTime,
) -> Result<ProcessIdentity, LocalRuntimeError> {
    let process_started_at = started_at
        .duration_since(UNIX_EPOCH)
        .map_err(|error| {
            LocalRuntimeError::new(
                LocalRuntimeErrorCode::SpawnFailed,
                format!("cannot capture local runtime start time: {error}"),
            )
        })?
        .as_nanos()
        .to_string();
    Ok(ProcessIdentity {
        pid,
        process_started_at,
        ownership_nonce: ownership_nonce.to_string(),
    })
}

#[cfg(all(unix, not(any(target_os = "linux", target_os = "macos"))))]
fn retained_unix_process_identity(
    child: &mut Child,
    ownership_nonce: &str,
) -> Result<ProcessIdentity, LocalRuntimeError> {
    match child.try_wait() {
        Ok(None) => retained_process_identity(child.id(), ownership_nonce, SystemTime::now()),
        Ok(Some(_)) => Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::SpawnFailed,
            "local runtime exited before its identity was retained",
        )),
        Err(error) => Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::SpawnFailed,
            format!("cannot inspect local runtime after spawn: {error}"),
        )),
    }
}

impl RuntimeDriver for LocalProcessRuntimeDriver {
    fn spawn(
        &self,
        request: &StartRequest,
        ownership_nonce: &str,
    ) -> Result<ProcessIdentity, LocalRuntimeError> {
        let appliance_root = self.validate_agent_runtime(request)?;
        let mut command = prepared_runtime_command(
            request,
            runtime_environment(request, ownership_nonce, std::env::vars())?,
            appliance_environment(&appliance_root),
            cfg!(target_os = "windows"),
            apply_windows_creation_flags,
        );
        let mut child = command.spawn().map_err(|error| {
            LocalRuntimeError::new(
                LocalRuntimeErrorCode::SpawnFailed,
                format!("cannot start local runtime: {error}"),
            )
        })?;
        let pid = child.id();
        #[cfg(target_os = "windows")]
        let identity = match windows_process_identity(&child, ownership_nonce) {
            Ok(identity) => identity,
            Err(error) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(error);
            }
        };
        #[cfg(target_os = "linux")]
        let identity = match wait_for_spawned_process_identity(pid, ownership_nonce) {
            Err(error) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(error);
            }
            Ok(Some(identity)) if identity.ownership_nonce == ownership_nonce => identity,
            Ok(Some(_)) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(LocalRuntimeError::new(
                    LocalRuntimeErrorCode::SpawnFailed,
                    "local runtime did not receive the required ownership nonce",
                ));
            }
            Ok(None) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(LocalRuntimeError::new(
                    LocalRuntimeErrorCode::SpawnFailed,
                    "local runtime exited before its identity was available",
                ));
            }
        };
        #[cfg(all(unix, not(target_os = "linux")))]
        #[cfg(not(target_os = "macos"))]
        let identity = match retained_unix_process_identity(&mut child, ownership_nonce) {
            Ok(identity) => identity,
            Err(error) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(error);
            }
        };
        #[cfg(target_os = "macos")]
        let identity = match macos_spawned_process_identity(
            &mut child,
            ownership_nonce,
            &request.agent_runtime_path,
        ) {
            Ok(identity) => identity,
            Err(error) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(error);
            }
        };
        let mut processes = self.processes.lock().map_err(|_| {
            let _ = child.kill();
            let _ = child.wait();
            LocalRuntimeError::new(
                LocalRuntimeErrorCode::SpawnFailed,
                "local runtime registry lock is poisoned",
            )
        })?;
        processes.insert(
            pid,
            LocalProcess {
                child,
                identity: identity.clone(),
            },
        );
        Ok(identity)
    }

    fn wait_ready(&self, pid: u32, request: &StartRequest) -> Result<(), LocalRuntimeError> {
        if !self
            .processes
            .lock()
            .map_err(|_| {
                LocalRuntimeError::new(
                    LocalRuntimeErrorCode::ProbeFailed,
                    "local runtime registry lock is poisoned",
                )
            })?
            .contains_key(&pid)
        {
            return Err(LocalRuntimeError::new(
                LocalRuntimeErrorCode::ProbeFailed,
                "local runtime process is not retained",
            ));
        }
        let token = read_sandbox_token(request)?;
        wait_ready_with_token(&request.runtime_addr, &token, READINESS_TIMEOUT)
    }

    fn stop(&self, pid: u32) -> Result<(), LocalRuntimeError> {
        self.stop_retained_with_timeout_and_ops(
            pid,
            STOP_TIMEOUT,
            |child| child.try_wait().map(|status| status.is_some()),
            Child::kill,
        )
    }

    fn identity(&self, pid: u32) -> Result<Option<ProcessIdentity>, LocalRuntimeError> {
        Ok(self
            .processes
            .lock()
            .map_err(|_| {
                LocalRuntimeError::new(
                    LocalRuntimeErrorCode::ReconcileIdentityMismatch,
                    "local runtime registry lock is poisoned",
                )
            })?
            .get(&pid)
            .map(|process| process.identity.clone()))
    }

    fn recover_identity(
        &self,
        expected: &ProcessIdentity,
    ) -> Result<Option<ProcessIdentity>, LocalRuntimeError> {
        if let Some(retained) = self.identity(expected.pid)? {
            return Ok(Some(retained));
        }
        let recovered = platform_recovered_process_identity(
            expected,
            &agent_runtime_executable(&self.appliance_root),
        )?;
        if recovered.as_ref() == Some(expected) {
            self.recovered_processes
                .lock()
                .map_err(|_| {
                    LocalRuntimeError::new(
                        LocalRuntimeErrorCode::ReconcileIdentityMismatch,
                        "local runtime recovery registry lock is poisoned",
                    )
                })?
                .insert(expected.pid, expected.clone());
        }
        Ok(recovered)
    }
}

impl LocalProcessRuntimeDriver {
    fn stop_retained_with_timeout_and_ops<Inspect, Kill>(
        &self,
        pid: u32,
        timeout: Duration,
        mut has_exited: Inspect,
        mut force_kill: Kill,
    ) -> Result<(), LocalRuntimeError>
    where
        Inspect: FnMut(&mut Child) -> std::io::Result<bool>,
        Kill: FnMut(&mut Child) -> std::io::Result<()>,
    {
        let process = self
            .processes
            .lock()
            .map_err(|_| {
                LocalRuntimeError::new(
                    LocalRuntimeErrorCode::StopFailed,
                    "local runtime registry lock is poisoned",
                )
            })?
            .remove(&pid);
        let Some(mut process) = process else {
            return self.stop_recovered_process(pid);
        };
        if let Err(error) = stop_retained_child_before_deadline(
            &mut process.child,
            timeout,
            &mut has_exited,
            &mut force_kill,
        ) {
            self.restore_process(pid, process)?;
            return Err(error);
        }
        Ok(())
    }

    fn restore_process(&self, pid: u32, process: LocalProcess) -> Result<(), LocalRuntimeError> {
        self.processes
            .lock()
            .map_err(|_| {
                LocalRuntimeError::new(
                    LocalRuntimeErrorCode::StopFailed,
                    "local runtime registry lock is poisoned while restoring process",
                )
            })?
            .insert(pid, process);
        Ok(())
    }

    fn stop_recovered_process(&self, pid: u32) -> Result<(), LocalRuntimeError> {
        let expected = self
            .recovered_processes
            .lock()
            .map_err(|_| {
                LocalRuntimeError::new(
                    LocalRuntimeErrorCode::StopFailed,
                    "local runtime recovery registry lock is poisoned",
                )
            })?
            .remove(&pid)
            .ok_or_else(|| {
                LocalRuntimeError::new(
                    LocalRuntimeErrorCode::StopFailed,
                    "local runtime process is not retained",
                )
            })?;
        #[cfg(target_os = "linux")]
        {
            match platform_recovered_process_identity(
                &expected,
                &agent_runtime_executable(&self.appliance_root),
            )? {
                Some(actual) if actual == expected => stop_residual_unix_process(pid),
                _ => Err(LocalRuntimeError::new(
                    LocalRuntimeErrorCode::ReconcileIdentityMismatch,
                    "local runtime process identity changed before termination",
                )),
            }
        }
        #[cfg(target_os = "windows")]
        {
            stop_residual_windows_process(
                &expected,
                &agent_runtime_executable(&self.appliance_root),
            )
        }
        #[cfg(target_os = "macos")]
        {
            stop_residual_macos_process(&expected, &agent_runtime_executable(&self.appliance_root))
        }
        #[cfg(not(any(target_os = "linux", target_os = "windows", target_os = "macos")))]
        {
            let _ = expected;
            Err(LocalRuntimeError::new(
                LocalRuntimeErrorCode::StopFailed,
                "local runtime process is not retained",
            ))
        }
    }
}

fn stop_retained_child_before_deadline<Inspect, Kill>(
    child: &mut Child,
    timeout: Duration,
    has_exited: &mut Inspect,
    force_kill: &mut Kill,
) -> Result<(), LocalRuntimeError>
where
    Inspect: FnMut(&mut Child) -> std::io::Result<bool>,
    Kill: FnMut(&mut Child) -> std::io::Result<()>,
{
    let started = Instant::now();
    let deadline = started + timeout;
    let force_kill_at = deadline
        .checked_sub(timeout.min(RETAINED_FORCE_KILL_CONFIRMATION_RESERVE))
        .unwrap_or(started);
    if wait_for_retained_child_exit(child, force_kill_at, has_exited)? {
        return Ok(());
    }
    if Instant::now() >= deadline {
        return Err(retained_stop_deadline_error());
    }
    if let Err(error) = force_kill(child) {
        if has_exited(child).map_err(retained_inspection_error)? {
            return Ok(());
        }
        return Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::StopFailed,
            format!("cannot kill local runtime: {error}"),
        ));
    }
    if wait_for_retained_child_exit(child, deadline, has_exited)? {
        return Ok(());
    }
    Err(retained_stop_deadline_error())
}

fn wait_for_retained_child_exit<Inspect>(
    child: &mut Child,
    deadline: Instant,
    has_exited: &mut Inspect,
) -> Result<bool, LocalRuntimeError>
where
    Inspect: FnMut(&mut Child) -> std::io::Result<bool>,
{
    loop {
        if has_exited(child).map_err(retained_inspection_error)? {
            return Ok(true);
        }
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            return Ok(false);
        }
        thread::sleep(remaining.min(Duration::from_millis(100)));
    }
}

fn retained_inspection_error(error: std::io::Error) -> LocalRuntimeError {
    LocalRuntimeError::new(
        LocalRuntimeErrorCode::StopFailed,
        format!("cannot inspect local runtime: {error}"),
    )
}

fn retained_stop_deadline_error() -> LocalRuntimeError {
    LocalRuntimeError::new(
        LocalRuntimeErrorCode::StopFailed,
        "owned local runtime exit was not confirmed before the stop deadline",
    )
}

#[cfg(target_os = "linux")]
fn stop_residual_unix_process(pid: u32) -> Result<(), LocalRuntimeError> {
    let pid = i32::try_from(pid).map_err(|_| {
        LocalRuntimeError::new(
            LocalRuntimeErrorCode::StopFailed,
            "local runtime PID is invalid",
        )
    })?;
    let deadline = Instant::now() + STOP_TIMEOUT;
    signal_unix_process(pid, libc::SIGTERM)?;
    if wait_for_unix_process_exit(pid, deadline) {
        return Ok(());
    }
    signal_unix_process(pid, libc::SIGKILL)?;
    if wait_for_unix_process_exit(pid, deadline) {
        return Ok(());
    }
    Err(LocalRuntimeError::new(
        LocalRuntimeErrorCode::StopFailed,
        "owned local runtime did not exit after termination",
    ))
}

#[cfg(target_os = "linux")]
fn signal_unix_process(pid: i32, signal: i32) -> Result<(), LocalRuntimeError> {
    let result = unsafe { libc::kill(pid, signal) };
    if result == 0 || std::io::Error::last_os_error().raw_os_error() == Some(libc::ESRCH) {
        Ok(())
    } else {
        Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::StopFailed,
            format!(
                "cannot signal owned local runtime: {}",
                std::io::Error::last_os_error()
            ),
        ))
    }
}

#[cfg(target_os = "linux")]
fn wait_for_unix_process_exit(pid: i32, deadline: Instant) -> bool {
    loop {
        let mut status = 0;
        let waited = unsafe { libc::waitpid(pid, &mut status, libc::WNOHANG) };
        if waited == pid {
            return true;
        }
        let exists = unsafe { libc::kill(pid, 0) } == 0
            || std::io::Error::last_os_error().raw_os_error() == Some(libc::EPERM);
        if !exists {
            return true;
        }
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            return false;
        }
        thread::sleep(remaining.min(Duration::from_millis(100)));
    }
}

#[cfg(target_os = "windows")]
fn windows_process_identity(
    child: &Child,
    ownership_nonce: &str,
) -> Result<ProcessIdentity, LocalRuntimeError> {
    use std::os::windows::io::AsRawHandle;

    let process_started_at = windows_process_started_at(child.as_raw_handle())?;
    Ok(ProcessIdentity {
        pid: child.id(),
        process_started_at,
        ownership_nonce: ownership_nonce.to_string(),
    })
}

#[cfg(target_os = "windows")]
fn windows_process_started_at(process: *mut std::ffi::c_void) -> Result<String, LocalRuntimeError> {
    let mut creation_time = FileTime {
        dw_low_date_time: 0,
        dw_high_date_time: 0,
    };
    let mut exit_time = creation_time;
    let mut kernel_time = creation_time;
    let mut user_time = creation_time;
    let result = unsafe {
        GetProcessTimes(
            process,
            &mut creation_time,
            &mut exit_time,
            &mut kernel_time,
            &mut user_time,
        )
    };
    if result == 0 {
        return Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::SpawnFailed,
            "cannot read Windows runtime process creation time",
        ));
    }

    Ok(filetime_to_unix_nanoseconds(creation_time))
}

#[cfg(target_os = "windows")]
fn filetime_to_unix_nanoseconds(filetime: FileTime) -> String {
    const WINDOWS_TO_UNIX_EPOCH_100NS: u64 = 116_444_736_000_000_000;
    let ticks =
        (u64::from(filetime.dw_high_date_time) << 32) | u64::from(filetime.dw_low_date_time);
    (u128::from(ticks.saturating_sub(WINDOWS_TO_UNIX_EPOCH_100NS)) * 100).to_string()
}

#[cfg(target_os = "windows")]
struct WindowsProcessHandle(*mut std::ffi::c_void);

#[cfg(target_os = "windows")]
impl Drop for WindowsProcessHandle {
    fn drop(&mut self) {
        unsafe {
            CloseHandle(self.0);
        }
    }
}

#[cfg(target_os = "windows")]
fn open_windows_process(
    pid: u32,
    access: u32,
) -> Result<Option<WindowsProcessHandle>, LocalRuntimeError> {
    let handle = unsafe { OpenProcess(access, 0, pid) };
    if handle.is_null() {
        let error = std::io::Error::last_os_error();
        if error.raw_os_error() == Some(87) {
            return Ok(None);
        }
        return Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::ReconcileIdentityMismatch,
            format!("cannot open local runtime process: {error}"),
        ));
    }
    Ok(Some(WindowsProcessHandle(handle)))
}

#[cfg(target_os = "windows")]
fn windows_process_path(handle: &WindowsProcessHandle) -> Result<PathBuf, LocalRuntimeError> {
    let mut buffer = vec![0_u16; 32_768];
    let mut length = u32::try_from(buffer.len()).expect("Windows path buffer length fits u32");
    if unsafe { QueryFullProcessImageNameW(handle.0, 0, buffer.as_mut_ptr(), &mut length) } == 0 {
        return Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::ReconcileIdentityMismatch,
            format!(
                "cannot read local runtime executable path: {}",
                std::io::Error::last_os_error()
            ),
        ));
    }
    Ok(PathBuf::from(String::from_utf16_lossy(
        &buffer[..length as usize],
    )))
}

#[cfg(target_os = "windows")]
fn recovered_windows_process_identity(
    expected: &ProcessIdentity,
    expected_executable: &Path,
) -> Result<Option<ProcessIdentity>, LocalRuntimeError> {
    let handle = match open_windows_process(
        expected.pid,
        WINDOWS_PROCESS_QUERY_LIMITED_INFORMATION | WINDOWS_SYNCHRONIZE,
    )? {
        Some(handle) => handle,
        None => return Ok(None),
    };
    match unsafe { WaitForSingleObject(handle.0, 0) } {
        WINDOWS_WAIT_OBJECT_0 => return Ok(None),
        WINDOWS_WAIT_TIMEOUT => {}
        _ => {
            return Err(LocalRuntimeError::new(
                LocalRuntimeErrorCode::ReconcileIdentityMismatch,
                format!(
                    "cannot inspect local runtime process state: {}",
                    std::io::Error::last_os_error()
                ),
            ))
        }
    }
    let process_started_at = windows_process_started_at(handle.0)?;
    let actual_executable = fs::canonicalize(windows_process_path(&handle)?).map_err(|error| {
        LocalRuntimeError::new(
            LocalRuntimeErrorCode::ReconcileIdentityMismatch,
            format!("cannot resolve local runtime executable path: {error}"),
        )
    })?;
    let expected_executable = fs::canonicalize(expected_executable).map_err(|error| {
        LocalRuntimeError::new(
            LocalRuntimeErrorCode::ReconcileIdentityMismatch,
            format!("cannot resolve trusted local runtime executable: {error}"),
        )
    })?;
    Ok(Some(ProcessIdentity {
        pid: expected.pid,
        ownership_nonce: if process_started_at == expected.process_started_at
            && actual_executable == expected_executable
        {
            expected.ownership_nonce.clone()
        } else {
            String::new()
        },
        process_started_at,
    }))
}

#[cfg(target_os = "windows")]
fn stop_residual_windows_process(
    expected: &ProcessIdentity,
    expected_executable: &Path,
) -> Result<(), LocalRuntimeError> {
    if recovered_windows_process_identity(expected, expected_executable)?.as_ref() != Some(expected)
    {
        return Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::ReconcileIdentityMismatch,
            "local runtime process identity changed before termination",
        ));
    }
    let handle = open_windows_process(
        expected.pid,
        WINDOWS_PROCESS_TERMINATE | WINDOWS_PROCESS_QUERY_LIMITED_INFORMATION | WINDOWS_SYNCHRONIZE,
    )?
    .ok_or_else(|| {
        LocalRuntimeError::new(
            LocalRuntimeErrorCode::StopFailed,
            "owned local runtime exited before termination",
        )
    })?;
    if unsafe { WaitForSingleObject(handle.0, 0) } == WINDOWS_WAIT_OBJECT_0 {
        return Ok(());
    }
    let process_started_at = windows_process_started_at(handle.0)?;
    let actual_executable = fs::canonicalize(windows_process_path(&handle)?).map_err(|error| {
        LocalRuntimeError::new(
            LocalRuntimeErrorCode::ReconcileIdentityMismatch,
            format!("cannot resolve local runtime executable path: {error}"),
        )
    })?;
    let expected_executable = fs::canonicalize(expected_executable).map_err(|error| {
        LocalRuntimeError::new(
            LocalRuntimeErrorCode::ReconcileIdentityMismatch,
            format!("cannot resolve trusted local runtime executable: {error}"),
        )
    })?;
    if process_started_at != expected.process_started_at || actual_executable != expected_executable
    {
        return Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::ReconcileIdentityMismatch,
            "local runtime process identity changed before termination",
        ));
    }
    if unsafe { TerminateProcess(handle.0, 1) } == 0 {
        return Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::StopFailed,
            format!(
                "cannot terminate owned local runtime: {}",
                std::io::Error::last_os_error()
            ),
        ));
    }
    match unsafe { WaitForSingleObject(handle.0, STOP_TIMEOUT.as_millis() as u32) } {
        WINDOWS_WAIT_OBJECT_0 => Ok(()),
        WINDOWS_WAIT_TIMEOUT => Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::StopFailed,
            "owned local runtime did not exit after termination",
        )),
        _ => Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::StopFailed,
            format!(
                "cannot wait for owned local runtime: {}",
                std::io::Error::last_os_error()
            ),
        )),
    }
}

#[cfg(target_os = "macos")]
fn macos_process_snapshot(pid: u32) -> Result<Option<(String, PathBuf)>, LocalRuntimeError> {
    use std::os::unix::ffi::OsStringExt;

    let pid = i32::try_from(pid).map_err(|_| {
        LocalRuntimeError::new(
            LocalRuntimeErrorCode::ReconcileIdentityMismatch,
            "local runtime PID is invalid",
        )
    })?;
    let mut info = std::mem::MaybeUninit::<libc::proc_bsdinfo>::zeroed();
    let info_size = std::mem::size_of::<libc::proc_bsdinfo>();
    let read = unsafe {
        libc::proc_pidinfo(
            pid,
            libc::PROC_PIDTBSDINFO,
            0,
            info.as_mut_ptr().cast(),
            info_size as i32,
        )
    };
    if read == 0 {
        let error = std::io::Error::last_os_error();
        if matches!(error.raw_os_error(), Some(libc::ESRCH) | Some(libc::EINVAL)) {
            return Ok(None);
        }
        return Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::ReconcileIdentityMismatch,
            format!("cannot read local runtime process information: {error}"),
        ));
    }
    if read as usize != info_size {
        return Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::ReconcileIdentityMismatch,
            "local runtime process information is incomplete",
        ));
    }
    let info = unsafe { info.assume_init() };
    let process_started_at = (u128::from(info.pbi_start_tvsec) * 1_000_000_000
        + u128::from(info.pbi_start_tvusec) * 1_000)
        .to_string();
    let mut path = vec![0_u8; libc::PROC_PIDPATHINFO_MAXSIZE as usize];
    let path_length = unsafe {
        libc::proc_pidpath(
            pid,
            path.as_mut_ptr().cast(),
            libc::PROC_PIDPATHINFO_MAXSIZE as u32,
        )
    };
    if path_length <= 0 {
        return Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::ReconcileIdentityMismatch,
            format!(
                "cannot read local runtime executable path: {}",
                std::io::Error::last_os_error()
            ),
        ));
    }
    path.truncate(path_length as usize);
    if let Some(nul) = path.iter().position(|byte| *byte == 0) {
        path.truncate(nul);
    }
    Ok(Some((
        process_started_at,
        PathBuf::from(std::ffi::OsString::from_vec(path)),
    )))
}

#[cfg(target_os = "macos")]
fn macos_spawned_process_identity(
    child: &mut Child,
    ownership_nonce: &str,
    expected_executable: &Path,
) -> Result<ProcessIdentity, LocalRuntimeError> {
    let expected_executable = fs::canonicalize(expected_executable).map_err(|error| {
        LocalRuntimeError::new(
            LocalRuntimeErrorCode::SpawnFailed,
            format!("cannot resolve trusted local runtime executable: {error}"),
        )
    })?;
    let deadline = Instant::now() + Duration::from_secs(1);
    loop {
        if child
            .try_wait()
            .map_err(|error| {
                LocalRuntimeError::new(
                    LocalRuntimeErrorCode::SpawnFailed,
                    format!("cannot inspect local runtime after spawn: {error}"),
                )
            })?
            .is_some()
        {
            return Err(LocalRuntimeError::new(
                LocalRuntimeErrorCode::SpawnFailed,
                "local runtime exited before its identity was retained",
            ));
        }
        if let Some((process_started_at, executable)) = macos_process_snapshot(child.id())? {
            let executable = fs::canonicalize(executable).map_err(|error| {
                LocalRuntimeError::new(
                    LocalRuntimeErrorCode::SpawnFailed,
                    format!("cannot resolve local runtime executable path: {error}"),
                )
            })?;
            if executable == expected_executable {
                return Ok(ProcessIdentity {
                    pid: child.id(),
                    process_started_at,
                    ownership_nonce: ownership_nonce.to_string(),
                });
            }
        }
        if Instant::now() >= deadline {
            return Err(LocalRuntimeError::new(
                LocalRuntimeErrorCode::SpawnFailed,
                "local runtime executable does not match the trusted appliance entrypoint",
            ));
        }
        thread::sleep(Duration::from_millis(10));
    }
}

#[cfg(target_os = "macos")]
fn recovered_macos_process_identity(
    expected: &ProcessIdentity,
    expected_executable: &Path,
) -> Result<Option<ProcessIdentity>, LocalRuntimeError> {
    let Some((process_started_at, executable)) = macos_process_snapshot(expected.pid)? else {
        return Ok(None);
    };
    let executable = fs::canonicalize(executable).map_err(|error| {
        LocalRuntimeError::new(
            LocalRuntimeErrorCode::ReconcileIdentityMismatch,
            format!("cannot resolve local runtime executable path: {error}"),
        )
    })?;
    let expected_executable = fs::canonicalize(expected_executable).map_err(|error| {
        LocalRuntimeError::new(
            LocalRuntimeErrorCode::ReconcileIdentityMismatch,
            format!("cannot resolve trusted local runtime executable: {error}"),
        )
    })?;
    let path_matches = executable == expected_executable;
    Ok(Some(ProcessIdentity {
        pid: expected.pid,
        ownership_nonce: if process_started_at == expected.process_started_at && path_matches {
            expected.ownership_nonce.clone()
        } else {
            String::new()
        },
        process_started_at,
    }))
}

#[cfg(target_os = "macos")]
fn stop_residual_macos_process(
    expected: &ProcessIdentity,
    expected_executable: &Path,
) -> Result<(), LocalRuntimeError> {
    if recovered_macos_process_identity(expected, expected_executable)?.as_ref() != Some(expected) {
        return Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::ReconcileIdentityMismatch,
            "local runtime process identity changed before termination",
        ));
    }
    let pid = i32::try_from(expected.pid).map_err(|_| {
        LocalRuntimeError::new(
            LocalRuntimeErrorCode::StopFailed,
            "local runtime PID is invalid",
        )
    })?;
    let deadline = Instant::now() + STOP_TIMEOUT;
    signal_macos_process(pid, libc::SIGTERM)?;
    if wait_for_macos_process_exit(pid, deadline) {
        return Ok(());
    }
    signal_macos_process(pid, libc::SIGKILL)?;
    if wait_for_macos_process_exit(pid, deadline) {
        return Ok(());
    }
    Err(LocalRuntimeError::new(
        LocalRuntimeErrorCode::StopFailed,
        "owned local runtime did not exit after termination",
    ))
}

#[cfg(target_os = "macos")]
fn signal_macos_process(pid: i32, signal: i32) -> Result<(), LocalRuntimeError> {
    let result = unsafe { libc::kill(pid, signal) };
    if result == 0 || std::io::Error::last_os_error().raw_os_error() == Some(libc::ESRCH) {
        Ok(())
    } else {
        Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::StopFailed,
            format!(
                "cannot signal owned local runtime: {}",
                std::io::Error::last_os_error()
            ),
        ))
    }
}

#[cfg(target_os = "macos")]
fn wait_for_macos_process_exit(pid: i32, deadline: Instant) -> bool {
    loop {
        let mut status = 0;
        if unsafe { libc::waitpid(pid, &mut status, libc::WNOHANG) } == pid {
            return true;
        }
        let exists = unsafe { libc::kill(pid, 0) } == 0
            || std::io::Error::last_os_error().raw_os_error() == Some(libc::EPERM);
        if !exists {
            return true;
        }
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            return false;
        }
        thread::sleep(remaining.min(Duration::from_millis(100)));
    }
}

#[cfg(target_os = "linux")]
fn platform_recovered_process_identity(
    expected: &ProcessIdentity,
    expected_executable: &Path,
) -> Result<Option<ProcessIdentity>, LocalRuntimeError> {
    recovered_linux_process_identity(expected, expected_executable)
}

#[cfg(target_os = "windows")]
fn platform_recovered_process_identity(
    expected: &ProcessIdentity,
    expected_executable: &Path,
) -> Result<Option<ProcessIdentity>, LocalRuntimeError> {
    recovered_windows_process_identity(expected, expected_executable)
}

#[cfg(target_os = "macos")]
fn platform_recovered_process_identity(
    expected: &ProcessIdentity,
    expected_executable: &Path,
) -> Result<Option<ProcessIdentity>, LocalRuntimeError> {
    recovered_macos_process_identity(expected, expected_executable)
}

#[cfg(not(any(target_os = "linux", target_os = "windows", target_os = "macos")))]
fn platform_recovered_process_identity(
    _expected: &ProcessIdentity,
    _expected_executable: &Path,
) -> Result<Option<ProcessIdentity>, LocalRuntimeError> {
    Ok(None)
}

#[cfg(target_os = "linux")]
fn wait_for_spawned_process_identity(
    pid: u32,
    _ownership_nonce: &str,
) -> Result<Option<ProcessIdentity>, LocalRuntimeError> {
    let deadline = Instant::now() + Duration::from_secs(1);
    loop {
        match unix_process_identity(pid)? {
            Some(identity) => return Ok(Some(identity)),
            None if Instant::now() >= deadline => return Ok(None),
            None => thread::sleep(Duration::from_millis(10)),
        }
    }
}

pub(crate) fn wait_ready_with_token(
    runtime_addr: &str,
    token: &str,
    timeout: Duration,
) -> Result<(), LocalRuntimeError> {
    let url = format!("http://{runtime_addr}/api/status");
    let agent = ureq::AgentBuilder::new()
        .timeout_connect(Duration::from_secs(1))
        .timeout_read(Duration::from_secs(1))
        .build();
    let authorization = format!("Bearer {token}");
    let deadline = Instant::now() + timeout;
    loop {
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            break;
        }
        if agent
            .get(&url)
            .set("Authorization", &authorization)
            .timeout(remaining.min(Duration::from_secs(1)))
            .call()
            .map(|response| response.status() == 200)
            .unwrap_or(false)
        {
            return Ok(());
        }
        let remaining = deadline.saturating_duration_since(Instant::now());
        thread::sleep(remaining.min(Duration::from_millis(200)));
    }
    Err(LocalRuntimeError::new(
        LocalRuntimeErrorCode::ReadinessFailed,
        format!(
            "local runtime did not become ready within {} seconds",
            timeout.as_secs()
        ),
    ))
}

fn trusted_appliance_root(
    request: &StartRequest,
    configured_root: Option<&Path>,
) -> Result<PathBuf, LocalRuntimeError> {
    let agent_runtime = fs::canonicalize(&request.agent_runtime_path).map_err(|_| {
        LocalRuntimeError::new(
            LocalRuntimeErrorCode::InvalidRequest,
            "agent runtime executable is unavailable",
        )
    })?;
    if let Some(configured_root) = configured_root {
        let root = fs::canonicalize(configured_root).map_err(|_| {
            LocalRuntimeError::new(
                LocalRuntimeErrorCode::InvalidRequest,
                "local runtime appliance is unavailable",
            )
        })?;
        let expected_runtime = fs::canonicalize(agent_runtime_executable(&root)).map_err(|_| {
            LocalRuntimeError::new(
                LocalRuntimeErrorCode::InvalidRequest,
                "local runtime appliance is missing its runtime executable",
            )
        })?;
        if agent_runtime != expected_runtime {
            return Err(LocalRuntimeError::new(
                LocalRuntimeErrorCode::InvalidRequest,
                "agent runtime executable is outside the trusted local appliance entrypoint",
            ));
        }
        return Ok(root);
    }
    agent_runtime
        .parent()
        .and_then(Path::parent)
        .map(Path::to_path_buf)
        .ok_or_else(|| {
            LocalRuntimeError::new(
                LocalRuntimeErrorCode::InvalidRequest,
                "agent runtime executable has no appliance root",
            )
        })
}

fn appliance_environment(appliance_root: &Path) -> Vec<(String, String)> {
    let paths = appliance_paths(appliance_root);
    vec![
        (
            "DOLPHIN_CODE_CODEX_APP_SERVER_BINARY".to_string(),
            paths.codex.display().to_string(),
        ),
        (
            "DOLPHIN_CODE_AGENTIC_PACK_DIR".to_string(),
            appliance_root
                .join("agentic-coding-pack")
                .display()
                .to_string(),
        ),
        (
            "DOLPHIN_CODE_BUILDER_DIST_DIR".to_string(),
            appliance_root
                .join("web/builder/dist")
                .display()
                .to_string(),
        ),
        (
            "AGENTIC_ROOT".to_string(),
            appliance_root.join("agentic-coding").display().to_string(),
        ),
        (
            "AGENTIC_PACK_PYTHON".to_string(),
            paths.python.display().to_string(),
        ),
    ]
}

fn filtered_environment(
    request: &StartRequest,
    ownership_nonce: &str,
) -> Result<Vec<(String, String)>, LocalRuntimeError> {
    let mut environment = BTreeMap::new();
    for (key, value) in &request.environment {
        let Some(target_key) = mapped_environment_key(key) else {
            return Err(LocalRuntimeError::new(
                LocalRuntimeErrorCode::InvalidRequest,
                "local runtime environment contains an unsupported value",
            ));
        };
        if value.contains('\0') {
            return Err(LocalRuntimeError::new(
                LocalRuntimeErrorCode::InvalidRequest,
                "local runtime environment contains an unsupported value",
            ));
        }
        if environment
            .insert(target_key.to_string(), value.clone())
            .is_some()
        {
            return Err(LocalRuntimeError::new(
                LocalRuntimeErrorCode::InvalidRequest,
                "local runtime environment contains conflicting mappings",
            ));
        }
    }
    if environment
        .insert(
            "APAAS_RUNTIME_OWNERSHIP_NONCE".to_string(),
            ownership_nonce.to_string(),
        )
        .is_some()
    {
        return Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::InvalidRequest,
            "local runtime environment contains conflicting mappings",
        ));
    }
    Ok(environment.into_iter().collect())
}

fn runtime_environment<I>(
    request: &StartRequest,
    ownership_nonce: &str,
    host_environment: I,
) -> Result<Vec<(String, String)>, LocalRuntimeError>
where
    I: IntoIterator<Item = (String, String)>,
{
    let environment = filtered_environment(request, ownership_nonce)?;
    #[cfg(target_os = "windows")]
    {
        let system_proxy = windows_system_proxy();
        return windows_runtime_environment(
            environment,
            host_environment,
            system_proxy.as_deref(),
            &request.codex_home,
            &request.runtime_dir,
        );
    }
    #[cfg(not(target_os = "windows"))]
    {
        let _ = host_environment;
        let mut environment = environment;
        environment.extend([
            ("HOME".to_string(), request.codex_home.display().to_string()),
            (
                "USERPROFILE".to_string(),
                request.codex_home.display().to_string(),
            ),
            (
                "TEMP".to_string(),
                request.runtime_dir.display().to_string(),
            ),
            ("TMP".to_string(), request.runtime_dir.display().to_string()),
        ]);
        Ok(environment)
    }
}

fn mapped_environment_key(key: &str) -> Option<&'static str> {
    match key {
        "APAAS_RUNTIME_CONTEXT_PATH" => Some("DOLPHIN_CODE_RUNTIME_CONTEXT_PATH"),
        "APAAS_MODEL_PROVIDER_PATH" => Some("DOLPHIN_CODE_MODEL_PROVIDER_PATH"),
        "APAAS_WORKSPACE_INIT_MODE" => Some("DOLPHIN_CODE_WORKSPACE_INIT_MODE"),
        "APAAS_CI_HANDOFF_MODE" => Some("DOLPHIN_CODE_CI_HANDOFF_MODE"),
        "APAAS_CODEX_SESSION_MODE" => Some("DOLPHIN_CODE_CODEX_SESSION_MODE"),
        "APAAS_REPO_WORKSPACE_PATH" => Some("DOLPHIN_CODE_REPO_WORKSPACE_PATH"),
        "APAAS_WORKSPACE_PATH" => Some("DOLPHIN_CODE_WORKSPACE_PATH"),
        "APAAS_RUNTIME_WORKSPACE_PATH" => Some("DOLPHIN_CODE_RUNTIME_WORKSPACE_PATH"),
        "APAAS_CODEX_HOME" => Some("DOLPHIN_CODE_CODEX_HOME"),
        "APAAS_RUNTIME_ADDR" => Some("DOLPHIN_CODE_RUNTIME_ADDR"),
        "APAAS_AUTH_MODE" => Some("DOLPHIN_CODE_AUTH_MODE"),
        "APAAS_SANDBOX_TOKEN_PATH" => Some("DOLPHIN_CODE_SANDBOX_TOKEN_PATH"),
        _ => None,
    }
}

#[cfg(target_os = "windows")]
fn windows_system_proxy() -> Option<String> {
    use std::net::{Ipv4Addr, SocketAddr, TcpStream};
    use winreg::enums::HKEY_CURRENT_USER;
    use winreg::RegKey;

    let internet_settings = RegKey::predef(HKEY_CURRENT_USER)
        .open_subkey("Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings")
        .ok()?;
    let proxy_server: String = internet_settings.get_value("ProxyServer").ok()?;
    let proxy_url = normalize_windows_proxy(&proxy_server)?;
    let proxy_enabled = internet_settings
        .get_value::<u32, _>("ProxyEnable")
        .unwrap_or_default()
        != 0;
    if proxy_enabled {
        return Some(proxy_url);
    }

    let authority = proxy_url
        .split_once("://")
        .map(|(_, value)| value)
        .unwrap_or(proxy_url.as_str())
        .split('/')
        .next()?;
    let (host, port) = authority.rsplit_once(':')?;
    if !matches!(
        host.trim_matches(['[', ']']),
        "127.0.0.1" | "localhost" | "::1"
    ) {
        return None;
    }
    let address = SocketAddr::from((Ipv4Addr::LOCALHOST, port.parse::<u16>().ok()?));
    TcpStream::connect_timeout(&address, Duration::from_millis(150))
        .ok()
        .map(|_| proxy_url)
}

#[cfg(any(target_os = "windows", test))]
fn normalize_windows_proxy(value: &str) -> Option<String> {
    let value = value.trim();
    if value.is_empty() || value.chars().any(char::is_control) {
        return None;
    }
    let selected = if value.contains(';') {
        ["https", "http", "socks"].into_iter().find_map(|scheme| {
            value.split(';').find_map(|entry| {
                let (key, target) = entry.split_once('=')?;
                (key.trim().eq_ignore_ascii_case(scheme)).then(|| target.trim())
            })
        })?
    } else {
        value
    };
    if selected.is_empty() || selected.chars().any(char::is_whitespace) {
        return None;
    }
    if selected.contains("://") {
        Some(selected.to_string())
    } else {
        Some(format!("http://{selected}"))
    }
}

#[cfg(any(target_os = "windows", test))]
fn windows_runtime_environment<I>(
    runtime_environment: Vec<(String, String)>,
    host_environment: I,
    system_proxy: Option<&str>,
    runtime_home: &Path,
    runtime_temp: &Path,
) -> Result<Vec<(String, String)>, LocalRuntimeError>
where
    I: IntoIterator<Item = (String, String)>,
{
    let mut host = BTreeMap::new();
    for (key, value) in host_environment {
        if !key.is_empty() && !value.contains('\0') {
            host.insert(key.to_ascii_uppercase(), value);
        }
    }

    let mut environment = BTreeMap::new();
    for key in [
        "SYSTEMROOT",
        "COMSPEC",
        "PATH",
        "PATHEXT",
        "SYSTEMDRIVE",
        "WINDIR",
    ] {
        if let Some(value) = host.get(key).filter(|value| !value.is_empty()) {
            environment.insert(key.to_string(), value.clone());
        }
    }
    for key in ["SYSTEMROOT", "COMSPEC", "PATH"] {
        if !environment.contains_key(key) {
            return Err(LocalRuntimeError::new(
                LocalRuntimeErrorCode::SpawnFailed,
                format!("Windows runtime host environment is missing required {key}"),
            ));
        }
    }

    let appdata = runtime_home.join("AppData");
    let runtime_home = runtime_home.display().to_string();
    let runtime_temp = runtime_temp.display().to_string();
    environment.insert("USERPROFILE".to_string(), runtime_home.clone());
    environment.insert("HOME".to_string(), runtime_home);
    environment.insert(
        "APPDATA".to_string(),
        appdata.join("Roaming").display().to_string(),
    );
    environment.insert(
        "LOCALAPPDATA".to_string(),
        appdata.join("Local").display().to_string(),
    );
    environment.insert("TEMP".to_string(), runtime_temp.clone());
    environment.insert("TMP".to_string(), runtime_temp);

    for key in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"] {
        if let Some(value) = host.get(key).filter(|value| !value.is_empty()) {
            environment.insert(key.to_string(), value.clone());
        }
    }
    let fallback_proxy = environment
        .get("HTTPS_PROXY")
        .or_else(|| environment.get("HTTP_PROXY"))
        .or_else(|| environment.get("ALL_PROXY"))
        .cloned()
        .or_else(|| system_proxy.map(str::to_string));
    if let Some(proxy) = fallback_proxy {
        environment
            .entry("HTTP_PROXY".to_string())
            .or_insert_with(|| proxy.clone());
        environment
            .entry("HTTPS_PROXY".to_string())
            .or_insert(proxy);
    }
    let mut no_proxy = host.get("NO_PROXY").cloned().unwrap_or_default();
    for local_host in ["127.0.0.1", "localhost", "::1"] {
        if !no_proxy.split(',').any(|entry| entry.trim() == local_host) {
            if !no_proxy.is_empty() {
                no_proxy.push(',');
            }
            no_proxy.push_str(local_host);
        }
    }
    environment.insert("NO_PROXY".to_string(), no_proxy);

    for (key, value) in runtime_environment {
        if key.is_empty() || value.contains('\0') {
            return Err(LocalRuntimeError::new(
                LocalRuntimeErrorCode::InvalidRequest,
                "local runtime environment contains an unsupported value",
            ));
        }
        if matches!(
            key.to_ascii_uppercase().as_str(),
            "SYSTEMROOT"
                | "COMSPEC"
                | "PATH"
                | "PATHEXT"
                | "SYSTEMDRIVE"
                | "WINDIR"
                | "APPDATA"
                | "LOCALAPPDATA"
                | "USERPROFILE"
                | "HOME"
                | "TEMP"
                | "TMP"
        ) {
            return Err(LocalRuntimeError::new(
                LocalRuntimeErrorCode::InvalidRequest,
                "local runtime environment cannot override Windows bootstrap variables",
            ));
        }
        if environment
            .insert(key.to_ascii_uppercase(), value)
            .is_some()
        {
            return Err(LocalRuntimeError::new(
                LocalRuntimeErrorCode::InvalidRequest,
                "local runtime environment contains conflicting mappings",
            ));
        }
    }
    Ok(environment.into_iter().collect())
}

#[cfg(target_os = "linux")]
fn unix_process_identity(pid: u32) -> Result<Option<ProcessIdentity>, LocalRuntimeError> {
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

#[cfg(target_os = "linux")]
fn recovered_linux_process_identity(
    expected: &ProcessIdentity,
    expected_executable: &Path,
) -> Result<Option<ProcessIdentity>, LocalRuntimeError> {
    let Some(mut identity) = unix_process_identity(expected.pid)? else {
        return Ok(None);
    };
    let executable = match fs::read_link(format!("/proc/{}/exe", expected.pid)) {
        Ok(path) => fs::canonicalize(path).map_err(|error| {
            LocalRuntimeError::new(
                LocalRuntimeErrorCode::ReconcileIdentityMismatch,
                format!("cannot resolve local runtime executable path: {error}"),
            )
        })?,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => {
            return Err(LocalRuntimeError::new(
                LocalRuntimeErrorCode::ReconcileIdentityMismatch,
                format!("cannot read local runtime executable path: {error}"),
            ))
        }
    };
    let expected_executable = fs::canonicalize(expected_executable).map_err(|error| {
        LocalRuntimeError::new(
            LocalRuntimeErrorCode::ReconcileIdentityMismatch,
            format!("cannot resolve trusted local runtime executable: {error}"),
        )
    })?;
    if identity.process_started_at != expected.process_started_at
        || identity.ownership_nonce != expected.ownership_nonce
        || executable != expected_executable
    {
        identity.ownership_nonce.clear();
    }
    Ok(Some(identity))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[cfg(unix)]
    fn build_sleeping_runtime(appliance_root: &Path) -> PathBuf {
        let bin_dir = appliance_root.join("bin");
        fs::create_dir_all(&bin_dir).unwrap();
        let source = appliance_root.join("sleeping-runtime.rs");
        fs::write(
            &source,
            "fn main() { loop { std::thread::sleep(std::time::Duration::from_secs(60)); } }\n",
        )
        .unwrap();
        let executable = bin_dir.join("agent-runtime");
        let status = Command::new("rustc")
            .arg("--edition=2021")
            .arg(&source)
            .arg("-o")
            .arg(&executable)
            .status()
            .unwrap();
        assert!(status.success(), "compile sleeping test runtime");
        executable
    }

    #[cfg(unix)]
    struct TestRuntimeProcess(u32);

    #[cfg(unix)]
    impl Drop for TestRuntimeProcess {
        fn drop(&mut self) {
            unsafe {
                libc::kill(self.0 as i32, libc::SIGKILL);
                libc::waitpid(self.0 as i32, std::ptr::null_mut(), 0);
            }
        }
    }

    #[cfg(target_os = "linux")]
    struct UnreapedTestProcess {
        supervisor_pid: i32,
        target_pid: i32,
    }

    #[cfg(target_os = "linux")]
    impl UnreapedTestProcess {
        fn spawn_ignoring_sigterm() -> Self {
            let mut pipe_fds = [0; 2];
            assert_eq!(unsafe { libc::pipe(pipe_fds.as_mut_ptr()) }, 0);
            let supervisor_pid = unsafe { libc::fork() };
            assert!(supervisor_pid >= 0);
            if supervisor_pid == 0 {
                unsafe {
                    libc::close(pipe_fds[0]);
                    let target_pid = libc::fork();
                    if target_pid == 0 {
                        libc::signal(libc::SIGTERM, libc::SIG_IGN);
                        let pid = libc::getpid();
                        libc::write(
                            pipe_fds[1],
                            (&pid as *const i32).cast(),
                            std::mem::size_of::<i32>(),
                        );
                        libc::close(pipe_fds[1]);
                        loop {
                            libc::pause();
                        }
                    }
                    libc::close(pipe_fds[1]);
                    if target_pid < 0 {
                        libc::_exit(2);
                    }
                    loop {
                        libc::pause();
                    }
                }
            }
            unsafe {
                libc::close(pipe_fds[1]);
            }
            let mut target_pid = 0_i32;
            let bytes_read = unsafe {
                libc::read(
                    pipe_fds[0],
                    (&mut target_pid as *mut i32).cast(),
                    std::mem::size_of::<i32>(),
                )
            };
            unsafe {
                libc::close(pipe_fds[0]);
            }
            assert_eq!(bytes_read, std::mem::size_of::<i32>() as isize);
            assert!(target_pid > 0);
            Self {
                supervisor_pid,
                target_pid,
            }
        }
    }

    #[cfg(target_os = "linux")]
    impl Drop for UnreapedTestProcess {
        fn drop(&mut self) {
            unsafe {
                libc::kill(self.target_pid, libc::SIGKILL);
                libc::kill(self.supervisor_pid, libc::SIGKILL);
                libc::waitpid(self.supervisor_pid, std::ptr::null_mut(), 0);
            }
        }
    }

    fn request() -> StartRequest {
        StartRequest {
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
            environment: [("APAAS_RUNTIME_ADDR".into(), "127.0.0.1:41001".into())]
                .into_iter()
                .collect(),
        }
    }

    fn host_environment() -> Vec<(String, String)> {
        vec![("HTTPS_PROXY".into(), "http://host-proxy".into())]
    }

    fn value(environment: &[(String, String)], key: &str) -> Option<String> {
        environment
            .iter()
            .find(|(candidate, _)| candidate == key)
            .map(|(_, value)| value.clone())
    }

    #[test]
    fn process_environment_excludes_proxy_and_uses_runtime_directories() {
        let mappings = [
            (
                "APAAS_RUNTIME_CONTEXT_PATH",
                "DOLPHIN_CODE_RUNTIME_CONTEXT_PATH",
            ),
            (
                "APAAS_MODEL_PROVIDER_PATH",
                "DOLPHIN_CODE_MODEL_PROVIDER_PATH",
            ),
            (
                "APAAS_WORKSPACE_INIT_MODE",
                "DOLPHIN_CODE_WORKSPACE_INIT_MODE",
            ),
            ("APAAS_CI_HANDOFF_MODE", "DOLPHIN_CODE_CI_HANDOFF_MODE"),
            (
                "APAAS_CODEX_SESSION_MODE",
                "DOLPHIN_CODE_CODEX_SESSION_MODE",
            ),
            (
                "APAAS_REPO_WORKSPACE_PATH",
                "DOLPHIN_CODE_REPO_WORKSPACE_PATH",
            ),
            ("APAAS_WORKSPACE_PATH", "DOLPHIN_CODE_WORKSPACE_PATH"),
            (
                "APAAS_RUNTIME_WORKSPACE_PATH",
                "DOLPHIN_CODE_RUNTIME_WORKSPACE_PATH",
            ),
            ("APAAS_CODEX_HOME", "DOLPHIN_CODE_CODEX_HOME"),
            ("APAAS_RUNTIME_ADDR", "DOLPHIN_CODE_RUNTIME_ADDR"),
            ("APAAS_AUTH_MODE", "DOLPHIN_CODE_AUTH_MODE"),
            (
                "APAAS_SANDBOX_TOKEN_PATH",
                "DOLPHIN_CODE_SANDBOX_TOKEN_PATH",
            ),
        ];
        let mut request = request();
        request.environment = mappings
            .iter()
            .enumerate()
            .map(|(index, (source, _))| (source.to_string(), format!("value-{index}")))
            .collect();
        let mut host_environment = host_environment();
        host_environment.push((
            "DOLPHIN_CODE_RUNTIME_ADDR".into(),
            "host-value-must-not-pass".into(),
        ));

        let environment = runtime_environment(&request, "nonce-a", host_environment).unwrap();

        for (index, (source, target)) in mappings.iter().enumerate() {
            assert_eq!(value(&environment, target), Some(format!("value-{index}")));
            assert_eq!(value(&environment, source), None);
        }
        assert_eq!(
            value(&environment, "HOME"),
            Some(request.codex_home.display().to_string())
        );
        assert_eq!(
            value(&environment, "USERPROFILE"),
            Some(request.codex_home.display().to_string())
        );
        assert_eq!(
            value(&environment, "TEMP"),
            Some(request.runtime_dir.display().to_string())
        );
        assert_eq!(
            value(&environment, "APAAS_RUNTIME_OWNERSHIP_NONCE"),
            Some("nonce-a".into())
        );
        assert_eq!(value(&environment, "HTTPS_PROXY"), None);
    }

    #[test]
    fn process_environment_rejects_untrusted_request_values() {
        let mut request = request();
        request
            .environment
            .insert("UNTRUSTED_HOST_ENV".into(), "must-not-pass".into());

        let error = runtime_environment(&request, "nonce-a", host_environment()).unwrap_err();
        assert_eq!(error.code, LocalRuntimeErrorCode::InvalidRequest);
    }

    #[test]
    fn process_environment_rejects_direct_dolphin_request_values() {
        let mut request = request();
        request
            .environment
            .insert("DOLPHIN_CODE_RUNTIME_ADDR".into(), "must-not-pass".into());

        let error = runtime_environment(&request, "nonce-a", host_environment()).unwrap_err();
        assert_eq!(error.code, LocalRuntimeErrorCode::InvalidRequest);
    }

    #[test]
    fn appliance_environment_uses_dolphin_binary_paths_and_agentic_roots() {
        let appliance_root = Path::new("/opt/dolphin-code");
        let environment = appliance_environment(appliance_root);

        assert_eq!(
            value(&environment, "DOLPHIN_CODE_CODEX_APP_SERVER_BINARY"),
            Some(appliance_paths(appliance_root).codex.display().to_string())
        );
        assert_eq!(
            value(&environment, "DOLPHIN_CODE_AGENTIC_PACK_DIR"),
            Some(
                appliance_root
                    .join("agentic-coding-pack")
                    .display()
                    .to_string()
            )
        );
        assert_eq!(
            value(&environment, "AGENTIC_ROOT"),
            Some(appliance_root.join("agentic-coding").display().to_string())
        );
        assert_eq!(
            value(&environment, "AGENTIC_PACK_PYTHON"),
            Some(appliance_paths(appliance_root).python.display().to_string())
        );
        assert_eq!(value(&environment, "APAAS_CODEX_APP_SERVER_BINARY"), None);
        assert_eq!(value(&environment, "APAAS_AGENTIC_PACK_DIR"), None);
    }

    #[test]
    fn appliance_environment_declares_builder_distribution() {
        let appliance_root = Path::new("/opt/dolphin-code");
        let environment = appliance_environment(appliance_root);

        assert_eq!(
            value(&environment, "DOLPHIN_CODE_BUILDER_DIST_DIR"),
            Some(
                appliance_root
                    .join("web/builder/dist")
                    .display()
                    .to_string()
            )
        );
    }

    #[test]
    fn windows_environment_keeps_bootstrap_and_runtime_paths_controlled() {
        assert_eq!(
            normalize_windows_proxy("http=127.0.0.1:7897;https=127.0.0.1:7897"),
            Some("http://127.0.0.1:7897".to_string())
        );
        let environment = windows_runtime_environment(
            vec![("DOLPHIN_CODE_RUNTIME_ADDR".into(), "127.0.0.1:41001".into())],
            vec![
                ("SystemRoot".into(), "C:\\Windows".into()),
                ("ComSpec".into(), "C:\\Windows\\System32\\cmd.exe".into()),
                ("Path".into(), "C:\\Windows\\System32".into()),
            ],
            Some("http://127.0.0.1:7897"),
            Path::new("C:\\runtime\\codex-home"),
            Path::new("C:\\runtime\\instance"),
        )
        .unwrap();
        let environment: HashMap<_, _> = environment.into_iter().collect();

        assert_eq!(
            environment.get("SYSTEMROOT"),
            Some(&"C:\\Windows".to_string())
        );
        assert_eq!(
            environment.get("USERPROFILE"),
            Some(&Path::new("C:\\runtime\\codex-home").display().to_string())
        );
        assert_eq!(
            environment.get("TEMP"),
            Some(&Path::new("C:\\runtime\\instance").display().to_string())
        );
        assert_eq!(
            environment.get("DOLPHIN_CODE_RUNTIME_ADDR"),
            Some(&"127.0.0.1:41001".to_string())
        );
        assert_eq!(
            environment.get("HTTPS_PROXY"),
            Some(&"http://127.0.0.1:7897".to_string())
        );
        assert_eq!(
            environment.get("NO_PROXY"),
            Some(&"127.0.0.1,localhost,::1".to_string())
        );
    }

    #[test]
    fn windows_environment_rejects_duplicate_runtime_keys() {
        let error = windows_runtime_environment(
            vec![
                ("DOLPHIN_CODE_RUNTIME_ADDR".into(), "first".into()),
                ("DOLPHIN_CODE_RUNTIME_ADDR".into(), "second".into()),
            ],
            vec![
                ("SystemRoot".into(), "C:\\Windows".into()),
                ("ComSpec".into(), "C:\\Windows\\System32\\cmd.exe".into()),
                ("Path".into(), "C:\\Windows\\System32".into()),
            ],
            None,
            Path::new("C:\\runtime\\codex-home"),
            Path::new("C:\\runtime\\instance"),
        )
        .unwrap_err();

        assert_eq!(error.code, LocalRuntimeErrorCode::InvalidRequest);
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn filetime_creation_timestamp_converts_to_unix_nanoseconds_deterministically() {
        let filetime = FileTime {
            dw_low_date_time: 0xd53e_8000,
            dw_high_date_time: 0x019d_b1de,
        };

        assert_eq!(filetime_to_unix_nanoseconds(filetime), "0");
    }

    #[cfg(unix)]
    #[test]
    fn successful_stop_reaps_and_removes_the_retained_process() {
        let appliance_root = std::env::temp_dir().join(format!(
            "orcamatrix-process-driver-lifecycle-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let runtime = build_sleeping_runtime(&appliance_root);
        let mut request = request();
        request.agent_runtime_path = runtime;
        request.worktree_path = std::env::current_dir().expect("current working directory");
        let driver = LocalProcessRuntimeDriver::with_appliance_root(&appliance_root);
        let identity = driver
            .spawn(&request, "test-nonce")
            .expect("spawn test process");

        driver.stop(identity.pid).expect("stop test process");
        assert_eq!(
            driver
                .identity(identity.pid)
                .expect("read process identity"),
            None
        );
        std::fs::remove_dir_all(appliance_root).expect("remove test appliance directory");
    }

    #[cfg(unix)]
    #[test]
    fn retained_child_timeout_is_bounded_and_preserves_process_ownership() {
        let appliance_root = std::env::temp_dir().join(format!(
            "orcamatrix-process-driver-retained-timeout-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let runtime = build_sleeping_runtime(&appliance_root);
        let mut request = request();
        request.agent_runtime_path = runtime;
        request.worktree_path = std::env::current_dir().expect("current working directory");
        let driver = LocalProcessRuntimeDriver::with_appliance_root(&appliance_root);
        let identity = driver
            .spawn(&request, "retained-timeout-nonce")
            .expect("spawn test process");
        let kill_attempted = std::cell::Cell::new(false);
        let started = Instant::now();

        let error = driver
            .stop_retained_with_timeout_and_ops(
                identity.pid,
                Duration::from_millis(50),
                |_| Ok::<bool, std::io::Error>(false),
                |_| {
                    kill_attempted.set(true);
                    Ok::<(), std::io::Error>(())
                },
            )
            .unwrap_err();
        let elapsed = started.elapsed();

        assert_eq!(error.code, LocalRuntimeErrorCode::StopFailed);
        assert!(error.message.contains("deadline"));
        assert!(kill_attempted.get());
        assert!(elapsed < Duration::from_millis(500));
        assert_eq!(
            driver.identity(identity.pid).unwrap(),
            Some(identity.clone())
        );

        driver
            .stop_retained_with_timeout_and_ops(
                identity.pid,
                Duration::from_secs(1),
                |child| child.try_wait().map(|status| status.is_some()),
                Child::kill,
            )
            .expect("clean up retained test process");
        std::fs::remove_dir_all(appliance_root).expect("remove test appliance directory");
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn recovered_process_stop_rejects_an_executable_changed_after_recovery() {
        let appliance_root = std::env::temp_dir().join(format!(
            "orcamatrix-process-driver-recovery-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let runtime = build_sleeping_runtime(&appliance_root);
        let mut request = request();
        request.agent_runtime_path = runtime.clone();
        request.worktree_path = std::env::current_dir().expect("current working directory");
        let first_driver = LocalProcessRuntimeDriver::with_appliance_root(&appliance_root);
        let identity = first_driver
            .spawn(&request, "recovery-nonce")
            .expect("spawn test process");
        let process = TestRuntimeProcess(identity.pid);
        drop(first_driver);

        let fresh_driver = LocalProcessRuntimeDriver::with_appliance_root(&appliance_root);
        assert_eq!(
            fresh_driver.recover_identity(&identity).unwrap(),
            Some(identity.clone())
        );
        fs::rename(&runtime, appliance_root.join("bin/original-agent-runtime")).unwrap();
        build_sleeping_runtime(&appliance_root);

        let error = fresh_driver.stop(identity.pid).unwrap_err();

        assert_eq!(error.code, LocalRuntimeErrorCode::ReconcileIdentityMismatch);
        assert_eq!(unsafe { libc::kill(identity.pid as i32, 0) }, 0);
        drop(process);
        std::fs::remove_dir_all(appliance_root).expect("remove test appliance directory");
    }

    #[test]
    fn readiness_rejects_an_unretained_process() {
        let driver = LocalProcessRuntimeDriver::with_appliance_root("/tmp/appliance");
        let error = driver.wait_ready(41001, &request()).unwrap_err();
        assert_eq!(error.code, LocalRuntimeErrorCode::ProbeFailed);
    }

    #[test]
    fn readiness_allows_the_runtime_up_to_120_seconds() {
        assert_eq!(READINESS_TIMEOUT, Duration::from_secs(120));
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn residual_linux_stop_shares_one_timeout_between_term_and_kill() {
        let process = UnreapedTestProcess::spawn_ignoring_sigterm();
        let started = Instant::now();

        let error = stop_residual_unix_process(process.target_pid as u32).unwrap_err();
        let elapsed = started.elapsed();

        assert_eq!(error.code, LocalRuntimeErrorCode::StopFailed);
        assert!(
            elapsed <= STOP_TIMEOUT + Duration::from_secs(1),
            "stop took {elapsed:?}, exceeding the single {STOP_TIMEOUT:?} budget"
        );
    }

    #[test]
    fn windows_spawn_command_applies_the_no_window_creation_flag() {
        let request = request();
        let observed_flags = std::cell::Cell::new(None);

        let command =
            prepared_runtime_command(&request, Vec::new(), Vec::new(), true, |_, flags| {
                observed_flags.set(Some(flags))
            });

        assert_eq!(
            command.get_program(),
            request.agent_runtime_path.as_os_str()
        );
        assert_eq!(observed_flags.get(), Some(WINDOWS_CREATE_NO_WINDOW));
    }

    #[test]
    fn appliance_paths_match_windows_and_unix_layouts() {
        let root = Path::new("/opt/dolphin/agent-runtime");
        let unix = appliance_paths_for_platform(root, false);
        assert_eq!(unix.agent_runtime, root.join("bin/agent-runtime"));
        assert_eq!(unix.codex, root.join("codex/bin/codex"));
        assert_eq!(unix.python, root.join("agentic-coding/.venv/bin/python"));

        let windows = appliance_paths_for_platform(root, true);
        assert_eq!(windows.agent_runtime, root.join("bin/agent-runtime.exe"));
        assert_eq!(windows.codex, root.join("codex/bin/codex.exe"));
        assert_eq!(
            windows.python,
            root.join("agentic-coding/.venv/Scripts/python.exe")
        );
    }

    #[test]
    fn retained_identity_keeps_the_owned_process_nonce() {
        let started_at = UNIX_EPOCH + Duration::from_secs(42);
        let identity = retained_process_identity(41001, "nonce-a", started_at).unwrap();
        assert_eq!(identity.pid, 41001);
        assert_eq!(identity.process_started_at, "42000000000");
        assert_eq!(identity.ownership_nonce, "nonce-a");
    }

    #[test]
    fn readiness_error_reports_the_supplied_deadline() {
        let error = wait_ready_with_token("127.0.0.1:9", "token", Duration::ZERO).unwrap_err();
        assert_eq!(error.code, LocalRuntimeErrorCode::ReadinessFailed);
        assert!(error.message.contains("0 seconds"));
    }

    #[test]
    fn readiness_probe_sends_the_runtime_token_as_bearer_authorization() {
        use std::sync::{Arc, Mutex};

        let server = tiny_http::Server::http("127.0.0.1:0").unwrap();
        let runtime_addr = server.server_addr().to_string();
        let authorization = Arc::new(Mutex::new(None));
        let observed = Arc::clone(&authorization);
        let responder = std::thread::spawn(move || {
            let request = server
                .recv_timeout(Duration::from_secs(2))
                .unwrap()
                .unwrap();
            *observed.lock().unwrap() = request
                .headers()
                .iter()
                .find(|header| header.field.equiv("Authorization"))
                .map(|header| header.value.as_str().to_string());
            request.respond(tiny_http::Response::empty(200)).unwrap();
        });

        wait_ready_with_token(&runtime_addr, "test-token", Duration::from_secs(2)).unwrap();
        responder.join().unwrap();
        assert_eq!(
            authorization.lock().unwrap().as_deref(),
            Some("Bearer test-token")
        );
    }

    #[test]
    fn process_driver_rejects_runtime_outside_the_trusted_appliance() {
        let root =
            std::env::temp_dir().join(format!("orcamatrix-process-driver-{}", std::process::id()));
        let appliance = root.join("appliance");
        let outside = root.join("outside-agent-runtime");
        std::fs::create_dir_all(appliance.join("bin")).unwrap();
        std::fs::write(appliance.join("bin/agent-runtime"), "runtime").unwrap();
        std::fs::write(&outside, "runtime").unwrap();
        let mut outside_request = request();
        outside_request.agent_runtime_path = outside;
        let error = LocalProcessRuntimeDriver::with_appliance_root(&appliance)
            .validate_agent_runtime(&outside_request)
            .unwrap_err();
        assert_eq!(error.code, LocalRuntimeErrorCode::InvalidRequest);
        std::fs::remove_dir_all(root).unwrap();
    }
}
