use super::contract::{LocalRuntimeError, LocalRuntimeErrorCode};
use std::fs::{self, OpenOptions};
use std::path::Path;
use std::process::{Child, Command, Stdio};

pub(crate) fn configure_runtime_logs(
    command: &mut Command,
    runtime_dir: &Path,
) -> Result<(), LocalRuntimeError> {
    fs::create_dir_all(runtime_dir).map_err(|error| log_error(runtime_dir, error))?;
    let stdout = open_log(runtime_dir, "runtime.stdout.log")?;
    let stderr = open_log(runtime_dir, "runtime.stderr.log")?;
    command
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr));
    Ok(())
}

pub(crate) fn inspect_runtime_exit(
    child: &mut Child,
    runtime_dir: &Path,
) -> Result<(), LocalRuntimeError> {
    match child.try_wait() {
        Ok(None) => Ok(()),
        Ok(Some(status)) => {
            let exit = status
                .code()
                .map(|code| format!("exit code {code}"))
                .unwrap_or_else(|| "terminated by signal".to_string());
            Err(LocalRuntimeError::new(
                LocalRuntimeErrorCode::SpawnFailed,
                format!(
                    "local runtime exited before readiness ({exit}); inspect {}",
                    runtime_dir.join("runtime.stderr.log").display()
                ),
            ))
        }
        Err(error) => Err(LocalRuntimeError::new(
            LocalRuntimeErrorCode::SpawnFailed,
            format!("cannot inspect local runtime after spawn: {error}"),
        )),
    }
}

fn open_log(runtime_dir: &Path, name: &str) -> Result<std::fs::File, LocalRuntimeError> {
    OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .open(runtime_dir.join(name))
        .map_err(|error| log_error(runtime_dir, error))
}

fn log_error(runtime_dir: &Path, error: std::io::Error) -> LocalRuntimeError {
    LocalRuntimeError::new(
        LocalRuntimeErrorCode::SpawnFailed,
        format!(
            "cannot prepare local runtime logs in {}: {error}",
            runtime_dir.display()
        ),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn runtime_output_is_written_to_instance_logs() {
        let runtime_dir =
            std::env::temp_dir().join(format!("dolphin-runtime-logs-{}", std::process::id()));
        fs::create_dir_all(&runtime_dir).unwrap();
        let mut command = Command::new("sh");
        command.args(["-c", "printf stdout-line; printf stderr-line >&2"]);

        configure_runtime_logs(&mut command, &runtime_dir).unwrap();
        assert!(command.status().unwrap().success());

        assert_eq!(
            fs::read_to_string(runtime_dir.join("runtime.stdout.log")).unwrap(),
            "stdout-line"
        );
        assert_eq!(
            fs::read_to_string(runtime_dir.join("runtime.stderr.log")).unwrap(),
            "stderr-line"
        );
        fs::remove_dir_all(runtime_dir).unwrap();
    }

    #[test]
    fn exited_runtime_reports_spawn_failure_with_log_path() {
        let runtime_dir = Path::new("/tmp/runtime-instance");
        let mut child = Command::new("sh").args(["-c", "exit 7"]).spawn().unwrap();
        child.wait().unwrap();

        let error = inspect_runtime_exit(&mut child, runtime_dir).unwrap_err();

        assert_eq!(error.code, LocalRuntimeErrorCode::SpawnFailed);
        assert!(error.message.contains("exit code 7"));
        assert!(error.message.contains("runtime.stderr.log"));
    }
}
