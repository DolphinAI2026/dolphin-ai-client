import os

import desktop_sidecar as ds
import desktop_sidecar


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
