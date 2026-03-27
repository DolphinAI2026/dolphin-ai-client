# 交接文档 — aPaaS Builder AI / 睿鲸 AI Coding

> 更新时间: 2026-03-27
> 当前仓库: `/Users/mars/Vibe Coding/apaas-builder-ai`

## 本轮重点结论

这轮主要推进了两条线：

1. 低代码前端自开发链路
   - PC 组件、移动端组件、PC 页面、移动端页面的创建/构建/预览链路已补齐并做过实测。
   - 布局类已从错误的 `LAYOUT` 协议修正到 CLI 原生支持的 `PAGE_LAYOUT`。
   - 旧前端工作区已批量回填 `.cursor/rules` 默认规则。

2. code-server 二开成 Vibe IDE
   - Chat 面板已从“能显示但不能发”修到“能发消息、能读代码、能真实写文件”。
   - 默认语言已切到中文。
   - Welcome 页已开始品牌化为“睿鲸AI Coding”。

## 当前状态

### 1. 低代码前端自开发

- `PC 组件`: 可用，已实际跑通过。
- `移动端组件`: 可用，移动端预览壳已补上。
- `PC 页面`: 可用，页面产物目录和预览链路已修。
- `移动端页面`: 可用，移动端页面骨架和手机壳预览已补上。
- `布局`: 已改为 `PAGE_LAYOUT`，CLI 构建与预览已通。
- `列表视图`: 已按 `LIST_VIEW` 协议接通。
- `前端插件`: 已按 `FRONTEND_PLUGIN` 协议接通。
- `后端自开发`: 已改成 Maven/JDK 方向，但当前机器缺的不是代码，是得帆私服 Maven 凭据。

### 2. code-server / Vibe IDE

- Chat 视图已可见。
- AI 助手已能发送消息。
- AI 助手已能读取当前工作区代码。
- AI 助手已能真实写回文件，不再只是对话框建议。
- 默认语言已切为中文。
- Welcome 页品牌补丁已打入运行时。

## 本轮改动概览

### 仓库内代码

- `backend/app/coding/workspace.py`
  - 前端四类工作区、布局、列表视图、前端插件、后端自开发脚手架和构建逻辑整理。
  - 历史前端工作区默认规则回填能力。
- `backend/app/routes/coding.py`
  - 预览链路补充类型识别与更稳的页面/组件预览支持。
- `backend/app/coding/vibe_agent.py`
  - AI Coding SSE、thinking 展示和进度补充。
- `frontend/src/views/CodingPage.vue`
  - 预览区域、思路展示、步骤条、自动同步预览、配置属性预览等体验增强。
- `frontend/src/stores/coding.ts`
  - 类型补齐。
- `backend/app/coding/default_rules/前端SDK-v2介绍.mdc`
- `backend/app/coding/default_rules/自开发菜单页面开发指南.mdc`
- `scripts/patch_vscode_chat_fallback.js`
- `scripts/patch_vscode_chat_fallback.template.txt`
- `scripts/patch_vscode_locale.js`
- `scripts/patch_vscode_branding.js`

### 仓库外运行时文件

这些文件是直接改在本机 code-server/VS Code 运行时里的，升级 code-server 后可能需要重新打补丁：

- `/Users/mars/.local/lib/code-server-4.112.0/lib/vscode/out/vs/code/browser/workbench/workbench.js`
- `/Users/mars/.local/lib/code-server-4.112.0/lib/vscode/out/server-cli.js`
- `/Users/mars/.local/lib/code-server-4.112.0/lib/vscode/product.json`
- `/Users/mars/.local/share/code-server/User/settings.json`
- `/Users/mars/.local/share/code-server/User/locale.json`
- `/Users/mars/.local/share/code-server/languagepacks.json`
- `/Users/mars/.config/code-server/config.yaml`

## code-server 当前补丁说明

### 1. Chat 能力补丁

- 入口脚本:
  - `/Users/mars/Vibe Coding/apaas-builder-ai/scripts/patch_vscode_chat_fallback.js`
  - `/Users/mars/Vibe Coding/apaas-builder-ai/scripts/patch_vscode_chat_fallback.template.txt`
- 作用:
  - 避开默认 Copilot/GitHub 聊天激活失败。
  - 注入 MiniMax 动态兜底 agent。
  - 支持读取当前工作区。
  - 支持直接写文件到当前工作区。

### 2. 中文语言补丁

- 脚本:
  - `/Users/mars/Vibe Coding/apaas-builder-ai/scripts/patch_vscode_locale.js`
- 作用:
  - 修复 `server-cli.js` 启动时硬编码 `en` 的问题。
  - 生成 `languagepacks.json`。
  - 确保 `locale.json` 和 `config.yaml` 走 `zh-cn`。

### 3. Welcome 品牌补丁

- 脚本:
  - `/Users/mars/Vibe Coding/apaas-builder-ai/scripts/patch_vscode_branding.js`
- 作用:
  - 把产品显示名改成“睿鲸AI Coding”。
  - Welcome 页标题、副标题、右侧引导卡和快速上手文案改成内部品牌文案。

### 4. 启动行为修正

- 文件:
  - `/Users/mars/.local/share/code-server/User/settings.json`
- 关键设置:
  - `"workbench.startupEditor": "welcomePage"`
- 背景:
  - 出现过“不是挂了，而是落到了空白编辑器”的情况。
  - 现在默认固定打开 Welcome 页，避免误判为卡住。

## 已知问题

### 1. code-server 品牌页

- 主体品牌补丁已经打入。
- 少量第三方或 code-server 自带英文文案可能仍残留。
- 如果当前浏览器 tab 仍显示旧内容，通常是缓存/旧内存 bundle，强刷或重开 tab 即可。

### 2. AI 助手体验

- 现在已经能读写代码，但还不是 Cursor 那种完整的 diff 审阅体验。
- 目前没有“逐块 accept / reject patch”面板。

### 3. 后端自开发

- 脚手架和 Maven 构建逻辑已接通。
- 当前卡在得帆私有 Maven 仓库凭据，报 `401 Unauthorized`。
- 缺的不是代码，而是私服认证。

## 关键验证结果

- 低代码前端四类工作区的创建/构建/预览链路已做过真实 smoke test。
- 布局类已能按 `PAGE_LAYOUT` 构建和预览。
- Chat 已实测能创建并删除测试文件：
  - 在工作区 `1_7d9dba34` 根目录创建过 `ai-write-test.txt`
  - 后续已删除
- 中文语言已验证：
  - 资源管理器 / 搜索 / 源代码管理 / 运行和调试 / 扩展 已切中文

## 建议的后续工作

### P1

- 把 Welcome 页剩余英文文案继续品牌化
- 给 Chat 增加更像 Cursor 的交互：
  - 当前打开文件优先注入
  - 当前选中代码自动带入上下文
  - 修改时提供更清晰的 diff 反馈

### P2

- 统一工作区命名规则
  - 展示名使用中文/业务语义
  - 技术名使用英文短横线 slug
- 继续把前端自开发规则体系沉淀到默认模板

### P3

- 后端自开发接入真实 Maven 私服凭据，完成端到端 smoke test

## 常用操作

### 重打 code-server 聊天补丁

```bash
cd /Users/mars/Vibe\ Coding/apaas-builder-ai
node scripts/patch_vscode_chat_fallback.js
```

### 重打中文语言补丁

```bash
cd /Users/mars/Vibe\ Coding/apaas-builder-ai
node scripts/patch_vscode_locale.js
```

### 重打品牌补丁

```bash
cd /Users/mars/Vibe\ Coding/apaas-builder-ai
node scripts/patch_vscode_branding.js
```

### 重启 code-server

```bash
pkill -f '/Users/mars/.local/bin/code-server' || true
nohup /Users/mars/.local/bin/code-server > /tmp/code-server-zh.log 2>&1 &
```

## 备注

- 当前仓库是脏工作区，不要直接做大范围回滚。
- `workspaces/` 下有用户工作区与测试产物，谨慎处理。
- 本文覆盖的是 2026-03-27 这轮重点变更，老的环境管理交接内容已不再是本轮核心。
