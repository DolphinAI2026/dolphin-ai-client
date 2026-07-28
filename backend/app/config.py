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
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # aPaaS Platform
    # 登录方式：control_plane 或 apaas。local/coding 仅保留旧部署兼容。
    auth_provider: str = "control_plane"
    # Builder 登录策略和产品入口可由配置文件显式覆盖；留空时兼容 AUTH_PROVIDER。
    builder_auth_default_login_provider: str = ""
    builder_auth_enabled_login_providers: str = ""
    builder_product_builder_enabled: bool = True
    builder_product_code_enabled: bool = True
    builder_auth_platform_mode: str = ""
    builder_auth_apaas_label: str = "aPaaS 账号"
    builder_auth_platform_label: str = "平台账号"
    # 可选项：开启后，Dolphin 登录账号必须已在平台管理绑定本地租户和 aPaaS 环境。
    # 默认关闭；关闭时按 Dolphin 当前租户自动创建/复用本地租户上下文。
    control_plane_binding_enabled: bool = False
    # 可选项：Control Plane 登录页所在环境的根地址。
    dolphin_workspace_base_url: str = "https://om-demo.dfy.definesys.cn"
    apaas_base_url: str = ""
    # 桌面 sidecar: 公网账号权威地址(authority)。空=本实例自身就是 authority。
    public_account_base_url: str = ""
    # 桌面更新产物目录(account-service 挂 PVC /data)。GET manifest/包 + 平台管理员上传都读写这里。
    # 环境变量 DESKTOP_UPDATES_DIR 覆盖。
    desktop_updates_dir: str = "/data/desktop-updates"
    apaas_tenant_id: str = ""
    # Optional local bootstrap credentials for PlatformEnv. Prefer .env.local.
    apaas_token: str = ""
    apaas_username: str = ""
    apaas_password: str = ""
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

    # Database (PostgreSQL for server deployments; SQLite remains available locally)
    database_url: str = "postgresql+asyncpg://postgres:password@localhost:5432/apaas_builder"

    # JWT
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440
    # 接受的 JWT issuer 白名单 (CSV)。共享后端默认只认 ai-builder; 桌面 sidecar
    # 经 env ACCEPTED_TOKEN_ISSUERS 设为 "ai-builder,desktop-sidecar"。
    accepted_token_issuers: str = "ai-builder"

    @property
    def accepted_issuers_set(self) -> set[str]:
        return {s.strip() for s in self.accepted_token_issuers.split(",") if s.strip()}

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

    # Coding 模型配置（多模型支持）
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

    # Control Plane 地址和 Code 模式兼容配置。
    dolphin_code_control_plane_url: str = ""
    dolphin_code_control_plane_token: str = ""
    dolphin_code_control_plane_delegation_secret: str = ""
    # 首次打开真实 Code workspace 会同步等待 Control Plane 完成 Sandbox 部署和运行时就绪。
    # 默认值覆盖其 Helm 安装、部署就绪和运行时探测的组合预算。
    dolphin_code_workspace_open_timeout_seconds: int = 660
    dolphin_code_builder_url: str = ""
    dolphin_code_default_seed_project_id: str = "1781233861147"
    dolphin_code_allow_cookieless_loopback_runtime: bool = False
    # 浏览器热 iframe 只影响切换缓存数量，不改变 Runtime Cookie、Secret
    # 轮换或失败恢复协议。Control Plane 租户覆盖接入前，这里作为部署级默认值。
    dolphin_code_cache_profile: str = "normal"
    dolphin_code_normal_browser_hot_frames: int = 2
    dolphin_code_performance_browser_hot_frames: int = 5
    dolphin_code_normal_server_warm_sandboxes_per_user: int = 4
    dolphin_code_performance_server_warm_sandboxes_per_user: int = 10

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
