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
    llm_api_base: str = "https://api.jiekou.ai/openai"
    llm_api_key: str
    llm_model: str = "claude-haiku-4-5-20251001"

    # Database
    database_url: str = "sqlite+aiosqlite:///./apaas_builder.db"

    # JWT
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Code Generation
    # 是否为资源编码添加随机后缀（避免编码冲突）
    # 开发/测试环境建议开启，生产环境建议关闭
    enable_code_suffix: bool = False


settings = Settings()
