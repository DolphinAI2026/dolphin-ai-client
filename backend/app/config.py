from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # aPaaS Platform
    apaas_base_url: str = "https://apaas-poc.definesys.cn/backend"
    apaas_tenant_id: str = "743906758237356033"

    # LLM Configuration
    # 兼容保留：运行时统一走 ANTHROPIC_BASE_URL，LLM_API_BASE 不再实际参与请求
    llm_api_base: str = "https://api.minimaxi.com/anthropic"
    llm_api_key: str
    llm_model: str = "MiniMax-M2.7"
    llm_doc_model: str = "MiniMax-M2.7"
    llm_vision_model: str = "MiniMax-M2.7"
    anthropic_base_url: str = "https://api.minimaxi.com/anthropic"
    anthropic_api_key: str | None = None
    anthropic_model: str = "MiniMax-M2.7"

    # Database (MySQL)
    database_url: str = "mysql+aiomysql://root:password@localhost:3306/apaas_builder"

    # JWT
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Encryption
    encryption_key: str = "default-key-change-in-production-32b"  # Fernet key for password encryption

    # Code Generation
    # 是否为资源编码添加随机后缀（避免编码冲突）
    # 开发/测试环境建议开启，生产环境建议关闭
    enable_code_suffix: bool = False

    # Web IDE (code-server)
    # code-server 的外部访问基础 URL，留空则禁用 Web IDE 功能
    code_server_base_url: str = ""  # e.g. https://your-domain.com/ide/


settings = Settings()
