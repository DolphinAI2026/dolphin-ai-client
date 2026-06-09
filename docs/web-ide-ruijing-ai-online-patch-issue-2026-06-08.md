# 线上 Web IDE 睿鲸 AI 插件未按本地方式生效

## 背景

本地 Web IDE 中睿鲸 AI 可以正常接管 VS Code Chat，但线上部署后 Chat 面板退回了 VS Code 默认 Agent 体验，导致输入 `hello` 后没有睿鲸 AI 的中文回复。

本地地址：

```text
http://localhost:8080/?folder=/Users/mars/.apaas-builder-ai/workspaces/form-page-leave-home-dashboard__1_fce6f785
```

线上地址：

```text
https://agent.dfy.definesys.cn/ai-builder/ide/?folder=/root/apaas-builder/workspaces/form-page-meeting-dashboard__3_f4391c11&_cb=fix4
```

## 现象

本地正常：

- Chat 中显示 `睿鲸AI` participant。
- 输入 `hello` 后返回中文助手回复。
- 回复内容类似：“你好！我是集成在 VS Code 中的中文编程助手。”

线上异常：

- Chat 面板显示 VS Code 默认英文 Agent UI。
- 输入 `hello` 后只有空白/默认完成记录。
- 没有显示 `睿鲸AI` participant 的中文回复。

## 已验证信息

后端整体不是挂掉：

```bash
curl -sS -o /dev/null -w 'health=%{http_code}\n' \
  https://agent.dfy.definesys.cn/ai-builder/api/health
```

结果：

```text
health=200
```

IDE 代理本身也可访问，能拿到 code-server HTML。

线上 HTML 指向的 `workbench.js` 已带缓存参数：

```text
workbench.js?v=patched-1780904101676
```

说明线上打过某种 patch，但进一步检查 `workbench.js` 后发现只有旧 fallback marker：

```text
patched:skip-signin
patched:delegate-to-minimax
```

缺少当前 code-server 4.112 / VS Code 1.112 方案需要的新 marker：

```text
patched:force-models
patched:skip-unknown-check
patched:force-free
```

## 初步判断

这不是简单的“睿鲸 AI 扩展完全没安装”，更像是线上 code-server 仍在使用旧的 Chat fallback patch。

仓库里已有新方案脚本：

```text
scripts/patch_all.js
scripts/patch_vscode_chat_enable.js
```

`scripts/patch_vscode_chat_enable.js` 的注释说明了关键点：

- 旧的 `patch_vscode_chat_fallback.js` 在 code-server 4.112 / VS Code 1.112 上不适用。
- 新方案通过 entitlement patch 让未登录 Copilot 的原生 Chat 可用。
- 新方案还会修改 `product.json`：
  - 放行 `apaas-builder.ruijing-ai` 的 proposed API。
  - 将 `defaultChatAgent` 指向 `apaas-builder.ruijing-ai`。

因此线上异常大概率是部署脚本仍在执行旧的 `patch_vscode_chat_fallback.js`，没有执行 `patch_all.js` / `patch_vscode_chat_enable.js`。

## 需要修复

请检查并修复云部署/线上 IDE 修复链路，重点看：

```text
scripts/deploy_cloud.py
```

需要确认：

1. IDE 部署部分不要再执行旧的 `patch_vscode_chat_fallback.js`。
2. 应改为上传并执行 `patch_all.js`。
3. `patch_all.js` 内部会调用 `patch_vscode_chat_enable.js`。
4. `IDE_PATCH_FILES` 至少需要包含：

```text
patch_all.js
patch_vscode_chat_enable.js
patch_vscode_branding.js
lib/codeServerResolver.js
```

5. 线上校验逻辑应检查新 patch marker：

```text
patched:force-models
patched:skip-unknown-check
patched:force-free
```

6. 线上校验逻辑还应检查 `product.json`：

```text
extensionAllowedProposedApi
defaultChatAgent
apaas-builder.ruijing-ai
```

## 修复后部署命令

只修复线上 IDE patch：

```bash
python3 scripts/deploy_cloud.py --ide-only --skip-build
```

如果随完整发布一起修复 IDE：

```bash
python3 scripts/deploy_cloud.py --include-ide
```

## 验收方式

部署后先确认公网后端健康：

```bash
curl -sS -o /dev/null -w 'health=%{http_code}\n' \
  https://agent.dfy.definesys.cn/ai-builder/api/health
```

应返回：

```text
health=200
```

然后抓线上 `workbench.js` 检查 marker。先从线上 IDE HTML 中找到实际 `workbench.js` 路径，再执行类似命令：

```bash
curl -L -sS 'https://agent.dfy.definesys.cn/ai-builder/ide/<actual-workbench-path>/workbench.js?v=<actual-cache-bust>' \
  | rg -o 'patched:force-models|patched:skip-unknown-check|patched:force-free|apaas-builder\.ruijing-ai' \
  | sort | uniq -c
```

应能看到：

```text
patched:force-models
patched:skip-unknown-check
patched:force-free
apaas-builder.ruijing-ai
```

最后强刷线上 IDE 页面，验证 Chat：

- Chat 面板应显示 `睿鲸AI` participant。
- 输入 `hello` 后应返回中文助手回复。
- 不应再只显示 VS Code 默认英文 Agent 空回复。

