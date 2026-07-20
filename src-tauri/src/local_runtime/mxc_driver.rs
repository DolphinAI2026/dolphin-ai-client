use thiserror::Error;

const MXC_SDK_VERSION: &str = "0.7.0";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProbeResult {
    pub platform: String,
    pub mxc_version: String,
    pub backend: String,
    pub supported: bool,
    pub reason: Option<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LocalRuntimeErrorCode {
    UnsupportedPlatform,
    ProbeFailed,
}

#[derive(Debug, Error)]
#[error("{message}")]
pub struct LocalRuntimeError {
    pub code: LocalRuntimeErrorCode,
    pub message: String,
}

pub fn probe() -> Result<ProbeResult, LocalRuntimeError> {
    let platform = std::env::consts::OS;
    if platform != "linux" {
        return Err(LocalRuntimeError {
            code: LocalRuntimeErrorCode::UnsupportedPlatform,
            message: format!(
                "MXC local runtime requires Linux Bubblewrap, but the host platform is {platform}"
            ),
        });
    }

    let support = mxc_sdk::platform_support();
    if !support.is_supported {
        return Err(LocalRuntimeError {
            code: LocalRuntimeErrorCode::ProbeFailed,
            message: support.reason.unwrap_or_else(|| {
                "MXC reported that the Linux Bubblewrap backend is unavailable".to_string()
            }),
        });
    }

    if !support
        .available_methods
        .iter()
        .any(|method| method == "bubblewrap")
    {
        return Err(LocalRuntimeError {
            code: LocalRuntimeErrorCode::ProbeFailed,
            message: format!(
                "MXC reported supported methods ({}) but not the required Linux Bubblewrap backend",
                support.available_methods.join(", ")
            ),
        });
    }

    Ok(ProbeResult {
        platform: platform.to_string(),
        mxc_version: MXC_SDK_VERSION.to_string(),
        backend: "bubblewrap".to_string(),
        supported: true,
        reason: None,
    })
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
}
