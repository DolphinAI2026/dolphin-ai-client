from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# ── 品牌 / 应用常量 ─────────────────────────────────────────
# 集中应用名称相关的硬编码，便于替换或做多租户定制。
# ⚠️ 不覆盖 CLI 命令名 "apaas-builder"，那是命令行工具的调用入口，不属于品牌文案。
APP_TITLE = "aPaaS Builder AI"
APP_BRAND = "aPaaS Builder"
APP_DESCRIPTION = "得帆云低代码平台智能搭建 & Vibe Coding 助手"
APP_VERSION = "1.0.0"

# 上线 / 发布时写入平台的摘要（历史为 "aPaaS Builder 应用上线"）。
APP_DEPLOY_ABSTRACT = f"{APP_BRAND} 应用上线"


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

    # Agent Turn Limits（可通过 .env 覆盖）
    coding_max_turns: int = 30
    """CodingAgent 最大轮次，对应 CODING_MAX_TURNS 环境变量"""
    verification_max_turns: int = 20
    """VerificationAgent 最大轮次，对应 VERIFICATION_MAX_TURNS 环境变量"""

    # Code Generation
    # 是否为资源编码添加随机后缀（避免编码冲突）
    # 开发/测试环境建议开启，生产环境建议关闭
    enable_code_suffix: bool = False

    # Web IDE (code-server)
    # code-server 的外部访问基础 URL，留空则禁用 Web IDE 功能
    code_server_base_url: str = ""  # e.g. https://your-domain.com/ide/

    # IDE Coding 模型配置（多模型支持）
    # 格式：CODING_MODEL_{NAME}_BASE_URL / _API_KEY / _MODEL
    # 前端通过 model 字段选择，后端路由到对应上游
    coding_model_deepseek_base_url: str = ""
    coding_model_deepseek_api_key: str = ""
    coding_model_deepseek_model: str = "deepseek-chat"
    coding_model_qwen_base_url: str = ""
    coding_model_qwen_api_key: str = ""
    coding_model_qwen_model: str = "qwen-plus"
    # 接口.ai 聚合平台（GPT-5.4 / Claude Sonnet 4.6 / Claude Opus 4.6）
    coding_model_gpt54_base_url: str = ""
    coding_model_gpt54_api_key: str = ""
    coding_model_gpt54_model: str = "gpt-5.4"
    coding_model_codex_base_url: str = ""
    coding_model_codex_api_key: str = ""
    coding_model_codex_model: str = "gpt-5.3-codex"
    coding_model_sonnet_base_url: str = ""
    coding_model_sonnet_api_key: str = ""
    coding_model_sonnet_model: str = "claude-sonnet-4-6"
    coding_model_opus_base_url: str = ""
    coding_model_opus_api_key: str = ""
    coding_model_opus_model: str = "claude-opus-4-6"

    # Dolphin omnigate 统一网关（OpenAI 兼容，gpt-5.5 通用模型）
    # 注意：保留以下三个字段是因为 dolphin 提供了对外的 OpenAI 兼容 LLM API gateway。
    # ai-builder 把它当作普通 LLM provider 使用 — 不构成"业务集成"。
    dolphin_base_url: str = ""
    dolphin_api_key: str = ""
    dolphin_model: str = "gpt-5.5"

    # ai-builder 自身的对外 chat URL — 给外部 MCP 客户端生成 deeplink 时用。
    # 外部 agent 把 md push 到 cache 后，工具返回值带
    # {ai_builder_chat_deeplink_base}/chat?from=requirements，agent 把这条链接
    # 贴在 chat 里让用户点击；用户点了在新 tab 跳到 ChatPage，自动从 cache 拿
    # md 走 ChooseAppTargetDialog（新建 / 更新现有应用）。
    # 留空则不下发 deeplink（agent 仍可通过其它指引让用户跳转）。
    # 例：https://ai-builder.dfy.definesys.cn
    ai_builder_chat_deeplink_base: str = ""

    # Vibe Coding 运行时
    # - "auto"   : docker daemon + vibe-sandbox 镜像可用就走 docker；否则 fallback host
    # - "docker" : 强制 docker，不可用直接报错（生产环境用）
    # - "host"   : 强制 host shell，跳过 docker 检测（dev 环境快速迭代用）
    vibe_coding_runtime: str = "auto"
    # docker 容器空闲多久（秒）就 stop 回收（保留容器，下次 start 复用）
    vibe_coding_idle_threshold_sec: int = 1800


def _normalize_database_url(url: str) -> str:
    """将相对 SQLite 路径固定到 backend 目录下，避免随 cwd 漂移。"""
    if not isinstance(url, str) or not url.startswith("sqlite"):
        return url

    prefixes = ("sqlite+aiosqlite:///", "sqlite:///")
    matched_prefix = next((prefix for prefix in prefixes if url.startswith(prefix)), "")
    if not matched_prefix:
        return url

    path_part = url[len(matched_prefix):]
    if path_part == ":memory:" or path_part.startswith("file:"):
        return url
    if not path_part or path_part.startswith("/"):
        return url

    backend_dir = Path(__file__).resolve().parent.parent
    normalized_path = (backend_dir / path_part).resolve()
    return f"{matched_prefix}{normalized_path}"


settings = Settings()
settings.database_url = _normalize_database_url(settings.database_url)
