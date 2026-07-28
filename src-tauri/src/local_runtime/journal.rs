use super::contract::{InstanceState, LocalRuntimeError, LocalRuntimeErrorCode};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct JournalRecord {
    pub runtime_scope_id: String,
    pub application_id: String,
    pub sandbox_instance_id: String,
    pub pid: u32,
    pub process_started_at: String,
    pub ownership_nonce: String,
    pub worktree_path: PathBuf,
    pub state: InstanceState,
    pub updated_at: DateTime<Utc>,
}

#[derive(Debug, Clone)]
pub struct JournalStore {
    root: PathBuf,
}

impl JournalStore {
    pub fn new(root: impl Into<PathBuf>) -> Self {
        Self { root: root.into() }
    }

    fn path(&self, runtime_scope_id: &str) -> PathBuf {
        self.root
            .join(runtime_scope_id)
            .join("runtime-journal.json")
    }

    pub fn load(&self, runtime_scope_id: &str) -> Result<Option<JournalRecord>, LocalRuntimeError> {
        let path = self.path(runtime_scope_id);
        match fs::read(&path) {
            Ok(bytes) => serde_json::from_slice(&bytes).map(Some).map_err(|error| {
                LocalRuntimeError::new(
                    LocalRuntimeErrorCode::JournalFailed,
                    format!("invalid local runtime journal: {error}"),
                )
            }),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
            Err(error) => Err(LocalRuntimeError::new(
                LocalRuntimeErrorCode::JournalFailed,
                format!("cannot read local runtime journal: {error}"),
            )),
        }
    }

    pub fn write(&self, record: &JournalRecord) -> Result<(), LocalRuntimeError> {
        let path = self.path(&record.runtime_scope_id);
        let parent = path.parent().expect("journal path has parent");
        fs::create_dir_all(parent).map_err(|error| {
            LocalRuntimeError::new(
                LocalRuntimeErrorCode::JournalFailed,
                format!("cannot create local runtime journal directory: {error}"),
            )
        })?;
        let temporary = parent.join(format!(
            ".runtime-journal.{}-{}.tmp",
            std::process::id(),
            Utc::now().timestamp_nanos_opt().unwrap_or_default()
        ));
        let payload = serde_json::to_vec_pretty(record).map_err(|error| {
            LocalRuntimeError::new(
                LocalRuntimeErrorCode::JournalFailed,
                format!("cannot encode local runtime journal: {error}"),
            )
        })?;
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)
            .map_err(|error| {
                LocalRuntimeError::new(
                    LocalRuntimeErrorCode::JournalFailed,
                    format!("cannot create local runtime journal: {error}"),
                )
            })?;
        file.write_all(&payload)
            .and_then(|_| file.write_all(b"\n"))
            .and_then(|_| file.sync_all())
            .map_err(|error| {
                LocalRuntimeError::new(
                    LocalRuntimeErrorCode::JournalFailed,
                    format!("cannot persist local runtime journal: {error}"),
                )
            })?;
        fs::rename(&temporary, &path).map_err(|error| {
            LocalRuntimeError::new(
                LocalRuntimeErrorCode::JournalFailed,
                format!("cannot replace local runtime journal: {error}"),
            )
        })?;
        sync_directory(parent)?;
        Ok(())
    }

    pub fn remove(&self, runtime_scope_id: &str) -> Result<(), LocalRuntimeError> {
        let path = self.path(runtime_scope_id);
        match fs::remove_file(&path) {
            Ok(()) => {
                if let Some(parent) = path.parent() {
                    sync_directory(parent)?;
                }
                Ok(())
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
            Err(error) => Err(LocalRuntimeError::new(
                LocalRuntimeErrorCode::JournalFailed,
                format!("cannot remove local runtime journal: {error}"),
            )),
        }
    }

    pub fn list(&self) -> Result<Vec<JournalRecord>, LocalRuntimeError> {
        let entries = match fs::read_dir(&self.root) {
            Ok(entries) => entries,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(Vec::new()),
            Err(error) => {
                return Err(LocalRuntimeError::new(
                    LocalRuntimeErrorCode::JournalFailed,
                    format!("cannot enumerate local runtime journals: {error}"),
                ))
            }
        };
        let mut records = Vec::new();
        for entry in entries {
            let entry = entry.map_err(|error| {
                LocalRuntimeError::new(
                    LocalRuntimeErrorCode::JournalFailed,
                    format!("cannot enumerate local runtime journals: {error}"),
                )
            })?;
            if !entry
                .file_type()
                .map_err(|error| {
                    LocalRuntimeError::new(
                        LocalRuntimeErrorCode::JournalFailed,
                        format!("cannot inspect local runtime journal: {error}"),
                    )
                })?
                .is_dir()
            {
                continue;
            }
            if let Some(record) = self.load(&entry.file_name().to_string_lossy())? {
                records.push(record);
            }
        }
        Ok(records)
    }
}

fn sync_directory(path: &Path) -> Result<(), LocalRuntimeError> {
    File::open(path)
        .and_then(|file| file.sync_all())
        .map_err(|error| {
            LocalRuntimeError::new(
                LocalRuntimeErrorCode::JournalFailed,
                format!("cannot sync local runtime journal directory: {error}"),
            )
        })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn temp_root() -> PathBuf {
        let path = std::env::temp_dir().join(format!(
            "orcamatrix-journal-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir_all(&path).unwrap();
        path
    }

    #[test]
    fn journal_round_trip_preserves_ownership_identity() {
        let root = temp_root();
        let store = JournalStore::new(&root);
        let record = JournalRecord {
            runtime_scope_id: "scope-a".into(),
            application_id: "app-a".into(),
            sandbox_instance_id: "instance-a".into(),
            pid: 41001,
            process_started_at: "1234".into(),
            ownership_nonce: "nonce-a".into(),
            worktree_path: root.join("worktree"),
            state: InstanceState::Ready,
            updated_at: Utc::now(),
        };
        store.write(&record).unwrap();
        let loaded = store.load("scope-a").unwrap().unwrap();
        assert_eq!(loaded.sandbox_instance_id, "instance-a");
        assert_eq!(loaded.ownership_nonce, "nonce-a");
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn journal_payload_has_no_driver_selector() {
        let root = temp_root();
        let record = JournalRecord {
            runtime_scope_id: "scope-a".into(),
            application_id: "app-a".into(),
            sandbox_instance_id: "instance-a".into(),
            pid: 41001,
            process_started_at: "1234".into(),
            ownership_nonce: "nonce-a".into(),
            worktree_path: root.join("worktree"),
            state: InstanceState::Ready,
            updated_at: Utc::now(),
        };
        let payload = serde_json::to_value(&record).unwrap();
        assert!(payload.get(&["runtime", "mode"].join("_")).is_none());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn journal_load_ignores_a_legacy_selector_field() {
        let root = temp_root();
        let store = JournalStore::new(&root);
        let mut payload = serde_json::json!({
            "runtime_scope_id": "scope-a",
            "application_id": "app-a",
            "sandbox_instance_id": "instance-a",
            "pid": 41001,
            "process_started_at": "1234",
            "ownership_nonce": "nonce-a",
            "worktree_path": root.join("worktree"),
            "state": "ready",
            "updated_at": Utc::now(),
        });
        payload
            .as_object_mut()
            .unwrap()
            .insert(["runtime", "mode"].join("_"), "fast_local".into());
        let path = root.join("scope-a").join("runtime-journal.json");
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, serde_json::to_vec(&payload).unwrap()).unwrap();

        let loaded = store.load("scope-a").unwrap().unwrap();
        assert_eq!(loaded.ownership_nonce, "nonce-a");
        fs::remove_dir_all(root).unwrap();
    }
}
