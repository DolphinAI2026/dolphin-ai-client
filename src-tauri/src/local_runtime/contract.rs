use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::path::PathBuf;
use thiserror::Error;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum InstanceState {
    Starting,
    Ready,
    Stopping,
    Stopped,
    Failed,
    Blocked,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct StartRequest {
    pub runtime_scope_id: String,
    pub application_id: String,
    pub sandbox_instance_id: String,
    pub workspace_id: String,
    pub worktree_path: PathBuf,
    pub git_common_dir: PathBuf,
    pub codex_home: PathBuf,
    pub runtime_dir: PathBuf,
    pub runtime_context_path: PathBuf,
    pub agent_runtime_path: PathBuf,
    pub runtime_addr: String,
    pub environment: BTreeMap<String, String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct InstanceStatus {
    pub runtime_scope_id: String,
    pub application_id: String,
    pub sandbox_instance_id: String,
    pub state: InstanceState,
    pub pid: u32,
    pub runtime_base_url: String,
    pub builder_url: String,
    pub started_at: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProcessIdentity {
    pub pid: u32,
    pub process_started_at: String,
    pub ownership_nonce: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LocalRuntimeErrorCode {
    UnsupportedPlatform,
    ProbeFailed,
    InvalidRequest,
    InstanceConflict,
    SpawnFailed,
    ReadinessFailed,
    StopFailed,
    JournalFailed,
    ReconcileIdentityMismatch,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ReconcileResult {
    pub runtime_scope_id: String,
    pub sandbox_instance_id: String,
    pub error_code: Option<LocalRuntimeErrorCode>,
}

#[derive(Debug, Error)]
#[error("{message}")]
pub struct LocalRuntimeError {
    pub code: LocalRuntimeErrorCode,
    pub message: String,
}

impl LocalRuntimeError {
    pub fn new(code: LocalRuntimeErrorCode, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }
}
