"""account-service 启动入口。在 import app.* 之前注入独立的库 + JWT 密钥。

env(部署时设)：
  ACCOUNT_SERVICE_DATABASE_URL  独立账号库
  ACCOUNT_SERVICE_JWT_SECRET    account-service 自己的 JWT 密钥(必须与任何 sidecar 不同)
  ACCOUNT_SERVICE_PORT          监听端口(默认 8100)
注意：必须保证 PUBLIC_ACCOUNT_BASE_URL 为空(authority 模式)。
"""
import os


def main() -> None:
    db = os.environ.get("ACCOUNT_SERVICE_DATABASE_URL")
    if db:
        os.environ["DATABASE_URL"] = db
    secret = os.environ.get("ACCOUNT_SERVICE_JWT_SECRET")
    if secret:
        os.environ["JWT_SECRET_KEY"] = secret
    os.environ["PUBLIC_ACCOUNT_BASE_URL"] = ""  # 强制 authority
    port = int(os.environ.get("ACCOUNT_SERVICE_PORT", "8100"))

    import uvicorn
    from app.config import settings  # 触发用上面注入的 env 实例化 Settings

    if not settings.jwt_secret_key:
        raise SystemExit("account-service 需要 ACCOUNT_SERVICE_JWT_SECRET 或 JWT_SECRET_KEY")

    uvicorn.run("services.account_service.main:app", host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
