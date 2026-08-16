use serde::{Deserialize, Serialize};
use std::collections::HashMap;
#[cfg(unix)]
use std::fs::File;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Component, Path, PathBuf};
use std::sync::{Arc, Mutex, OnceLock, Weak};
use std::time::{SystemTime, UNIX_EPOCH};
use tauri::Url;

pub const CONTROL_PLANE_DEFAULT_URL: &str = "https://om-demo.dfy.definesys.cn";
pub const APAAS_DEFAULT_URL: &str = "https://apaas-trial.definesys.cn/backend";

const DESKTOP_CONFIG_SCHEMA_VERSION: u32 = 2;

type TransactionLock = Arc<Mutex<()>>;

static TRANSACTION_LOCKS: OnceLock<Mutex<HashMap<String, Weak<Mutex<()>>>>> = OnceLock::new();

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum DesktopLoginMode {
    ControlPlane,
    Apaas,
}

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

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct DesktopLoginConfig {
    pub mode: DesktopLoginMode,
    pub base_url: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct DesktopDiscoveryPlatform {
    #[serde(rename = "type")]
    pub platform_type: String,
    pub name: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct DesktopDiscoveryAuth {
    pub provider: String,
    pub login_url: String,
    #[serde(default)]
    pub api_base_url: Option<String>,
    #[serde(default)]
    pub logout_url: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct DesktopDiscoveryProduct {
    pub enabled: bool,
    #[serde(default)]
    pub base_url: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct DesktopDiscoveryProducts {
    pub builder: DesktopDiscoveryProduct,
    pub code: DesktopDiscoveryProduct,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, Default)]
pub struct DesktopRemoteCapabilities {
    #[serde(default)]
    pub models: bool,
    #[serde(default)]
    pub mcp: bool,
    #[serde(default)]
    pub skills: bool,
    #[serde(default)]
    pub knowledge_bases: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct DesktopLocalAiConfig {
    #[serde(default = "default_local_ai_enabled")]
    pub enabled: bool,
    #[serde(default)]
    pub allowed_kinds: Vec<String>,
    #[serde(default = "default_bridge_protocol_version")]
    pub bridge_protocol_version: u32,
}

fn default_local_ai_enabled() -> bool {
    true
}
fn default_bridge_protocol_version() -> u32 {
    1
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct DesktopDiscoveryDocument {
    pub schema_version: u32,
    pub deployment_id: String,
    pub platform: DesktopDiscoveryPlatform,
    pub auth: DesktopDiscoveryAuth,
    pub products: DesktopDiscoveryProducts,
    #[serde(default)]
    pub remote_capabilities: DesktopRemoteCapabilities,
    pub local_ai: DesktopLocalAiConfig,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct DesktopConfig {
    pub schema_version: u32,
    pub root_dir: PathBuf,
    pub login: DesktopLoginConfig,
    #[serde(default = "default_workspace_entry_scope")]
    pub workspace_entry_scope: WorkspaceEntryScope,
    #[serde(default)]
    pub discovery_url: String,
    #[serde(default)]
    pub discovery: Option<DesktopDiscoveryDocument>,
    #[serde(default = "default_local_ai_enabled")]
    pub local_ai_enabled: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DesktopSetupInput {
    pub root_dir: String,
    pub login: DesktopLoginConfig,
    pub workspace_entry_scope: WorkspaceEntryScope,
    #[serde(default)]
    pub discovery_url: Option<String>,
    #[serde(default)]
    pub discovery: Option<DesktopDiscoveryDocument>,
    #[serde(default = "default_local_ai_enabled")]
    pub local_ai_enabled: bool,
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

impl DesktopPaths {
    pub fn from_root(root_dir: PathBuf) -> Self {
        let applications_dir = root_dir.join("applications");
        let data_dir = root_dir.join(".appdata");
        let runtime_dir = data_dir.join("runtime");
        let sessions_dir = data_dir.join("sessions");
        let cache_dir = data_dir.join("cache");
        let logs_dir = data_dir.join("logs");
        let config_path = data_dir.join("desktop-config.json");

        Self {
            root_dir,
            applications_dir,
            data_dir,
            runtime_dir,
            sessions_dir,
            cache_dir,
            logs_dir,
            config_path,
        }
    }
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

#[derive(Debug, Clone)]
pub struct DesktopConfigStore {
    system_data_dir: PathBuf,
    transaction_lock: TransactionLock,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum BootstrapSaveMode {
    WritePointer,
    PreservePointer,
}

impl DesktopConfigStore {
    pub fn new(system_data_dir: impl Into<PathBuf>) -> Self {
        let system_data_dir = system_data_dir.into();
        Self {
            transaction_lock: shared_transaction_lock(&system_data_dir),
            system_data_dir,
        }
    }

    pub fn load(&self) -> Result<Option<SavedDesktopConfig>, DesktopConfigError> {
        let _transaction_guard = self
            .transaction_lock
            .lock()
            .map_err(|_| DesktopConfigError::invalid("桌面配置事务锁不可用"))?;
        let system_data_identity = resolve_path_for_comparison(&self.system_data_dir)?;
        let bootstrap_path = self.system_data_dir.join("bootstrap.json");
        if !bootstrap_path.try_exists().map_err(|error| {
            DesktopConfigError::invalid(format!("无法检查桌面启动配置: {error}"))
        })? {
            return Ok(None);
        }

        let pointer: BootstrapPointer = read_json(&bootstrap_path)?;
        if !matches!(pointer.schema_version, 1 | DESKTOP_CONFIG_SCHEMA_VERSION) {
            return Err(DesktopConfigError::invalid("桌面启动配置版本不受支持"));
        }

        let root_dir = PathBuf::from(&pointer.root_dir);
        if !root_dir.is_absolute() {
            return Err(DesktopConfigError::invalid("桌面根目录必须是绝对路径"));
        }
        let root_identity = fs::canonicalize(&root_dir).map_err(|error| {
            DesktopConfigError::invalid(format!("无法规范化桌面根目录: {error}"))
        })?;
        if !paths_equal(&root_identity, &root_dir) {
            return Err(DesktopConfigError::invalid("桌面根目录不是规范化路径"));
        }
        ensure_storage_roots_are_disjoint(&root_identity, &system_data_identity)?;

        let paths = DesktopPaths::from_root(root_identity.clone());
        reject_existing_links_in_derived_paths(&paths)?;
        let mut config: DesktopConfig = read_json(&paths.config_path)?;
        if !matches!(config.schema_version, 1 | DESKTOP_CONFIG_SCHEMA_VERSION) {
            return Err(DesktopConfigError::invalid("桌面根配置版本不受支持"));
        }
        if !config.root_dir.is_absolute() || !paths_equal(&config.root_dir, &root_identity) {
            return Err(DesktopConfigError::invalid(
                "桌面根配置与启动配置中的根目录不一致",
            ));
        }

        config.login.base_url = normalize_login_url(&config.login.base_url)?;
        if config.discovery_url.trim().is_empty() {
            config.discovery_url = config.login.base_url.clone();
        }
        config.discovery_url = normalize_login_url(&config.discovery_url)?;
        config.schema_version = DESKTOP_CONFIG_SCHEMA_VERSION;
        Ok(Some(SavedDesktopConfig { config, paths }))
    }

    pub fn save(&self, input: DesktopSetupInput) -> Result<SavedDesktopConfig, DesktopConfigError> {
        self.save_with_mode(input, BootstrapSaveMode::WritePointer)
    }

    pub fn save_current_root(
        &self,
        input: DesktopSetupInput,
    ) -> Result<SavedDesktopConfig, DesktopConfigError> {
        self.save_with_mode(input, BootstrapSaveMode::PreservePointer)
    }

    fn save_with_mode(
        &self,
        input: DesktopSetupInput,
        bootstrap_mode: BootstrapSaveMode,
    ) -> Result<SavedDesktopConfig, DesktopConfigError> {
        let _transaction_guard = self
            .transaction_lock
            .lock()
            .map_err(|_| DesktopConfigError::invalid("桌面配置事务锁不可用"))?;
        let requested_root = PathBuf::from(input.root_dir.trim());
        if requested_root.as_os_str().is_empty() || !requested_root.is_absolute() {
            return Err(DesktopConfigError::invalid("桌面根目录必须是绝对路径"));
        }

        let login = DesktopLoginConfig {
            mode: input.login.mode,
            base_url: normalize_login_url(&input.login.base_url)?,
        };

        let requested_root_identity = resolve_path_for_comparison(&requested_root)?;
        let system_data_identity = resolve_path_for_comparison(&self.system_data_dir)?;
        ensure_storage_roots_are_disjoint(&requested_root_identity, &system_data_identity)?;

        fs::create_dir_all(&requested_root)
            .map_err(|error| DesktopConfigError::invalid(format!("无法创建桌面根目录: {error}")))?;
        let root_dir = fs::canonicalize(&requested_root).map_err(|error| {
            DesktopConfigError::invalid(format!("无法规范化桌面根目录: {error}"))
        })?;
        let system_data_identity = resolve_path_for_comparison(&self.system_data_dir)?;
        ensure_storage_roots_are_disjoint(&root_dir, &system_data_identity)?;
        if bootstrap_mode == BootstrapSaveMode::PreservePointer {
            self.ensure_bootstrap_points_to(&root_dir)?;
        }
        let paths = DesktopPaths::from_root(root_dir.clone());
        reject_existing_links_in_derived_paths(&paths)?;

        for path in [
            &paths.applications_dir,
            &paths.runtime_dir,
            &paths.sessions_dir,
            &paths.cache_dir,
            &paths.logs_dir,
        ] {
            fs::create_dir_all(path).map_err(|error| {
                DesktopConfigError::invalid(format!("无法创建桌面目录 {}: {error}", path.display()))
            })?;
        }
        validate_resolved_derived_directories(&paths, &system_data_identity)?;

        verify_root_is_writable(&root_dir)?;

        let discovery_url =
            normalize_login_url(input.discovery_url.as_deref().unwrap_or(&login.base_url))?;
        let config = DesktopConfig {
            schema_version: DESKTOP_CONFIG_SCHEMA_VERSION,
            root_dir: root_dir.clone(),
            login,
            workspace_entry_scope: input.workspace_entry_scope,
            discovery_url,
            discovery: input.discovery,
            local_ai_enabled: input.local_ai_enabled,
        };
        atomic_write_json(&paths.config_path, &config)?;

        if bootstrap_mode == BootstrapSaveMode::WritePointer {
            fs::create_dir_all(&self.system_data_dir).map_err(|error| {
                DesktopConfigError::invalid(format!("无法创建系统应用数据目录: {error}"))
            })?;
            let pointer = BootstrapPointer {
                schema_version: DESKTOP_CONFIG_SCHEMA_VERSION,
                root_dir: root_dir_to_string(&root_dir)?,
            };
            atomic_write_json(&self.system_data_dir.join("bootstrap.json"), &pointer)?;
        }

        Ok(SavedDesktopConfig { config, paths })
    }

    fn ensure_bootstrap_points_to(&self, root_dir: &Path) -> Result<(), DesktopConfigError> {
        let bootstrap_path = self.system_data_dir.join("bootstrap.json");
        let pointer: BootstrapPointer = read_json(&bootstrap_path)?;
        if !matches!(pointer.schema_version, 1 | DESKTOP_CONFIG_SCHEMA_VERSION) {
            return Err(DesktopConfigError::invalid("桌面启动配置版本不受支持"));
        }

        let pointer_root = PathBuf::from(&pointer.root_dir);
        if !pointer_root.is_absolute() {
            return Err(DesktopConfigError::invalid("桌面根目录必须是绝对路径"));
        }
        let pointer_root_identity = fs::canonicalize(&pointer_root).map_err(|error| {
            DesktopConfigError::invalid(format!("无法规范化桌面根目录: {error}"))
        })?;
        if !paths_equal(&pointer_root_identity, &pointer_root)
            || !paths_equal(&pointer_root_identity, root_dir)
        {
            return Err(DesktopConfigError::invalid(
                "桌面根配置与启动配置中的根目录不一致",
            ));
        }
        Ok(())
    }
}

fn shared_transaction_lock(system_data_dir: &Path) -> TransactionLock {
    let key = transaction_lock_key(system_data_dir);
    let registry = TRANSACTION_LOCKS.get_or_init(|| Mutex::new(HashMap::new()));
    let mut registry = registry
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    registry.retain(|_, lock| lock.strong_count() > 0);
    if let Some(lock) = registry.get(&key).and_then(Weak::upgrade) {
        return lock;
    }

    let lock = Arc::new(Mutex::new(()));
    registry.insert(key, Arc::downgrade(&lock));
    lock
}

fn transaction_lock_key(system_data_dir: &Path) -> String {
    let resolved = resolve_path_for_comparison(system_data_dir)
        .or_else(|_| normalize_absolute_path(system_data_dir))
        .unwrap_or_else(|_| system_data_dir.to_path_buf());
    let key = resolved.as_os_str().to_string_lossy().into_owned();
    #[cfg(windows)]
    {
        key.to_ascii_lowercase()
    }
    #[cfg(not(windows))]
    {
        key
    }
}

pub fn default_root_dir(home_dir: &Path) -> PathBuf {
    home_dir.join("DolphinAI")
}

pub fn normalize_login_url(raw: &str) -> Result<String, DesktopConfigError> {
    let mut url =
        Url::parse(raw.trim()).map_err(|_| DesktopConfigError::invalid("服务地址不是有效 URL"))?;
    if !matches!(url.scheme(), "http" | "https")
        || url.host_str().is_none()
        || !url.username().is_empty()
        || url.password().is_some()
        || url.fragment().is_some()
    {
        return Err(DesktopConfigError::invalid(
            "服务地址必须是无凭据、无 fragment 的 HTTP(S) 绝对 URL",
        ));
    }
    url.set_fragment(None);
    Ok(url.as_str().trim_end_matches('/').to_string())
}

fn read_json<T: serde::de::DeserializeOwned>(path: &Path) -> Result<T, DesktopConfigError> {
    let bytes = fs::read(path).map_err(|error| DesktopConfigError::invalid(error.to_string()))?;
    serde_json::from_slice(&bytes).map_err(|error| DesktopConfigError::invalid(error.to_string()))
}

fn root_dir_to_string(root_dir: &Path) -> Result<String, DesktopConfigError> {
    root_dir
        .to_str()
        .map(str::to_owned)
        .ok_or_else(|| DesktopConfigError::invalid("桌面根目录必须是有效 UTF-8 路径"))
}

fn resolve_path_for_comparison(path: &Path) -> Result<PathBuf, DesktopConfigError> {
    let normalized = normalize_absolute_path(path)?;
    let mut existing = normalized.clone();
    let mut missing = Vec::new();

    loop {
        match fs::symlink_metadata(&existing) {
            Ok(_) => {
                let mut resolved = fs::canonicalize(&existing).map_err(|error| {
                    DesktopConfigError::invalid(format!(
                        "无法解析路径 {}: {error}",
                        existing.display()
                    ))
                })?;
                for component in missing.iter().rev() {
                    resolved.push(component);
                }
                return normalize_absolute_path(&resolved);
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                let component = existing.file_name().ok_or_else(|| {
                    DesktopConfigError::invalid(format!(
                        "无法找到路径 {} 的现存祖先",
                        normalized.display()
                    ))
                })?;
                missing.push(component.to_os_string());
                if !existing.pop() {
                    return Err(DesktopConfigError::invalid(format!(
                        "无法解析路径 {}",
                        normalized.display()
                    )));
                }
            }
            Err(error) => {
                return Err(DesktopConfigError::invalid(format!(
                    "无法检查路径 {}: {error}",
                    existing.display()
                )))
            }
        }
    }
}

fn normalize_absolute_path(path: &Path) -> Result<PathBuf, DesktopConfigError> {
    if !path.is_absolute() {
        return Err(DesktopConfigError::invalid("桌面路径必须是绝对路径"));
    }

    let mut normalized = PathBuf::new();
    for component in path.components() {
        match component {
            Component::Prefix(_) | Component::RootDir | Component::Normal(_) => {
                normalized.push(component.as_os_str());
            }
            Component::CurDir => {}
            Component::ParentDir => {
                if !normalized.pop() {
                    return Err(DesktopConfigError::invalid(
                        "桌面路径不能越过文件系统根目录",
                    ));
                }
            }
        }
    }
    Ok(normalized)
}

fn ensure_storage_roots_are_disjoint(
    root_dir: &Path,
    system_data_dir: &Path,
) -> Result<(), DesktopConfigError> {
    if path_starts_with(root_dir, system_data_dir) || path_starts_with(system_data_dir, root_dir) {
        return Err(DesktopConfigError::invalid(
            "桌面根目录与系统应用数据目录不能重叠",
        ));
    }
    Ok(())
}

fn reject_existing_links_in_derived_paths(paths: &DesktopPaths) -> Result<(), DesktopConfigError> {
    for path in [
        &paths.applications_dir,
        &paths.data_dir,
        &paths.runtime_dir,
        &paths.sessions_dir,
        &paths.cache_dir,
        &paths.logs_dir,
        &paths.config_path,
    ] {
        reject_existing_links_below_root(&paths.root_dir, path)?;
    }
    Ok(())
}

fn reject_existing_links_below_root(
    root_dir: &Path,
    target: &Path,
) -> Result<(), DesktopConfigError> {
    let relative = target.strip_prefix(root_dir).map_err(|_| {
        DesktopConfigError::invalid(format!("桌面派生路径不在根目录内: {}", target.display()))
    })?;
    let mut current = root_dir.to_path_buf();
    for component in relative.components() {
        current.push(component.as_os_str());
        match fs::symlink_metadata(&current) {
            Ok(_) => {
                if path_is_link_or_reparse_point(&current).map_err(|error| {
                    DesktopConfigError::invalid(format!(
                        "无法检查桌面派生路径 {}: {error}",
                        current.display()
                    ))
                })? {
                    return Err(DesktopConfigError::invalid(format!(
                        "桌面派生路径不能包含链接或 reparse point: {}",
                        current.display()
                    )));
                }
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => break,
            Err(error) => {
                return Err(DesktopConfigError::invalid(format!(
                    "无法检查桌面派生路径 {}: {error}",
                    current.display()
                )))
            }
        }
    }
    Ok(())
}

fn validate_resolved_derived_directories(
    paths: &DesktopPaths,
    system_data_dir: &Path,
) -> Result<(), DesktopConfigError> {
    for path in [
        &paths.applications_dir,
        &paths.data_dir,
        &paths.runtime_dir,
        &paths.sessions_dir,
        &paths.cache_dir,
        &paths.logs_dir,
    ] {
        let resolved = fs::canonicalize(path).map_err(|error| {
            DesktopConfigError::invalid(format!(
                "无法规范化桌面派生目录 {}: {error}",
                path.display()
            ))
        })?;
        if paths_equal(&resolved, &paths.root_dir)
            || !path_starts_with(&resolved, &paths.root_dir)
            || path_starts_with(&resolved, system_data_dir)
            || path_starts_with(system_data_dir, &resolved)
        {
            return Err(DesktopConfigError::invalid(format!(
                "桌面派生目录越过允许的数据边界: {}",
                path.display()
            )));
        }
    }
    Ok(())
}

#[cfg(not(windows))]
fn paths_equal(left: &Path, right: &Path) -> bool {
    left == right
}

#[cfg(windows)]
fn paths_equal(left: &Path, right: &Path) -> bool {
    let mut left = left.components();
    let mut right = right.components();
    loop {
        match (left.next(), right.next()) {
            (Some(left), Some(right))
                if left
                    .as_os_str()
                    .to_string_lossy()
                    .eq_ignore_ascii_case(&right.as_os_str().to_string_lossy()) => {}
            (None, None) => return true,
            _ => return false,
        }
    }
}

#[cfg(not(windows))]
fn path_starts_with(path: &Path, base: &Path) -> bool {
    path.starts_with(base)
}

#[cfg(windows)]
fn path_starts_with(path: &Path, base: &Path) -> bool {
    let mut path = path.components();
    for base_component in base.components() {
        let Some(path_component) = path.next() else {
            return false;
        };
        if !path_component
            .as_os_str()
            .to_string_lossy()
            .eq_ignore_ascii_case(&base_component.as_os_str().to_string_lossy())
        {
            return false;
        }
    }
    true
}

#[cfg(unix)]
fn path_is_link_or_reparse_point(path: &Path) -> std::io::Result<bool> {
    Ok(fs::symlink_metadata(path)?.file_type().is_symlink())
}

#[cfg(windows)]
fn path_is_link_or_reparse_point(path: &Path) -> std::io::Result<bool> {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Storage::FileSystem::{
        GetFileAttributesW, FILE_ATTRIBUTE_REPARSE_POINT, INVALID_FILE_ATTRIBUTES,
    };

    let path: Vec<u16> = path.as_os_str().encode_wide().chain(Some(0)).collect();
    let attributes = unsafe { GetFileAttributesW(path.as_ptr()) };
    if attributes == INVALID_FILE_ATTRIBUTES {
        Err(std::io::Error::last_os_error())
    } else {
        Ok(attributes & FILE_ATTRIBUTE_REPARSE_POINT != 0)
    }
}

#[cfg(not(any(unix, windows)))]
fn path_is_link_or_reparse_point(path: &Path) -> std::io::Result<bool> {
    Ok(fs::symlink_metadata(path)?.file_type().is_symlink())
}

fn verify_root_is_writable(root_dir: &Path) -> Result<(), DesktopConfigError> {
    let probe_path = temporary_path(root_dir, "desktop-write-probe");
    let result = (|| {
        let file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&probe_path)?;
        file.sync_all()?;
        drop(file);
        fs::remove_file(&probe_path)
    })();

    if result.is_err() {
        let _ = fs::remove_file(&probe_path);
    }
    result.map_err(|error| DesktopConfigError::invalid(format!("桌面根目录不可写: {error}")))
}

fn atomic_write_json<T: Serialize>(path: &Path, value: &T) -> Result<(), DesktopConfigError> {
    let parent = path
        .parent()
        .ok_or_else(|| DesktopConfigError::invalid("桌面配置路径缺少父目录"))?;
    let payload = serde_json::to_vec_pretty(value)
        .map_err(|error| DesktopConfigError::invalid(format!("无法编码桌面配置: {error}")))?;
    let temporary = temporary_path(parent, path.file_name().unwrap_or_default());

    let write_result = (|| {
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)?;
        file.write_all(&payload)?;
        file.write_all(b"\n")?;
        file.sync_all()?;
        drop(file);
        replace_file(&temporary, path)?;
        sync_directory(parent)
    })();

    if write_result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    write_result.map_err(|error| {
        DesktopConfigError::invalid(format!("无法原子写入桌面配置 {}: {error}", path.display()))
    })
}

fn temporary_path(parent: &Path, label: impl AsRef<std::ffi::OsStr>) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_nanos())
        .unwrap_or_default();
    let label = label.as_ref().to_string_lossy();
    parent.join(format!(".{label}.{}-{nonce}.tmp", std::process::id()))
}

#[cfg(not(windows))]
fn replace_file(source: &Path, target: &Path) -> std::io::Result<()> {
    fs::rename(source, target)
}

#[cfg(windows)]
fn replace_file(source: &Path, target: &Path) -> std::io::Result<()> {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Storage::FileSystem::{
        MoveFileExW, MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH,
    };

    let source: Vec<u16> = source.as_os_str().encode_wide().chain(Some(0)).collect();
    let target: Vec<u16> = target.as_os_str().encode_wide().chain(Some(0)).collect();
    let result = unsafe {
        MoveFileExW(
            source.as_ptr(),
            target.as_ptr(),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
        )
    };
    if result == 0 {
        Err(std::io::Error::last_os_error())
    } else {
        Ok(())
    }
}

#[cfg(unix)]
fn sync_directory(path: &Path) -> std::io::Result<()> {
    File::open(path)?.sync_all()
}

#[cfg(not(unix))]
fn sync_directory(_path: &Path) -> std::io::Result<()> {
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::fs;
    use std::path::PathBuf;
    use std::sync::{mpsc, Barrier};
    use std::thread;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn unique_test_dir(label: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "dolphin-desktop-{label}-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos(),
        ))
    }

    fn write_json_fixture(path: &std::path::Path, value: serde_json::Value) {
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, serde_json::to_vec(&value).unwrap()).unwrap();
    }

    #[test]
    fn paths_are_derived_from_one_user_root() {
        let paths = DesktopPaths::from_root(PathBuf::from("/tmp/DolphinAI"));
        assert_eq!(
            paths.applications_dir,
            PathBuf::from("/tmp/DolphinAI/applications")
        );
        assert_eq!(paths.data_dir, PathBuf::from("/tmp/DolphinAI/.appdata"));
        assert_eq!(
            paths.runtime_dir,
            PathBuf::from("/tmp/DolphinAI/.appdata/runtime")
        );
        assert_eq!(
            paths.logs_dir,
            PathBuf::from("/tmp/DolphinAI/.appdata/logs")
        );
    }

    #[test]
    fn default_root_dir_uses_dolphin_ai_home_directory() {
        assert_eq!(
            default_root_dir(Path::new("/home/tester")),
            PathBuf::from("/home/tester/DolphinAI")
        );
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
    fn legacy_config_without_workspace_scope_defaults_to_both() {
        let raw = r#"{
            "schema_version": 1,
            "root_dir": "/tmp/DolphinAI",
            "login": {"mode": "control_plane", "base_url": "https://example.com"}
        }"#;
        let config: DesktopConfig = serde_json::from_str(raw).unwrap();
        assert_eq!(config.workspace_entry_scope, WorkspaceEntryScope::Both);
    }

    #[test]
    fn setup_persists_explicit_workspace_scope() {
        let temp = unique_test_dir("workspace-scope");
        let store = DesktopConfigStore::new(temp.join("system"));
        store
            .save(DesktopSetupInput {
                root_dir: temp.join("DolphinAI").to_string_lossy().into_owned(),
                login: DesktopLoginConfig {
                    mode: DesktopLoginMode::ControlPlane,
                    base_url: CONTROL_PLANE_DEFAULT_URL.to_string(),
                },
                workspace_entry_scope: WorkspaceEntryScope::AiPlatform,
                discovery_url: None,
                discovery: None,
                local_ai_enabled: true,
            })
            .unwrap();
        let loaded = store.load().unwrap().unwrap();
        assert_eq!(
            loaded.config.workspace_entry_scope,
            WorkspaceEntryScope::AiPlatform
        );
        fs::remove_dir_all(temp).unwrap();
    }

    #[test]
    fn root_config_is_written_before_bootstrap_pointer() {
        let temp = unique_test_dir("save-order");
        let system_data = temp.join("system");
        let root = temp.join("DolphinAI");
        let store = DesktopConfigStore::new(system_data.clone());
        let saved = store
            .save(DesktopSetupInput {
                root_dir: root.to_string_lossy().into_owned(),
                login: DesktopLoginConfig {
                    mode: DesktopLoginMode::ControlPlane,
                    base_url: CONTROL_PLANE_DEFAULT_URL.to_string(),
                },
                workspace_entry_scope: WorkspaceEntryScope::Both,
                discovery_url: None,
                discovery: None,
                local_ai_enabled: true,
            })
            .unwrap();

        assert!(saved.paths.config_path.is_file());
        let pointer: BootstrapPointer = read_json(&system_data.join("bootstrap.json")).unwrap();
        assert_eq!(PathBuf::from(pointer.root_dir), saved.config.root_dir);
        fs::remove_dir_all(temp).unwrap();
    }

    #[test]
    fn saved_configuration_round_trips() {
        let temp = unique_test_dir("round-trip");
        let system_data = temp.join("system");
        let store = DesktopConfigStore::new(system_data);
        let saved = store
            .save(DesktopSetupInput {
                root_dir: temp.join("DolphinAI").to_string_lossy().into_owned(),
                login: DesktopLoginConfig {
                    mode: DesktopLoginMode::Apaas,
                    base_url: format!("{APAAS_DEFAULT_URL}/"),
                },
                workspace_entry_scope: WorkspaceEntryScope::Both,
                discovery_url: None,
                discovery: None,
                local_ai_enabled: true,
            })
            .unwrap();

        let loaded = store.load().unwrap().unwrap();
        assert_eq!(loaded.config, saved.config);
        assert_eq!(loaded.paths.root_dir, saved.paths.root_dir);
        assert_eq!(loaded.config.login.base_url, APAAS_DEFAULT_URL);
        fs::remove_dir_all(temp).unwrap();
    }

    #[test]
    fn load_returns_none_when_bootstrap_pointer_is_missing() {
        let temp = unique_test_dir("missing-pointer");
        let store = DesktopConfigStore::new(temp.clone());
        assert!(store.load().unwrap().is_none());
        assert!(!temp.exists());
    }

    #[test]
    fn load_rejects_invalid_pointer_schema() {
        let temp = unique_test_dir("pointer-schema");
        let system_data = temp.join("system");
        write_json_fixture(
            &system_data.join("bootstrap.json"),
            json!({ "schema_version": 2, "root_dir": temp.join("DolphinAI") }),
        );

        let error = DesktopConfigStore::new(system_data).load().unwrap_err();
        assert_eq!(error.code, "DESKTOP_SETUP_CONFIG_INVALID");
        fs::remove_dir_all(temp).unwrap();
    }

    #[test]
    fn load_rejects_relative_pointer_root() {
        let temp = unique_test_dir("relative-pointer");
        let system_data = temp.join("system");
        write_json_fixture(
            &system_data.join("bootstrap.json"),
            json!({ "schema_version": 1, "root_dir": "relative/DolphinAI" }),
        );

        let error = DesktopConfigStore::new(system_data).load().unwrap_err();
        assert_eq!(error.code, "DESKTOP_SETUP_CONFIG_INVALID");
        fs::remove_dir_all(temp).unwrap();
    }

    #[test]
    fn load_rejects_missing_root_config() {
        let temp = unique_test_dir("missing-root-config");
        let system_data = temp.join("system");
        let root = temp.join("DolphinAI");
        write_json_fixture(
            &system_data.join("bootstrap.json"),
            json!({ "schema_version": 1, "root_dir": root }),
        );

        let error = DesktopConfigStore::new(system_data).load().unwrap_err();
        assert_eq!(error.code, "DESKTOP_SETUP_CONFIG_INVALID");
        fs::remove_dir_all(temp).unwrap();
    }

    #[test]
    fn load_rejects_root_mismatch_without_deleting_files() {
        let temp = unique_test_dir("root-mismatch");
        let system_data = temp.join("system");
        let pointer_root = temp.join("DolphinAI");
        let other_root = temp.join("OtherRoot");
        let root_config = pointer_root.join(".appdata/desktop-config.json");
        let bootstrap = system_data.join("bootstrap.json");
        write_json_fixture(
            &bootstrap,
            json!({ "schema_version": 1, "root_dir": pointer_root }),
        );
        write_json_fixture(
            &root_config,
            json!({
                "schema_version": 1,
                "root_dir": other_root,
                "login": {
                    "mode": "control_plane",
                    "base_url": CONTROL_PLANE_DEFAULT_URL,
                },
            }),
        );

        let error = DesktopConfigStore::new(system_data).load().unwrap_err();
        assert_eq!(error.code, "DESKTOP_SETUP_CONFIG_INVALID");
        assert!(bootstrap.is_file());
        assert!(root_config.is_file());
        fs::remove_dir_all(temp).unwrap();
    }

    #[test]
    fn save_returns_stable_error_for_an_unwritable_root() {
        let temp = unique_test_dir("unwritable-root");
        fs::create_dir_all(&temp).unwrap();
        let blocked_root = temp.join("not-a-directory");
        fs::write(&blocked_root, b"file blocks directory creation").unwrap();

        let error = DesktopConfigStore::new(temp.join("system"))
            .save(DesktopSetupInput {
                root_dir: blocked_root.to_string_lossy().into_owned(),
                login: DesktopLoginConfig {
                    mode: DesktopLoginMode::ControlPlane,
                    base_url: CONTROL_PLANE_DEFAULT_URL.to_string(),
                },
                workspace_entry_scope: WorkspaceEntryScope::Both,
                discovery_url: None,
                discovery: None,
                local_ai_enabled: true,
            })
            .unwrap_err();

        assert_eq!(error.code, "DESKTOP_SETUP_CONFIG_INVALID");
        assert!(!temp.join("system/bootstrap.json").exists());
        fs::remove_dir_all(temp).unwrap();
    }

    #[test]
    fn save_rejects_root_and_system_data_overlap_before_creating_derived_directories() {
        for (label, root_from_temp, system_from_temp) in [
            ("same", "system", "system"),
            ("root-inside-system", "system/DolphinAI", "system"),
            (
                "system-inside-root",
                "DolphinAI",
                "DolphinAI/.appdata/system",
            ),
        ] {
            let temp = unique_test_dir(label);
            let root = temp.join(root_from_temp);
            let system_data = temp.join(system_from_temp);
            let result = DesktopConfigStore::new(system_data.clone()).save(DesktopSetupInput {
                root_dir: root.to_string_lossy().into_owned(),
                login: DesktopLoginConfig {
                    mode: DesktopLoginMode::ControlPlane,
                    base_url: CONTROL_PLANE_DEFAULT_URL.to_string(),
                },
                workspace_entry_scope: WorkspaceEntryScope::Both,
                discovery_url: None,
                discovery: None,
                local_ai_enabled: true,
            });
            let applications_created = root.join("applications").exists();
            let data_created = root.join(".appdata").exists();
            let bootstrap_created = system_data.join("bootstrap.json").exists();
            let _ = fs::remove_dir_all(&temp);

            let error = result.expect_err(label);
            assert_eq!(error.code, "DESKTOP_SETUP_CONFIG_INVALID", "{label}");
            assert!(!applications_created, "{label}");
            assert!(!data_created, "{label}");
            assert!(!bootstrap_created, "{label}");
        }
    }

    #[cfg(unix)]
    #[test]
    fn save_rejects_existing_appdata_symlink_before_following_it() {
        let temp = unique_test_dir("appdata-symlink");
        let root = temp.join("DolphinAI");
        let external = temp.join("external-data");
        let system_data = temp.join("system");
        fs::create_dir_all(&root).unwrap();
        fs::create_dir_all(&external).unwrap();
        std::os::unix::fs::symlink(&external, root.join(".appdata")).unwrap();

        let result = DesktopConfigStore::new(system_data.clone()).save(DesktopSetupInput {
            root_dir: root.to_string_lossy().into_owned(),
            login: DesktopLoginConfig {
                mode: DesktopLoginMode::ControlPlane,
                base_url: CONTROL_PLANE_DEFAULT_URL.to_string(),
            },
            workspace_entry_scope: WorkspaceEntryScope::Both,
            discovery_url: None,
            discovery: None,
            local_ai_enabled: true,
        });
        let external_runtime_created = external.join("runtime").exists();
        let bootstrap_created = system_data.join("bootstrap.json").exists();
        let _ = fs::remove_dir_all(&temp);

        let error = result.expect_err("an existing .appdata symlink must be rejected");
        assert_eq!(error.code, "DESKTOP_SETUP_CONFIG_INVALID");
        assert!(!external_runtime_created);
        assert!(!bootstrap_created);
    }

    #[test]
    fn concurrent_saves_finish_with_the_last_successful_configuration_loadable() {
        let temp = unique_test_dir("concurrent-save");
        let system_data = temp.join("system");
        let root = temp.join("DolphinAI");
        let store = DesktopConfigStore::new(system_data.clone());
        let independent_store = DesktopConfigStore::new(system_data);
        let mut mismatch = None;

        for round in 0..64 {
            let barrier = Arc::new(Barrier::new(3));
            let (sender, receiver) = mpsc::channel();
            let mut handles = Vec::new();

            for ((writer, mode), store) in [
                ("control", DesktopLoginMode::ControlPlane),
                ("apaas", DesktopLoginMode::Apaas),
            ]
            .into_iter()
            .zip([store.clone(), independent_store.clone()])
            {
                let root = root.clone();
                let barrier = barrier.clone();
                let sender = sender.clone();
                handles.push(thread::spawn(move || {
                    barrier.wait();
                    let saved = store
                        .save(DesktopSetupInput {
                            root_dir: root.to_string_lossy().into_owned(),
                            login: DesktopLoginConfig {
                                mode,
                                base_url: format!("https://example.com/{writer}/{round}"),
                            },
                            workspace_entry_scope: WorkspaceEntryScope::Both,
                            discovery_url: None,
                            discovery: None,
                            local_ai_enabled: true,
                        })
                        .unwrap();
                    sender.send(saved.config).unwrap();
                }));
            }

            barrier.wait();
            drop(sender);
            let _first_completed = receiver.recv().unwrap();
            let last_completed = receiver.recv().unwrap();
            for handle in handles {
                handle.join().unwrap();
            }

            let loaded = store.load().unwrap().unwrap();
            if loaded.config != last_completed {
                mismatch = Some((round, last_completed, loaded.config));
                break;
            }
        }

        let _ = fs::remove_dir_all(&temp);
        assert!(
            mismatch.is_none(),
            "last successful save was not durable: {mismatch:?}"
        );
    }
}
