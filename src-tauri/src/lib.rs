pub mod desktop_backend;
pub mod desktop_config;
pub mod desktop_discovery;
pub mod local_runtime;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            desktop_backend::desktop_get_state,
            desktop_backend::desktop_save_setup,
            desktop_backend::desktop_test_service,
            desktop_backend::desktop_enter_login_setup,
            desktop_backend::desktop_retry_start,
            desktop_backend::desktop_update_login,
            desktop_backend::desktop_update_workspace_entry_scope,
            desktop_backend::desktop_open_path,
            desktop_backend::desktop_discover_service,
        ])
        .setup(desktop_backend::setup)
        .build(tauri::generate_context!())
        .expect("error while running tauri application")
        .run(desktop_backend::handle_run_event);
}
