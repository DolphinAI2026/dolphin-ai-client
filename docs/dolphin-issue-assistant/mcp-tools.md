# 问题助手 MCP 工具

## Endpoint

```text
https://agent.dfy.definesys.cn/api/mcp/mcp
```

认证：

```http
Authorization: Bearer ${MCP_API_KEY}
```

自定义 Body 字段：

```json
{
  "tenant_id": "{{tenant_id}}",
  "user_id": "{{user_id}}"
}
```

## record_product_issue

记录右侧问题助手识别出的咨询、配置问题、疑似 Bug 或需求建议。这个工具只记录，不改 git，不部署。

核心参数：

```json
{
  "summary": "应用资产库空白",
  "user_message": "我打开自开发资产库啥都没有，是不是坏了？",
  "classification": "bug",
  "severity": "normal",
  "current_url": "https://agent.dfy.definesys.cn/ai-builder/workspace-catalog",
  "page_title": "自开发资产库",
  "reproduction_steps": "1. 进入自开发资产库\n2. 页面显示空白\n3. 刷新后仍为空",
  "expected_behavior": "显示当前租户的自开发资产列表或明确空态",
  "actual_behavior": "页面只有空白区域，没有解释",
  "evidence_json": "{\"browser\":\"Chrome\",\"screenshot\":\"用户截图显示右侧空白\"}",
  "suggested_action": "检查资产库接口和空态文案",
  "can_auto_fix": true,
  "auto_fix_scope": "dev"
}
```

`classification` 允许值：

- `bug`
- `howto`
- `config`
- `permission`
- `feature_request`
- `needs_info`

## list_product_issues

查看已记录问题。

示例：

```json
{
  "classification": "bug",
  "status": "recorded",
  "limit": 20
}
```

## get_dev_fix_policy

回答“能不能自动修”“会不会动 main”“什么时候部署 dev”时调用。

返回要点：

- 允许自动修复分支：`dev`
- 禁止分支：`main` / `master` / `prod` / `production`
- dev 部署时间：每天 19:00
- 部署命令：`scripts/deploy_k8s_dev.sh`
- 自动任务 ID：`19-00-dev`

## 辅助工具

可按需使用：

- `browser_screenshot`：页面证据截图。
- `browser_snapshot`：读取页面结构，确认按钮、表单、空态。
- `list_deploy_records`：用户问某个应用部署历史时使用，需要 `app_id`。

