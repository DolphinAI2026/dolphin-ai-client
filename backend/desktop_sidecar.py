"""桌面交付驾驶舱 — 本地 sidecar 入口 (被 PyInstaller 打成 onefile)。

职责: 在 import 任何 app.* (会在 import 期实例化 Settings) 之前, 把本地运行
所需的全部环境变量注入 os.environ, 然后以 app 对象方式启动 uvicorn。
"""
import argparse
import multiprocessing
import os
import secrets
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


def build_env(data_dir: Path, port: int) -> dict:
    """构造并写入本地运行所需的环境变量, 返回写入的子集 (便于测试)。"""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "app.db"
    written = {
        "DESKTOP_MODE": "1",
        "HOST": "127.0.0.1",
        "PORT": str(port),
        # 绝对路径(四斜杠), 避免被 config._normalize_database_url 锚定到 backend/
        "DATABASE_URL": f"sqlite+aiosqlite:///{db_path}",
        # Phase 0 spike: 允许默认加密 key。Phase 1 改为每实例生成持久化 ENCRYPTION_KEY。
        "ALLOW_DEFAULT_ENCRYPTION_KEY": "1",
        "JWT_SECRET_KEY": ensure_jwt_secret(data_dir),
        "PUBLIC_ACCOUNT_BASE_URL": os.environ.get("PUBLIC_ACCOUNT_BASE_URL", "https://agent.dfy.definesys.cn"),
    }
    for k, v in written.items():
        os.environ[k] = v
    return written


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.environ.get("SIDECAR_PORT", "8799")))
    parser.add_argument("--data-dir", type=str, default=os.environ.get("SIDECAR_DATA_DIR", ""))
    args = parser.parse_args()

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
