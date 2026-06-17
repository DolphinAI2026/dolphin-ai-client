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


def build_env(data_dir: Path, port: int) -> dict:
    """构造并写入本地运行所需的环境变量, 返回写入的子集 (便于测试)。"""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "app.db"
    written = {
        "DESKTOP_MODE": "1",
        "HOST": "127.0.0.1",
        "PORT": str(port),
        # data_dir 的真相源：Tauri 经 --data-dir 传入(app_data_dir, 各平台不同)。
        # 显式导出, 让 skills_root() 等下游不必各自猜路径(避免误用 ~/.ruijing-builder 兜底)。
        "SIDECAR_DATA_DIR": str(data_dir),
        # 绝对路径(四斜杠), 避免被 config._normalize_database_url 锚定到 backend/
        "DATABASE_URL": f"sqlite+aiosqlite:///{db_path}",
        # 每实例持久化的加密主密钥 (crypto.py 对它 sha256 派生 Fernet key)。
        "ENCRYPTION_KEY": ensure_encryption_key(data_dir),
        "JWT_SECRET_KEY": ensure_jwt_secret(data_dir),
        # 默认 federation 模式: 转发到公网 account-service 认证(已部署 agent.dfy/account-api)。
        # 新机器用公网账号即可登, 不用复制 app.db。设 PUBLIC_ACCOUNT_BASE_URL="" 可切回本地 authority(离线兜底)。
        "PUBLIC_ACCOUNT_BASE_URL": os.environ.get(
            "PUBLIC_ACCOUNT_BASE_URL", "https://agent.dfy.definesys.cn/account-api"
        ),
        # 桌面 sidecar 接受 ai-builder(内部短票)+ desktop-sidecar(联邦会话票)。
        "ACCEPTED_TOKEN_ISSUERS": "ai-builder,desktop-sidecar",
        # app 托管工作区落 app_data_dir 下(稳定持久), 修冻结包相对二进制诡异路径
        "APAAS_WORKSPACE_ROOT": os.path.join(str(data_dir), "workspaces"),
    }
    for k, v in written.items():
        os.environ[k] = v
    return written


def run_script(path: str) -> int:
    """用本进程(冻结二进制即自带解释器+已打包依赖)执行一个 .py 文件。

    供 run_python 在桌面态调用: ruijing-sidecar --run-script <file>。
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
    parser.add_argument("--run-script", type=str, default="")
    args = parser.parse_args()

    if args.run_script:
        sys.exit(run_script(args.run_script))

    data_dir = Path(args.data_dir) if args.data_dir else (Path.home() / ".ruijing-builder")

    # 注入本地基础设施 env (必须早于任何 app.* import)。
    # 注意: aPaaS/LLM 等"用户配置"不走这里 — 它们由用户在应用内 UI 配置,
    # 存进本地 SQLite 的 PlatformEnv / LLMConfig 表。这里只设本地运行管道。
    build_env(data_dir=data_dir, port=args.port)

    # 现在才 import app (此时 Settings() 能读到上面注入的 env)
    import uvicorn
    from app.main import app  # noqa: E402  传 app 对象, 不用 "app.main:app" 字符串

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    multiprocessing.freeze_support()  # 冻结二进制下安全 (即便单 worker 也加, 保险)
    main()
