"""桌面交付驾驶舱 — 本地 sidecar 入口 (被 PyInstaller 打成 onefile)。

职责: 在 import 任何 app.* (会在 import 期实例化 Settings) 之前, 把本地运行
所需的全部环境变量注入 os.environ, 然后以 app 对象方式启动 uvicorn。
"""
import argparse
import multiprocessing
import os
import runpy
import secrets
import sys
import traceback
from pathlib import Path

# This module is stdlib-only. Keep the import at entrypoint scope so PyInstaller
# freezes it independently of the configuration-sensitive app package scan.
from app.coding.form_component_editor import normalize_form_component_editor_artifacts


def ensure_jwt_secret(data_dir: Path) -> str:
    """每安装实例持久化一个 JWT 密钥 (避免每次启动 session 失效)。"""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    f = data_dir / "jwt_secret"
    if f.is_file():
        existing = f.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    val = secrets.token_urlsafe(48)
    f.write_text(val, encoding="utf-8")
    f.chmod(0o600)  # 仅本用户可读, 避免同机其他用户读走伪造 token
    return val


def ensure_encryption_key(data_dir: Path) -> str:
    """每安装实例持久化一个加密主密钥 (Fernet key 由 crypto.py 对它 sha256 派生)。

    替掉 Phase 0 的 ALLOW_DEFAULT_ENCRYPTION_KEY 旁路: 用真实高熵 key, 让 main.py
    的加密安全门合法放行, 而非被绕过。
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    f = data_dir / "encryption_key"
    if f.is_file():
        existing = f.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    val = secrets.token_urlsafe(48)
    f.write_text(val, encoding="utf-8")
    f.chmod(0o600)
    return val


def sqlite_database_url(database_path: Path) -> str:
    """Build a SQLite URL that accepts canonical Windows device paths."""
    path = str(database_path)
    if path.startswith("\\\\?\\UNC\\"):
        path = "\\\\" + path[8:]
    elif path.startswith("\\\\?\\"):
        path = path[4:]
    return f"sqlite+aiosqlite:///{path}"


def control_plane_code_url(login_base_url: str) -> str:
    """Derive the remote Code Control Plane from the desktop login service.

    The desktop sidecar must not fall back to a developer-local coordinator. A
    separately configured Code URL can still
    be supplied by the Tauri launcher; this helper covers the web/sidecar path.
    """
    base = str(login_base_url or "").strip().rstrip("/")
    if not base:
        return ""
    return base if base.endswith("/control-plane") else f"{base}/control-plane"


def build_env(
    data_dir: Path,
    port: int,
    *,
    login_mode: str = "control_plane",
    login_base_url: str = "https://om-demo.dfy.definesys.cn",
    applications_root: Path | None = None,
    runtime_data_dir: Path | None = None,
) -> dict:
    """构造并写入本地运行所需的环境变量, 返回写入的子集 (便于测试)。"""
    if login_mode not in {"control_plane", "apaas"}:
        raise ValueError("login_mode must be control_plane or apaas")
    data_dir = Path(data_dir)
    applications_root = Path(applications_root or data_dir.parent / "applications")
    runtime_data_dir = Path(runtime_data_dir or data_dir / "runtime")
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "app.db"
    written = {
        "DESKTOP_MODE": "1",
        "HOST": "127.0.0.1",
        "PORT": str(port),
        # data_dir 的真相源：Tauri 经 --data-dir 传入(app_data_dir, 各平台不同)。
        # 显式导出, 让 skills_root() 等下游不必各自猜路径。
        "SIDECAR_DATA_DIR": str(data_dir),
        # Windows canonicalize 会产生 \\?\ 设备路径；SQLite URL 必须先转回普通路径，
        # 否则问号会被 URL 解析器当成查询分隔符并截断数据库文件名。
        "DATABASE_URL": sqlite_database_url(db_path),
        # 每实例持久化的加密主密钥 (crypto.py 对它 sha256 派生 Fernet key)。
        "ENCRYPTION_KEY": ensure_encryption_key(data_dir),
        "JWT_SECRET_KEY": ensure_jwt_secret(data_dir),
        # 桌面与 Web 复用 Control Plane/aPaaS 登录协议，不再走独立 desktop 账号服务。
        "AUTH_PROVIDER": login_mode,
        "DOLPHIN_WORKSPACE_BASE_URL": (
            login_base_url if login_mode == "control_plane" else ""
        ),
        # Keep Code's remote coordinator aligned with the selected login
        # service.  Empty in standalone aPaaS mode, which has no Code plane.
        "DOLPHIN_CODE_CONTROL_PLANE_URL": (
            control_plane_code_url(login_base_url)
            if login_mode == "control_plane"
            else ""
        ),
        "APAAS_BASE_URL": login_base_url if login_mode == "apaas" else "",
        "PUBLIC_ACCOUNT_BASE_URL": "",
        # The sidecar may issue its own desktop-sidecar ticket after remote
        # Control Plane authentication. This whitelist is local-only; shared
        # backends still reject that issuer at startup.
        "ACCEPTED_TOKEN_ISSUERS": "ai-builder,desktop-sidecar",
        "APAAS_WORKSPACE_ROOT": str(applications_root),
        "DOLPHIN_LOCAL_RUNTIME_DATA_DIR": str(runtime_data_dir),
    }
    for k, v in written.items():
        os.environ[k] = v
    _sync_preset_skills(data_dir)
    return written


def _sync_preset_skills(data_dir: Path) -> None:
    """把随包的 preset-skills 同步进 data_dir/skills/platform/（覆盖式，平台只读）。"""
    import shutil
    # 冻结态资源在 sys._MEIPASS 下；dev 态在仓库 backend/desktop/preset-skills
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "desktop" / "preset-skills"
    if not base.is_dir():
        return
    dest = Path(data_dir) / "skills" / "platform"
    dest.mkdir(parents=True, exist_ok=True)
    for d in base.iterdir():
        if d.is_dir():
            shutil.copytree(d, dest / d.name, dirs_exist_ok=True)


def run_script(path: str) -> int:
    """用本进程(冻结二进制即自带解释器+已打包依赖)执行一个 .py 文件。

    供 run_python 在桌面态调用: dolphin-ai-sidecar --run-script <file>。
    不起 uvicorn、不建 DB。stdout/stderr 继承父进程(由调用方 subprocess 捕获)。
    """
    try:
        runpy.run_path(path, run_name="__main__")
        return 0
    except SystemExit as exc:
        code = exc.code
        return code if isinstance(code, int) else (0 if code is None else 1)
    except BaseException:
        traceback.print_exc()
        return 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.environ.get("SIDECAR_PORT", "8799")))
    parser.add_argument("--data-dir", type=str, default=os.environ.get("SIDECAR_DATA_DIR", ""))
    parser.add_argument(
        "--login-mode",
        choices=("control_plane", "apaas"),
        default="control_plane",
    )
    parser.add_argument(
        "--login-base-url",
        default="https://om-demo.dfy.definesys.cn",
    )
    parser.add_argument("--applications-root", type=Path)
    parser.add_argument("--runtime-data-dir", type=Path)
    parser.add_argument("--run-script", type=str, default="")
    args = parser.parse_args()

    if args.run_script:
        sys.exit(run_script(args.run_script))

    data_dir = Path(args.data_dir) if args.data_dir else (Path.home() / "DolphinAI" / ".appdata")

    # 注入本地基础设施 env (必须早于任何 app.* import)。
    # 注意: aPaaS/LLM 等"用户配置"不走这里 — 它们由用户在应用内 UI 配置,
    # 存进本地 SQLite 的 PlatformEnv / LLMConfig 表。这里只设本地运行管道。
    build_env(
        data_dir=data_dir,
        port=args.port,
        login_mode=args.login_mode,
        login_base_url=args.login_base_url,
        applications_root=args.applications_root,
        runtime_data_dir=args.runtime_data_dir,
    )

    # 现在才 import app (此时 Settings() 能读到上面注入的 env)
    import uvicorn
    from app.main import app  # noqa: E402  传 app 对象, 不用 "app.main:app" 字符串

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    multiprocessing.freeze_support()  # 冻结二进制下安全 (即便单 worker 也加, 保险)
    main()
