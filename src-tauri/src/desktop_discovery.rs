use crate::desktop_config::{
    normalize_login_url, DesktopDiscoveryDocument, DesktopLoginConfig, DesktopLoginMode,
};
use serde::Serialize;
use std::time::Duration;

#[derive(Debug, Clone, Serialize, thiserror::Error)]
#[error("{message}")]
pub struct DesktopDiscoveryError {
    pub code: String,
    pub message: String,
}

impl DesktopDiscoveryError {
    fn invalid(message: impl Into<String>) -> Self {
        Self {
            code: "DESKTOP_DISCOVERY_INVALID".into(),
            message: message.into(),
        }
    }

    fn unavailable(message: impl Into<String>) -> Self {
        Self {
            code: "DESKTOP_DISCOVERY_UNAVAILABLE".into(),
            message: message.into(),
        }
    }
}

pub fn discover(raw_url: &str) -> Result<DesktopDiscoveryDocument, DesktopDiscoveryError> {
    let base_url = normalize_login_url(raw_url)
        .map_err(|error| DesktopDiscoveryError::invalid(error.message))?;
    let mut last_status = None;
    for endpoint in discovery_endpoints(&base_url) {
        let response = match ureq::get(&endpoint)
            .set("Accept", "application/json")
            .timeout(Duration::from_secs(12))
            .call()
        {
            Ok(response) => response,
            Err(ureq::Error::Status(status, _)) => {
                last_status = Some(status);
                // Reverse proxies commonly expose the same service below a
                // `/web-console` or `/backend` prefix. Try the parent path
                // only when the current candidate is missing.
                if status == 404 {
                    continue;
                }
                return Err(DesktopDiscoveryError::unavailable(format!(
                    "远程服务返回不可用状态码 {status}"
                )));
            }
            Err(error) => {
                return Err(DesktopDiscoveryError::unavailable(format!(
                    "无法连接远程服务: {error}"
                )));
            }
        };
        if response.status() != 200 {
            last_status = Some(response.status());
            if response.status() == 404 {
                continue;
            }
            return Err(DesktopDiscoveryError::unavailable(format!(
                "远程服务返回不可用状态码 {}",
                response.status()
            )));
        }
        let payload = response.into_string().map_err(|error| {
            DesktopDiscoveryError::invalid(format!("Discovery 响应读取失败: {error}"))
        })?;
        let document: DesktopDiscoveryDocument =
            serde_json::from_str(&payload).map_err(|error| {
                DesktopDiscoveryError::invalid(format!("Discovery 响应不是有效 JSON: {error}"))
            })?;
        validate(&document)?;
        return Ok(document);
    }
    Err(DesktopDiscoveryError::unavailable(format!(
        "远程服务未发布桌面 Discovery（最后状态码 {}）",
        last_status.map_or_else(|| "未知".to_string(), |status| status.to_string())
    )))
}

fn discovery_endpoints(base_url: &str) -> Vec<String> {
    let mut bases = vec![base_url.trim_end_matches('/').to_string()];
    for suffix in ["/web-console", "/backend"] {
        if let Some(parent) = bases[0].strip_suffix(suffix) {
            if !parent.is_empty() {
                bases.push(parent.trim_end_matches('/').to_string());
            }
        }
    }
    bases
        .into_iter()
        .map(|base| format!("{base}/.well-known/dolphin-desktop-bootstrap"))
        .collect()
}

pub fn login_config(
    document: &DesktopDiscoveryDocument,
) -> Result<DesktopLoginConfig, DesktopDiscoveryError> {
    let mode = match document.auth.provider.as_str() {
        "control_plane" => DesktopLoginMode::ControlPlane,
        "apaas" => DesktopLoginMode::Apaas,
        other => {
            return Err(DesktopDiscoveryError::invalid(format!(
                "不支持的认证方式: {other}"
            )))
        }
    };
    let base_url = normalize_login_url(&document.auth.login_url)
        .map_err(|error| DesktopDiscoveryError::invalid(error.message))?;
    Ok(DesktopLoginConfig { mode, base_url })
}

fn validate(document: &DesktopDiscoveryDocument) -> Result<(), DesktopDiscoveryError> {
    if document.schema_version != 1 {
        return Err(DesktopDiscoveryError::invalid(
            "Discovery schema 版本不受支持",
        ));
    }
    if document.deployment_id.trim().is_empty() || document.platform.name.trim().is_empty() {
        return Err(DesktopDiscoveryError::invalid(
            "Discovery 缺少部署或平台标识",
        ));
    }
    if !matches!(
        document.platform.platform_type.as_str(),
        "control_plane" | "apaas_builder"
    ) {
        return Err(DesktopDiscoveryError::invalid("Discovery 平台类型不受支持"));
    }
    if !matches!(document.auth.provider.as_str(), "control_plane" | "apaas") {
        return Err(DesktopDiscoveryError::invalid("Discovery 认证方式不受支持"));
    }
    if document.auth.login_url.trim().is_empty() {
        return Err(DesktopDiscoveryError::invalid("Discovery 缺少登录地址"));
    }
    if let Some(api_base_url) = document.auth.api_base_url.as_deref() {
        normalize_login_url(api_base_url)
            .map_err(|error| DesktopDiscoveryError::invalid(error.message))?;
    }
    Ok(())
}
