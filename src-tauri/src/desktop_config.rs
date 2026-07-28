use serde::{Deserialize, Serialize};
#[cfg(unix)]
use std::fs::File;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};
use tauri::Url;

pub const CONTROL_PLANE_DEFAULT_URL: &str = "https://om-demo.dfy.definesys.cn";
pub const APAAS_DEFAULT_URL: &str = "https://apaas-trial.definesys.cn/backend";

const DESKTOP_CONFIG_SCHEMA_VERSION: u32 = 1;

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
}

impl DesktopConfigStore {
    pub fn new(system_data_dir: impl Into<PathBuf>) -> Self {
        Self {
            system_data_dir: system_data_dir.into(),
        }
    }

    pub fn load(&self) -> Result<Option<SavedDesktopConfig>, DesktopConfigError> {
        let bootstrap_path = self.system_data_dir.join("bootstrap.json");
        if !bootstrap_path.try_exists().map_err(|error| {
            DesktopConfigError::invalid(format!("无法检查桌面启动配置: {error}"))
        })? {
            return Ok(None);
        }

        let pointer: BootstrapPointer = read_json(&bootstrap_path)?;
        if pointer.schema_version != DESKTOP_CONFIG_SCHEMA_VERSION {
            return Err(DesktopConfigError::invalid("桌面启动配置版本不受支持"));
        }

        let root_dir = PathBuf::from(&pointer.root_dir);
        if !root_dir.is_absolute() {
            return Err(DesktopConfigError::invalid("桌面根目录必须是绝对路径"));
        }

        let paths = DesktopPaths::from_root(root_dir.clone());
        let mut config: DesktopConfig = read_json(&paths.config_path)?;
        if config.schema_version != DESKTOP_CONFIG_SCHEMA_VERSION {
            return Err(DesktopConfigError::invalid("桌面根配置版本不受支持"));
        }
        if !config.root_dir.is_absolute() || config.root_dir != root_dir {
            return Err(DesktopConfigError::invalid(
                "桌面根配置与启动配置中的根目录不一致",
            ));
        }

        config.login.base_url = normalize_login_url(&config.login.base_url)?;
        Ok(Some(SavedDesktopConfig { config, paths }))
    }

    pub fn save(&self, input: DesktopSetupInput) -> Result<SavedDesktopConfig, DesktopConfigError> {
        let requested_root = PathBuf::from(input.root_dir.trim());
        if requested_root.as_os_str().is_empty() || !requested_root.is_absolute() {
            return Err(DesktopConfigError::invalid("桌面根目录必须是绝对路径"));
        }

        let login = DesktopLoginConfig {
            mode: input.login.mode,
            base_url: normalize_login_url(&input.login.base_url)?,
        };

        fs::create_dir_all(&requested_root)
            .map_err(|error| DesktopConfigError::invalid(format!("无法创建桌面根目录: {error}")))?;
        let root_dir = fs::canonicalize(&requested_root).map_err(|error| {
            DesktopConfigError::invalid(format!("无法规范化桌面根目录: {error}"))
        })?;
        let paths = DesktopPaths::from_root(root_dir.clone());

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

        verify_root_is_writable(&root_dir)?;

        let config = DesktopConfig {
            schema_version: DESKTOP_CONFIG_SCHEMA_VERSION,
            root_dir: root_dir.clone(),
            login,
        };
        atomic_write_json(&paths.config_path, &config)?;

        fs::create_dir_all(&self.system_data_dir).map_err(|error| {
            DesktopConfigError::invalid(format!("无法创建系统应用数据目录: {error}"))
        })?;
        let pointer = BootstrapPointer {
            schema_version: DESKTOP_CONFIG_SCHEMA_VERSION,
            root_dir: root_dir_to_string(&root_dir)?,
        };
        atomic_write_json(&self.system_data_dir.join("bootstrap.json"), &pointer)?;

        Ok(SavedDesktopConfig { config, paths })
    }
}

pub fn default_root_dir(home_dir: &Path) -> PathBuf {
    home_dir.join("DolphinCode")
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
        let paths = DesktopPaths::from_root(PathBuf::from("/tmp/DolphinCode"));
        assert_eq!(
            paths.applications_dir,
            PathBuf::from("/tmp/DolphinCode/applications")
        );
        assert_eq!(paths.data_dir, PathBuf::from("/tmp/DolphinCode/.appdata"));
        assert_eq!(
            paths.runtime_dir,
            PathBuf::from("/tmp/DolphinCode/.appdata/runtime")
        );
        assert_eq!(
            paths.logs_dir,
            PathBuf::from("/tmp/DolphinCode/.appdata/logs")
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
    fn root_config_is_written_before_bootstrap_pointer() {
        let temp = unique_test_dir("save-order");
        let system_data = temp.join("system");
        let root = temp.join("DolphinCode");
        let store = DesktopConfigStore::new(system_data.clone());
        let saved = store
            .save(DesktopSetupInput {
                root_dir: root.to_string_lossy().into_owned(),
                login: DesktopLoginConfig {
                    mode: DesktopLoginMode::ControlPlane,
                    base_url: CONTROL_PLANE_DEFAULT_URL.to_string(),
                },
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
                root_dir: temp.join("DolphinCode").to_string_lossy().into_owned(),
                login: DesktopLoginConfig {
                    mode: DesktopLoginMode::Apaas,
                    base_url: format!("{APAAS_DEFAULT_URL}/"),
                },
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
            json!({ "schema_version": 2, "root_dir": temp.join("DolphinCode") }),
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
            json!({ "schema_version": 1, "root_dir": "relative/DolphinCode" }),
        );

        let error = DesktopConfigStore::new(system_data).load().unwrap_err();
        assert_eq!(error.code, "DESKTOP_SETUP_CONFIG_INVALID");
        fs::remove_dir_all(temp).unwrap();
    }

    #[test]
    fn load_rejects_missing_root_config() {
        let temp = unique_test_dir("missing-root-config");
        let system_data = temp.join("system");
        let root = temp.join("DolphinCode");
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
        let pointer_root = temp.join("DolphinCode");
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
            })
            .unwrap_err();

        assert_eq!(error.code, "DESKTOP_SETUP_CONFIG_INVALID");
        assert!(!temp.join("system/bootstrap.json").exists());
        fs::remove_dir_all(temp).unwrap();
    }
}
