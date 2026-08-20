import os
import importlib.util
import ast
from pathlib import Path, PureWindowsPath

import desktop_sidecar as ds
import desktop_sidecar


def _load_sidecar_smoke_checker():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "verify-desktop-sidecar.py"
    spec = importlib.util.spec_from_file_location("verify_desktop_sidecar", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sidecar_smoke_checker_preserves_executable_symlinks(tmp_path):
    target = tmp_path / "sidecar-target"
    target.write_text("sidecar", encoding="utf-8")
    executable = tmp_path / "sidecar"
    executable.symlink_to(target)

    assert _load_sidecar_smoke_checker().sidecar_path(executable) == executable


def test_sidecar_entry_declares_root_form_editor_for_freezing():
    entry_path = Path(__file__).resolve().parents[1] / "desktop_sidecar.py"
    tree = ast.parse(entry_path.read_text(encoding="utf-8"))

    assert any(
        isinstance(node, ast.ImportFrom)
        and node.module == "form_component_editor_impl"
        for node in tree.body
    )


def test_parent_watchdog_skips_missing_parent_id(monkeypatch):
    started = []
    monkeypatch.setattr(ds.threading.Thread, "start", lambda self: started.append(self))

    ds.start_parent_watchdog(0)

    assert started == []


def test_process_exists_handles_missing_and_current_process():
    assert ds.process_exists(0) is False
    assert ds.process_exists(os.getpid()) is True


def test_sidecar_spec_does_not_scan_configuration_sensitive_coding_package():
    spec_path = Path(__file__).resolve().parents[1] / "dolphin-ai-sidecar.spec"

    assert 'collect_submodules("app.coding")' not in spec_path.read_text(encoding="utf-8")


def test_desktop_builds_run_the_sidecar_startup_smoke_check():
    root = Path(__file__).resolve().parents[2]

    for script_name in (
        "build-desktop.sh",
        "build-desktop-x86.sh",
        "build-desktop-windows.ps1",
    ):
        script = (root / "scripts" / script_name).read_text(encoding="utf-8")
        assert "verify-desktop-sidecar.py" in script


def test_arm_desktop_build_isolated_from_a_running_bundle_and_checks_lazy_profile_import():
    root = Path(__file__).resolve().parents[2]
    script = (root / "scripts" / "build-desktop.sh").read_text(encoding="utf-8")

    assert "CARGO_TARGET_DIR=\"$TAURI_TARGET_DIR\"" in script
    assert "mktemp -d /tmp/d-ai-code/build-desktop/tauri-target." in script
    assert "--verify-import app.agents.profile" in script


def test_sqlite_database_url_removes_windows_verbatim_prefix():
    database_path = PureWindowsPath(r"\\?\E:\dolphin_code\.appdata\app.db")

    assert ds.sqlite_database_url(database_path) == (
        r"sqlite+aiosqlite:///E:\dolphin_code\.appdata\app.db"
    )


def test_ensure_jwt_secret_persists(tmp_path):
    s1 = ds.ensure_jwt_secret(tmp_path)
    s2 = ds.ensure_jwt_secret(tmp_path)
    assert s1 and s1 == s2  # 第二次复用持久化的值
    assert (tmp_path / "jwt_secret").read_text(encoding="utf-8").strip() == s1
    # 权限收紧到仅本用户可读
    assert (os.stat(tmp_path / "jwt_secret").st_mode & 0o077) == 0


def test_build_env_sets_required_keys(tmp_path, monkeypatch):
    # 用副本替换 os.environ, 避免 build_env 的写入(尤其 DATABASE_URL)污染同进程其他测试
    monkeypatch.setattr(os, "environ", os.environ.copy())
    env = ds.build_env(data_dir=tmp_path, port=8799)
    assert env["DESKTOP_MODE"] == "1"
    assert env["HOST"] == "127.0.0.1"
    assert env["PORT"] == "8799"
    assert env["DATABASE_URL"] == f"sqlite+aiosqlite:///{tmp_path / 'app.db'}"
    assert "ALLOW_DEFAULT_ENCRYPTION_KEY" not in env
    assert env["ENCRYPTION_KEY"] and env["ENCRYPTION_KEY"] != "default-key-change-in-production-32b"
    assert len(env["JWT_SECRET_KEY"]) >= 32
    # build_env 的契约是"写进 os.environ 并返回所写"; 验证确实写进了 environ
    assert os.environ.get("DESKTOP_MODE") == "1"
    assert os.environ.get("DATABASE_URL") == env["DATABASE_URL"]
    assert os.environ.get("JWT_SECRET_KEY") == env["JWT_SECRET_KEY"]


def test_ensure_encryption_key_persists_and_reuses(tmp_path):
    k1 = desktop_sidecar.ensure_encryption_key(tmp_path)
    assert k1 and k1 not in {"", "default-key-change-in-production-32b", "__GENERATE__"}
    # 0o600 权限
    mode = (tmp_path / "encryption_key").stat().st_mode & 0o777
    assert mode == 0o600
    # 二次调用复用同值
    assert desktop_sidecar.ensure_encryption_key(tmp_path) == k1


def test_build_env_sets_real_key_and_no_bypass(tmp_path):
    env = desktop_sidecar.build_env(data_dir=tmp_path, port=9999)
    assert "ALLOW_DEFAULT_ENCRYPTION_KEY" not in env
    assert env["ENCRYPTION_KEY"] and env["ENCRYPTION_KEY"] != "default-key-change-in-production-32b"


def test_build_env_uses_web_auth_contract(tmp_path):
    env = desktop_sidecar.build_env(data_dir=tmp_path, port=9999)
    assert env["PUBLIC_ACCOUNT_BASE_URL"] == ""
    assert env["ACCEPTED_TOKEN_ISSUERS"] == "ai-builder,desktop-sidecar"
    assert env["AUTH_PROVIDER"] == "control_plane"


def test_build_env_sets_workspace_root(tmp_path):
    env = desktop_sidecar.build_env(data_dir=tmp_path / ".appdata", port=9999)
    assert env["APAAS_WORKSPACE_ROOT"] == str(tmp_path / "applications")


def test_build_env_maps_control_plane_login_and_user_root(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "environ", os.environ.copy())
    data_dir = tmp_path / ".appdata"
    env = ds.build_env(
        data_dir=data_dir,
        port=8799,
        login_mode="control_plane",
        login_base_url="https://om-demo.dfy.definesys.cn",
        applications_root=tmp_path / "applications",
        runtime_data_dir=data_dir / "runtime",
    )
    assert env["AUTH_PROVIDER"] == "control_plane"
    assert env["DOLPHIN_WORKSPACE_BASE_URL"] == "https://om-demo.dfy.definesys.cn"
    assert env["DOLPHIN_CODE_CONTROL_PLANE_URL"] == (
        "https://om-demo.dfy.definesys.cn/control-plane"
    )
    assert env["APAAS_BASE_URL"] == ""
    assert env["APAAS_WORKSPACE_ROOT"] == str(tmp_path / "applications")
    assert env["DOLPHIN_LOCAL_RUNTIME_DATA_DIR"] == str(data_dir / "runtime")


def test_build_env_maps_apaas_login(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "environ", os.environ.copy())
    env = ds.build_env(
        data_dir=tmp_path / ".appdata",
        port=8799,
        login_mode="apaas",
        login_base_url="https://apaas-trial.definesys.cn/backend",
        applications_root=tmp_path / "applications",
        runtime_data_dir=tmp_path / ".appdata/runtime",
    )
    assert env["AUTH_PROVIDER"] == "apaas"
    assert env["APAAS_BASE_URL"] == "https://apaas-trial.definesys.cn/backend"
    assert env["DOLPHIN_WORKSPACE_BASE_URL"] == ""
    assert env["DOLPHIN_CODE_CONTROL_PLANE_URL"] == ""


def test_control_plane_code_url_does_not_duplicate_suffix():
    assert ds.control_plane_code_url("https://control.example/control-plane/") == (
        "https://control.example/control-plane"
    )
