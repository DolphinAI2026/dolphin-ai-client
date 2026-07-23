use super::contract::{
    InstanceStatus, LocalRuntimeError, LocalRuntimeErrorCode, ReconcileResult, StartRequest,
};
use super::manager::{LocalRuntimeManager, RuntimeDriver};
use super::mxc_driver::MxcRuntimeDriver;
use std::io::Read;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Condvar, Mutex};
use std::thread::{self, JoinHandle};
use std::time::Duration;
use tiny_http::{Header, Method, Request, Response, Server, StatusCode};

const MAX_REQUEST_BYTES: u64 = 64 * 1024;

pub trait RuntimeManagerApi: Send + Sync {
    fn start(&self, request: StartRequest) -> Result<InstanceStatus, LocalRuntimeError>;
    fn status(&self, runtime_scope_id: &str) -> Result<Option<InstanceStatus>, LocalRuntimeError>;
    fn stop(
        &self,
        runtime_scope_id: &str,
        sandbox_instance_id: &str,
    ) -> Result<InstanceStatus, LocalRuntimeError>;
    fn reconcile(&self) -> Vec<ReconcileResult>;
}

impl<D> RuntimeManagerApi for LocalRuntimeManager<D>
where
    D: RuntimeDriver + Send + Sync,
{
    fn start(&self, request: StartRequest) -> Result<InstanceStatus, LocalRuntimeError> {
        LocalRuntimeManager::start(self, request)
    }

    fn status(&self, runtime_scope_id: &str) -> Result<Option<InstanceStatus>, LocalRuntimeError> {
        LocalRuntimeManager::status(self, runtime_scope_id)
    }

    fn stop(
        &self,
        runtime_scope_id: &str,
        sandbox_instance_id: &str,
    ) -> Result<InstanceStatus, LocalRuntimeError> {
        LocalRuntimeManager::stop(self, runtime_scope_id, sandbox_instance_id)
    }

    fn reconcile(&self) -> Vec<ReconcileResult> {
        LocalRuntimeManager::reconcile(self)
    }
}

pub struct LocalRuntimeApiServer {
    pub base_url: String,
    pub token: String,
    manager: Arc<dyn RuntimeManagerApi>,
    shutdown: Arc<AtomicBool>,
    inflight: Arc<InFlightRequests>,
    worker: Option<JoinHandle<()>>,
}

impl LocalRuntimeApiServer {
    pub fn start(
        data_root: impl Into<PathBuf>,
        appliance_root: impl Into<PathBuf>,
    ) -> Result<Self, LocalRuntimeError> {
        let manager = Arc::new(LocalRuntimeManager::new(
            data_root,
            MxcRuntimeDriver::with_appliance_root(appliance_root),
        ));
        let _ = manager.reconcile();
        Self::start_with_manager(manager)
    }

    fn start_with_manager(manager: Arc<dyn RuntimeManagerApi>) -> Result<Self, LocalRuntimeError> {
        let server = Server::http("127.0.0.1:0").map_err(|error| {
            LocalRuntimeError::new(
                LocalRuntimeErrorCode::ProbeFailed,
                format!("cannot bind local runtime manager: {error}"),
            )
        })?;
        let address = server.server_addr().to_ip().ok_or_else(|| {
            LocalRuntimeError::new(
                LocalRuntimeErrorCode::ProbeFailed,
                "local runtime manager did not bind an IP loopback address",
            )
        })?;
        if !address.ip().is_loopback() {
            return Err(LocalRuntimeError::new(
                LocalRuntimeErrorCode::ProbeFailed,
                "local runtime manager must bind a loopback address",
            ));
        }
        let token = random_token()?;
        let shutdown = Arc::new(AtomicBool::new(false));
        let worker_shutdown = shutdown.clone();
        let worker_token = token.clone();
        let worker_manager = manager.clone();
        let inflight = Arc::new(InFlightRequests::default());
        let worker_inflight = inflight.clone();
        let worker = thread::spawn(move || {
            while !worker_shutdown.load(Ordering::Relaxed) {
                match server.recv_timeout(Duration::from_millis(100)) {
                    Ok(Some(request)) => {
                        let manager = worker_manager.clone();
                        let token = worker_token.clone();
                        let guard = worker_inflight.enter();
                        thread::spawn(move || {
                            let _guard = guard;
                            handle_request(request, manager, &token);
                        });
                    }
                    Ok(None) => {}
                    Err(error) => {
                        log::warn!("local runtime manager stopped accepting requests: {error}");
                        break;
                    }
                }
            }
        });
        Ok(Self {
            base_url: format!("http://{address}"),
            token,
            manager,
            shutdown,
            inflight,
            worker: Some(worker),
        })
    }

    pub fn shutdown(&mut self) {
        self.shutdown.store(true, Ordering::Relaxed);
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
        self.inflight.wait_for_drain(Duration::from_secs(35));
        let _ = self.manager.reconcile();
    }
}

impl Drop for LocalRuntimeApiServer {
    fn drop(&mut self) {
        self.shutdown();
    }
}

#[derive(Default)]
struct InFlightRequests {
    count: Mutex<usize>,
    drained: Condvar,
}

impl InFlightRequests {
    fn enter(self: &Arc<Self>) -> InFlightGuard {
        *self
            .count
            .lock()
            .expect("in-flight request lock is poisoned") += 1;
        InFlightGuard(self.clone())
    }

    fn wait_for_drain(&self, timeout: Duration) {
        let count = self
            .count
            .lock()
            .expect("in-flight request lock is poisoned");
        let _ = self
            .drained
            .wait_timeout_while(count, timeout, |count| *count > 0);
    }
}

struct InFlightGuard(Arc<InFlightRequests>);

impl Drop for InFlightGuard {
    fn drop(&mut self) {
        let mut count = self
            .0
            .count
            .lock()
            .expect("in-flight request lock is poisoned");
        *count = count.saturating_sub(1);
        if *count == 0 {
            self.0.drained.notify_all();
        }
    }
}

fn handle_request(mut request: Request, manager: Arc<dyn RuntimeManagerApi>, token: &str) {
    if !authorized(&request, token) {
        respond(request, 401, serde_json::json!({"error": "unauthorized"}));
        return;
    }

    let path = request.url().split('?').next().unwrap_or_default();
    let components: Vec<_> = path.trim_matches('/').split('/').collect();
    let method = request.method().clone();
    let result = match (method, components.as_slice()) {
        (Method::Post, ["v1", "local-runtime", "instances", "start"]) => {
            read_start_request(&mut request).and_then(|start| manager.start(start))
        }
        (Method::Get, ["v1", "local-runtime", "instances", runtime_scope_id])
            if valid_identifier(runtime_scope_id) =>
        {
            match manager.status(runtime_scope_id) {
                Ok(Some(status)) => Ok(status),
                Ok(None) => {
                    respond(request, 404, serde_json::json!({"error": "not_found"}));
                    return;
                }
                Err(error) => Err(error),
            }
        }
        (Method::Delete, ["v1", "local-runtime", "instances", runtime_scope_id, instance_id])
            if valid_identifier(runtime_scope_id) && valid_identifier(instance_id) =>
        {
            manager.stop(runtime_scope_id, instance_id)
        }
        _ => {
            respond(request, 404, serde_json::json!({"error": "not_found"}));
            return;
        }
    };

    match result {
        Ok(status) => respond(
            request,
            200,
            serde_json::to_value(status).unwrap_or_default(),
        ),
        Err(error) => {
            let status = match error.code {
                LocalRuntimeErrorCode::InvalidRequest => 400,
                LocalRuntimeErrorCode::InstanceConflict
                | LocalRuntimeErrorCode::ReconcileIdentityMismatch => 409,
                _ => 503,
            };
            respond(
                request,
                status,
                serde_json::json!({"error": format!("{:?}", error.code), "message": error.message}),
            );
        }
    }
}

fn authorized(request: &Request, token: &str) -> bool {
    let expected = format!("Bearer {token}");
    request
        .headers()
        .iter()
        .find(|header| header.field.equiv("Authorization"))
        .map(|header| header.value.as_str() == expected)
        .unwrap_or(false)
}

fn read_start_request(request: &mut Request) -> Result<StartRequest, LocalRuntimeError> {
    let mut bytes = Vec::new();
    request
        .as_reader()
        .take(MAX_REQUEST_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|error| {
            LocalRuntimeError::new(
                LocalRuntimeErrorCode::InvalidRequest,
                format!("cannot read local runtime start request: {error}"),
            )
        })?;
    if bytes.len() as u64 > MAX_REQUEST_BYTES {
        return Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::InvalidRequest,
            "local runtime start request is too large",
        ));
    }
    serde_json::from_slice(&bytes).map_err(|error| {
        LocalRuntimeError::new(
            LocalRuntimeErrorCode::InvalidRequest,
            format!("invalid local runtime start request: {error}"),
        )
    })
}

fn respond(request: Request, status: u16, body: serde_json::Value) {
    let response = Response::from_string(body.to_string())
        .with_status_code(StatusCode(status))
        .with_header(
            Header::from_bytes("Content-Type", "application/json; charset=utf-8")
                .expect("static header is valid"),
        );
    let _ = request.respond(response);
}

fn valid_identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 160
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
}

fn random_token() -> Result<String, LocalRuntimeError> {
    let mut bytes = [0_u8; 32];
    getrandom::fill(&mut bytes).map_err(|error| {
        LocalRuntimeError::new(
            LocalRuntimeErrorCode::ProbeFailed,
            format!("cannot generate local runtime manager token: {error}"),
        )
    })?;
    Ok(bytes.iter().map(|byte| format!("{byte:02x}")).collect())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(Default)]
    struct FakeManager {
        status: Mutex<Option<InstanceStatus>>,
    }

    impl RuntimeManagerApi for FakeManager {
        fn start(&self, request: StartRequest) -> Result<InstanceStatus, LocalRuntimeError> {
            let status = InstanceStatus {
                runtime_scope_id: request.runtime_scope_id,
                application_id: request.application_id,
                sandbox_instance_id: request.sandbox_instance_id,
                state: super::super::contract::InstanceState::Ready,
                pid: 41001,
                runtime_base_url: "http://127.0.0.1:41001".into(),
                builder_url: "http://127.0.0.1:41001/builder/".into(),
                started_at: "2026-07-21T00:00:00Z".into(),
            };
            *self.status.lock().unwrap() = Some(status.clone());
            Ok(status)
        }

        fn status(
            &self,
            _runtime_scope_id: &str,
        ) -> Result<Option<InstanceStatus>, LocalRuntimeError> {
            Ok(self.status.lock().unwrap().clone())
        }

        fn stop(
            &self,
            _runtime_scope_id: &str,
            _sandbox_instance_id: &str,
        ) -> Result<InstanceStatus, LocalRuntimeError> {
            self.status.lock().unwrap().take().ok_or_else(|| {
                LocalRuntimeError::new(LocalRuntimeErrorCode::InstanceConflict, "not active")
            })
        }

        fn reconcile(&self) -> Vec<ReconcileResult> {
            Vec::new()
        }
    }

    #[test]
    fn api_requires_bearer_token_and_returns_status() {
        let manager = Arc::new(FakeManager::default());
        let server = LocalRuntimeApiServer::start_with_manager(manager).unwrap();
        let denied = ureq::get(&format!(
            "{}/v1/local-runtime/instances/scope-a",
            server.base_url
        ))
        .call()
        .unwrap_err();
        assert_eq!(denied.into_response().unwrap().status(), 401);

        let response = ureq::get(&format!(
            "{}/v1/local-runtime/instances/scope-a",
            server.base_url
        ))
        .set("Authorization", &format!("Bearer {}", server.token))
        .call()
        .unwrap_err();
        assert_eq!(response.into_response().unwrap().status(), 404);
    }

    #[test]
    fn api_starts_then_reads_an_instance_by_scope() {
        let manager = Arc::new(FakeManager::default());
        let server = LocalRuntimeApiServer::start_with_manager(manager).unwrap();
        let payload = serde_json::json!({
            "runtime_scope_id": "scope-a",
            "application_id": "app-a",
            "sandbox_instance_id": "instance-a",
            "workspace_id": "workspace-a",
            "worktree_path": "/tmp/worktree",
            "git_common_dir": "/tmp/git-common",
            "codex_home": "/tmp/codex",
            "runtime_dir": "/tmp/runtime",
            "runtime_context_path": "/tmp/runtime/runtime-context.json",
            "agent_runtime_path": "/opt/agent-runtime/agent-runtime",
            "runtime_addr": "127.0.0.1:41001",
            "environment": {}
        });
        let authorization = format!("Bearer {}", server.token);
        let started = ureq::post(&format!(
            "{}/v1/local-runtime/instances/start",
            server.base_url
        ))
        .set("Authorization", &authorization)
        .set("Content-Type", "application/json")
        .send_string(&payload.to_string())
        .unwrap();
        assert_eq!(started.status(), 200);

        let status = ureq::get(&format!(
            "{}/v1/local-runtime/instances/scope-a",
            server.base_url
        ))
        .set("Authorization", &authorization)
        .call()
        .unwrap();
        let mut body = String::new();
        status.into_reader().read_to_string(&mut body).unwrap();
        let body: serde_json::Value = serde_json::from_str(&body).unwrap();
        assert_eq!(body["sandbox_instance_id"], "instance-a");
    }
}
