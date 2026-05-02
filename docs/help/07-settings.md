# 设置 (`/platform-envs`)

集中配置 LLM 模型、平台环境、租户成员。

## LLM 配置 (`?tab=llm`)

- 配置 OpenAI / Anthropic / DeepSeek / 自部署 vLLM 等
- 每条记录：`{ provider, model, api_key, base_url, default }`
- 必须有 1 个默认配置（is_default=true），否则 AI 模块报错"无可用模型"
- 项目内置一些默认 LLM，启动时同步到 `llm_configs` 表

## 平台环境 (`?tab=envs`)

得帆云 aPaaS 平台地址 + 凭证。

- `env_name` / `base_url` / `platform_tenant_id` / `username` + `password` 或 `token`
- 一个 tenant 可以配多个环境（开发 / 测试 / 生产），其中一个 is_default=true
- 状态：`connected` / `disconnected`（依据上次登录）
- 每个环境有「测试连接」「设为默认」「断开」按钮
- DevOps 环境拓扑 tab 自动列出所有环境

## 成员管理 (`/tenant-users`)

仅 tenant_admin 可见。

- 邀请用户加入当前 tenant
- 设置角色：admin / member
- 启停账号
- 应用级别另有 4 角色（owner / maintainer / contributor / viewer），通过应用卡片「成员管理」管理

## 命令面板 (⌘K)

任何页面按 `⌘K` 打开命令面板：
- 快速跳转（应用 / DevOps / IDE / Vibe Coding / 设置）
- 输入关键词过滤
