use std::sync::Mutex;
use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

struct SidecarChild(Mutex<Option<CommandChild>>);

/// Kill a sidecar process and all its descendants.
///
/// PyInstaller onefile extracts and forks a child process; `child.kill()` only
/// kills the bootloader (direct child). This function:
/// 1. Collects all children of the bootloader BEFORE killing the bootloader
///    (after kill the children get reparented to init and pgrep -P won't find them)
/// 2. Kills the bootloader
/// 3. Kills the collected children
fn kill_sidecar_deep(bootloader_pid: u32) {
    #[cfg(unix)]
    {
        // Step 1: Collect children BEFORE killing the bootloader
        let mut child_pids: Vec<u32> = Vec::new();
        if let Ok(out) = std::process::Command::new("pgrep")
            .args(["-P", &format!("{}", bootloader_pid)])
            .output()
        {
            let output = String::from_utf8_lossy(&out.stdout);
            for line in output.lines() {
                if let Ok(child_pid) = line.trim().parse::<u32>() {
                    child_pids.push(child_pid);
                }
            }
        }
        // Step 2: Kill the bootloader itself
        let _ = std::process::Command::new("kill")
            .args(["-KILL", &format!("{}", bootloader_pid)])
            .status();
        // Step 3: Kill the children (e.g. uvicorn process spawned by PyInstaller)
        for child_pid in child_pids {
            let _ = std::process::Command::new("kill")
                .args(["-KILL", &format!("{}", child_pid)])
                .status();
        }
    }
}

fn pick_free_port() -> u16 {
    std::net::TcpListener::bind("127.0.0.1:0")
        .and_then(|l| l.local_addr())
        .map(|a| a.port())
        .unwrap_or(8799)
}

/// 跨启动稳定的端口。WebView origin = http://127.0.0.1:{port};localStorage(含登录 token)
/// 按 origin 隔离 → 端口每次变就要重新登录。这里把端口持久化进 data_dir/ui_port:
/// 复用上次端口(仍空闲就用),被占了才另选一个并存下来 → origin 稳定 → token 跨重启/重装保留。
fn stable_port(data_dir: &std::path::Path) -> u16 {
    let port_file = data_dir.join("ui_port");
    if let Ok(s) = std::fs::read_to_string(&port_file) {
        if let Ok(p) = s.trim().parse::<u16>() {
            if p != 0 && std::net::TcpListener::bind(("127.0.0.1", p)).is_ok() {
                return p;
            }
        }
    }
    let p = pick_free_port();
    let _ = std::fs::write(&port_file, p.to_string());
    p
}

fn wait_healthy(port: u16) -> bool {
    let url = format!("http://127.0.0.1:{}/api/health", port);
    for _ in 0..60 {
        if let Ok(resp) = ureq::get(&url).timeout(std::time::Duration::from_secs(2)).call() {
            if resp.status() == 200 {
                return true;
            }
        }
        std::thread::sleep(std::time::Duration::from_millis(1000));
    }
    false
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(SidecarChild(Mutex::new(None)))
        .setup(|app| {
            let handle = app.handle().clone();

            let data_dir = handle.path().app_data_dir().expect("app_data_dir");
            std::fs::create_dir_all(&data_dir).ok();

            // 跨启动稳定端口 → WebView origin 不变 → 登录 token(localStorage)保留,不用每次重登。
            let port = stable_port(&data_dir);

            let (mut rx, child) = handle
                .shell()
                .sidecar("ruijing-sidecar")
                .expect("sidecar binary not found")
                .args([
                    "--port".to_string(),
                    port.to_string(),
                    "--data-dir".to_string(),
                    data_dir.to_string_lossy().to_string(),
                ])
                // Phase 1' cutover 验证:桌面包里让 Code 模式走统一引擎 run_agent(dev-apaas profile),
                // 而 tests/本地 dev 仍走默认关(旧 coding 流水线)→ A/B 验证。验证通过后翻代码默认 + 退役旧码。
                .env("CODING_USE_RUNAGENT", "1")
                .spawn()
                .expect("failed to spawn sidecar");

            app.state::<SidecarChild>().0.lock().unwrap().replace(child);

            tauri::async_runtime::spawn(async move {
                while let Some(event) = rx.recv().await {
                    if let CommandEvent::Stdout(b) | CommandEvent::Stderr(b) = event {
                        print!("[sidecar] {}", String::from_utf8_lossy(&b));
                    }
                }
            });

            std::thread::spawn(move || {
                if wait_healthy(port) {
                    let url = format!("http://127.0.0.1:{}/", port);
                    WebviewWindowBuilder::new(
                        &handle,
                        "main",
                        WebviewUrl::External(url.parse().unwrap()),
                    )
                    .title("睿鲸 Builder")
                    .inner_size(1440.0, 900.0)
                    // 关掉 Tauri 原生 OS 级拖放处理：它会拦截页面内的 HTML5 drag-and-drop,
                    // 导致内嵌 apaas 编辑器拖字段失效(真浏览器无此拦截故能拖)。
                    // 前端不依赖 OS 文件拖放(附件走文件选择/粘贴), 关掉无副作用。
                    .disable_drag_drop_handler()
                    .build()
                    .expect("failed to build window");
                } else {
                    eprintln!("[tauri] sidecar 未在超时内就绪, 退出应用");
                    handle.exit(1);
                }
            });

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while running tauri application")
        .run(|app, event| {
            match event {
                RunEvent::ExitRequested { .. } | RunEvent::Exit => {
                    if let Some(child) = app.state::<SidecarChild>().0.lock().unwrap().take() {
                        let pid = child.pid();
                        // Collect and kill children BEFORE killing the bootloader,
                        // because child.kill() causes reparenting to init.
                        kill_sidecar_deep(pid);
                        let _ = child.kill();
                    }
                }
                _ => {}
            }
        });
}
