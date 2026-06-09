# 设置 (`/platform-envs`)

集中配置 LLM 模型、租户成员。客户的 aPaaS 平台地址由部署配置绑定。

## LLM 配置 (`?tab=llm`)

- 配置 OpenAI / Anthropic / DeepSeek / 自部署 vLLM 等
- 每条记录：`{ provider, model, api_key, base_url, default }`
- 必须有 1 个默认配置（is_default=true），否则 AI 模块报错"无可用模型"
- 项目内置一些默认 LLM，启动时同步到 `llm_configs` 表

## 成员管理 (`/tenant-users`)

仅 tenant_admin 可见。

- 邀请用户加入当前 tenant
- 设置角色：admin / member
- 启停账号
- 应用级别另有 4 角色（owner / maintainer / contributor / viewer），通过应用卡片「成员管理」管理

## 命令面板 (⌘K)

任何页面按 `⌘K` 打开命令面板：
- 快速跳转（应用 / IDE / 设置）
- 输入关键词过滤
