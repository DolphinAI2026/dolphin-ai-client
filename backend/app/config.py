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
    apaas_base_url: str = ""
    apaas_tenant_id: str = ""
    # 双端口 / 无 /backend 拓扑覆盖（如生产: 登录 API 在 :30607 根路径、RSA 公钥在 UI 端口 :30605）。
    # 留空 = 沿用单 origin 默认推导（trial: origin+/backend、origin/platform/apaasRsa.pub）。
    # 见 routes/mcp_platform._api_base / _get_apaas_rsa_public_key。
    apaas_api_base: str = ""        # 登录+API 根 URL；设了就直接用，不再 origin+/backend
    apaas_rsa_pub_url: str = ""     # RSA 公钥完整 URL；设了就用它取，不再 origin/platform/apaasRsa.pub

    # LLM Configuration
    # 兼容保留：运行时统一走 ANTHROPIC_BASE_URL，LLM_API_BASE 不再实际参与请求
    llm_api_base: str = "https://api.minimaxi.com/anthropic"
    llm_api_key: str = ""
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
    # 显式允许用上面的默认 key 跑(仅本地开发/历史数据兼容); 生产必须配真实 ENCRYPTION_KEY
    allow_default_encryption_key: bool = False

    # Agent Turn Limits（可通过 .env 覆盖）
    coding_max_turns: int = 30
    """CodingAgent 最大轮次，对应 CODING_MAX_TURNS 环境变量"""
    verification_max_turns: int = 20
    """VerificationAgent 最大轮次，对应 VERIFICATION_MAX_TURNS 环境变量"""

    # Code Generation
    # 是否为资源编码添加随机后缀（避免编码冲突）
    # 开发/测试环境建议开启，生产环境建议关闭
    enable_code_suffix: bool = False

    # aPaaS 后端打包 JDK 版本。一个部署环境通常只服务一种 aPaaS 后端包，
    # 因此优先用环境级配置锁定，而不是每次从 pom.xml 猜。
    # 可选值：8 / 17 / auto；默认 17。
    apaas_backend_jdk_version: str = "17"

    # Web IDE (code-server)
    # code-server 外部访问基础 URL。留空时按当前请求域名 + 部署前缀自动推导
    # （如 https://your-domain.com/ai-builder/ide/）；仅单独 IDE 域名等特殊拓扑需要配置。
    code_server_base_url: str = ""

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
