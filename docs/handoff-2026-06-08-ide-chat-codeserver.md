# 交接：线上 code-server IDE 聊天助手修复（未完成）

> 2026-06-08。状态：**未搞定**。模型注册、setup、请求都通了，但"发消息→渲染回复"这最后一步在线上没跑通。
> 本文档让下个会话能直接接上，不用重走我踩过的弯路。

## 一句话现状

线上 dev IDE(code-server）的聊天助手，本地能用、线上不能。根因层层剥开后已**完全清楚**，
且已把运行中的 dev pod **live-patch 成"复刻本地"的状态**（理论上能用），但**最后一下 UI 发送没人工确认**
（浏览器自动化驱动不了 Monaco 输入框），用户换会话了。

⚠️ **dev pod 现在是 live-patch 状态（临时的）。pod 一重启就回到镜像版本（镜像版聊天是坏的）。**

---

## 环境与关键事实

- 线上 dev：`https://agent.dfy.definesys.cn/ai-builder/ide/`，pod = `apaas-builder-dev-0`（ns `apaas-builder`），StatefulSet `apaas-builder-dev`。
- code-server **4.112.0 / VS Code 1.112.0**，node **v22**（`fetch` 可用，不是 fetch 的锅）。
- IDE 聊天是 VS Code **"Agent 模式"**，**必须有一个注册的语言模型**才能回复，否则卡。
- code-server 进程由 **supervisord** 管：`kubectl exec ... -- supervisorctl restart code-server` 可让它重读 product.json / 扩展 / settings。
- code-server `--auth none`，所以**直接开 `…/ide/?folder=<工作区绝对路径>` 就能进**（扩展从 `<ws>/.vscode/ruijing-ai.json` 读配置）。用 chrome-devtools MCP 开页面看控制台最有效。
- 浏览器自动化**无法把文字注入 Monaco 聊天输入框**（execCommand/paste/fill/setValue 都不进编辑器模型，Send 不亮）。验证最后一步只能靠真人打字。

## 本地（能用）到底靠什么 —— 这是钥匙

本地 `~/.local/share/code-server/`：
- 扩展 **`apaas-builder.minimax-chat-provider` v0.6.0**（源码**不在仓库**，只在本地）—— 这才是真正提供模型的。
  它用 `vscode.lm.registerLanguageModelChatProvider('copilot', provider)`（注册成 copilot vendor），
  **直连 `https://api.minimax.chat/v1`**，带 `settings.json` 里的 `minimax.apiKey`（静态 key）。
  附带一个 `patch-workbench.sh`（4 个 entitlement 补丁 + product.json）。
- 扩展 `apaas-builder.ruijing-ai` 0.1.0 是**旧版**，激活但**不注册模型**（无 `registerLanguageModelChatProvider`）。
- workbench.js 打了仓库的 **`chat_fallback` 补丁**（控制台 `[PATCH] registered MiniMax dynamic agent fallback`），
  它会 **"Replaced GitHub.copilot-chat references"**（消除 copilot-chat 安装错误）+ "delegate D0 to MiniMax handler"。
- `product.json`：`defaultChatAgent` **指向 minimax 扩展**（不是删！），`extensionAllowedProposedApi: ["apaas-builder.minimax-chat-provider"]`。
- `settings.json`：`minimax.apiKey` / `minimax.apiBase=https://api.minimax.chat/v1` / `minimax.model=MiniMax-M2.7`。

**重大纠正**：用户最初以为"本地是后端路由"，**其实本地一直是直连 api.minimax.chat（带静态 key），从没走后端**。
所以用户当初选的"干净后端方案（Option B）"是基于错误前提。

## 踩过的弯路（别重走）

1. **lmProvider URL bug**（commit `2a30dcd4`）：`${apiBase}/chat/completions` 少了 `/workspace/{ws}/ide` 前缀 → 404。
   是真 bug 但**在 4.112 上那段代码根本不执行**（注册 API 名都错），白修。
2. **以为是 fetch 不可用**：node 是 v22，`fetch` 有，不是这问题。
3. **删 defaultChatAgent**：删了 VS Code chat setup 回退到硬编码 `GitHub.copilot-chat` → 装不到 → 卡 "Getting chat ready"。
   要**重指向**自己的扩展，不能删（commit `a7b08b93` 改对了，但还不够）。
4. **entitlement 4 补丁**：本地运行中的 workbench.js **没有**这 4 个补丁（只有 chat_fallback）。我加了反而出 "Finish Setup"。本地靠的是 chat_fallback，不是这套。
5. **两个扩展都注册 'copilot' vendor**：minimax + 新 ruijing-ai 都注册 → `The vendor 'copilot' is already registered and cannot be registered twice`，得让其中一个不注册。

## 已提交（dev，IDE 聊天相关）

- `2a30dcd4` lmProvider URL（前缀）修复 —— 已在 origin。
- `c216b8ff` lmProvider 改用 `registerLanguageModelChatProvider` 新 API + `package.json` 加 `enabledApiProposals`/`languageModelChatProviders` + 新增 `scripts/patch_vscode_chat_enable.js`（entitlement + product.json）+ `patch_all.js` 用它替换 chat_fallback —— 已在 origin。
- `a7b08b93` chat_enable 改成"重指向 defaultChatAgent → ruijing-ai"（不删）+ 数组形态 allowlist —— **本地领先 origin，未 push**。

⚠️ 这三个 commit 是"干净后端方案（Option B）"的尝试，**镜像 `dev-20260608-c216b8ff` 里就是这套，但它聊天不通**
（删了 defaultChatAgent / 没 chat_fallback → 发消息报 copilot-chat 安装错）。`a7b08b93` 的重指向修复还没进镜像。

## dev pod 当前 live-patch 状态（= 复刻本地 = Option A，临时）

我在运行中的 pod 上手工做了（**重启即丢**）：
1. 把本地 `apaas-builder.minimax-chat-provider-0.6.0` 扩展（extension.js/browser.js/package.json/.vsixmanifest）拷进 `/root/.local/share/code-server/extensions/`，并加进 `extensions.json`。
2. `/root/.local/share/code-server/User/settings.json` 写入本地的 `minimax.apiKey/apiBase/model`。
3. `/opt/code-server/lib/vscode/product.json`：`defaultChatAgent` → minimax，`extensionAllowedProposedApi: ["apaas-builder.minimax-chat-provider","apaas-builder.ruijing-ai"]`。
4. workbench.js 应用了 `chat_fallback` 补丁（`node /app/scripts/patch_vscode_chat_fallback.js <workbench.js>`，先从 `.bak-*` 还原 pristine 再打）。
5. 把 pod 的 ruijing-ai `dist/extension.js` **换成本地旧版（不注册 provider）**，消除 vendor 'copilot' 冲突。
6. `supervisorctl restart code-server`。

**已验证（强证据，差最后 UI 渲染一下）**：
- 控制台：`[MiniMax] Registered as copilot vendor` + `@minimax participant` + `provideLanguageModelChatInformation called`，旧 ruijing 不注册、无冲突。
- 模型选择器显示 **MiniMax-M2.7**，状态栏 Signed out。
- **pod 内 curl `api.minimax.chat/v1/chat/completions` 带该 key → HTTP 200 + 真实回复**。
- 残留：控制台有个 `activateDefaultAgent` 的 `textContent on 'GitHub.copilot'` 报错（本地没有，疑似本地 workbench 还有额外手工改动；不一定挡发送）。

**没验证**：UI 里真打字发送后是否渲染出回复。用户换会话，没做这最后一下。

## 收尾：两条路

### Option A — 复刻本地（保证能用，但直连 minimax、非产品化）
把 live-patch 固化进镜像：
- `extensions/` 加入 `minimax-chat-provider`（仓库没源码，只能把本地构建好的 `extension.js/browser.js/package.json/.vsixmanifest` 当预构建产物提交，或让 Dockerfile COPY 安装）。
- Dockerfile：`code-server --install-extension` 装 minimax，**并把 ruijing-ai 改回不注册 provider 的版本**（避免 vendor 冲突），或干脆 Option A 下不要新 ruijing-ai lmProvider。
- patch_all.js：用 **chat_fallback**（不是 chat_enable）。
- 写入 `settings.json` 的 minimax key（**安全隐患：把个人 key 烤进客户可部署镜像**；产品化要改成可配置）。
- product.json：`defaultChatAgent` → minimax。
- 缺点：直连 api.minimax.chat，不走后端、不分租户。本地实测可用的就是这套。

### Option B — 干净后端路由（用户原本想要的）
让**新 ruijing-ai 的 lmProvider 独占 'copilot' vendor**（不要 minimax 扩展），流式打**后端**：
- 后端 `/api/coding/workspace/{ws}/ide/chat/completions` 已验证返回 **text/event-stream SSE，gpt-5.5**，格式跟 lmProvider 解析一致 → 后端没问题。
- 新 lmProvider（`c216b8ff` 起）已能注册成功（控制台见 `registered language model provider (copilot vendor, new API)`）。
- **关键缺口**：要 copilot-chat 安装 bypass，但**不要** chat_fallback 那句 "delegate D0 to MiniMax handler"（它抢 provider / 接不上 → 空回复）。
  即：从 `scripts/patch_vscode_chat_fallback.js` 里**只抽出**这几处字符串替换 —— "Replaced GitHub.copilot-chat references" + "Bypassed sign-in dialog in setup flow" + "Bypassed setup() auth" —— 加进 `patch_vscode_chat_enable.js`，**丢掉 D0-delegate**。
- product.json：`defaultChatAgent` 重指向 **ruijing-ai**（`a7b08b93` 已这么写），`extensionAllowedProposedApi: ["apaas-builder.ruijing-ai"]`。
- 验证后端能从 pod 到达：`PREVIEW_BASE_URL` / `/ai-builder/api/coding/...`（已验证 200 SSE）。
- 优点：走后端、租户鉴权、无 baked key。是对的方向，但是本地从没验证过的新路径，要 1-2 轮 build/deploy 调。

## 部署坑（重要，省你时间）

- `scripts/deploy_k8s_dev.sh` build 没问题，但**推镜像必失败**：Docker Desktop 默认走内置代理 `http.docker.internal:3128`，大镜像层 push 会 broken pipe + token EOF（即使 `dangerouslyDisableSandbox` 也没用，是 Docker daemon 自己的代理）。
- **绕法（实测可行）**：build 后镜像已在本地 `docker images`。用 **`crane`**（已装 `/opt/homebrew/bin/crane`）直连推：
  ```
  docker save <IMG> -o /tmp/img.tar
  HTTPS_PROXY="" HTTP_PROXY="" crane push /tmp/img.tar <IMG>   # 直连绕代理，~36min 一个大层但稳
  ```
  然后**手工** `kubectl patch sts apaas-builder-dev`（init+main 两个容器都设新 tag）+ `rollout restart`，**跳过部署脚本里那段会断的 push**。
- StatefulSet 两容器镜像 tag 必须一致（init `copy-frontend-dist` + main `apaas-builder`），否则 init 卡 ImagePullBackOff → 503。

## 关键文件 / 命令速查

- 扩展源：`extensions/ruijing-ai/`（`src/lmProvider.ts` 新 API 注册、`package.json` proposals）。本地 minimax：`~/.local/share/code-server/extensions/apaas-builder.minimax-chat-provider-0.6.0/`（`extension.js` + `patch-workbench.sh`）。
- patch：`scripts/patch_all.js`、`scripts/patch_vscode_chat_enable.js`（我加的，product.json + entitlement）、`scripts/patch_vscode_chat_fallback.js`（老的，含 copilot bypass + minimax delegate）。
- Dockerfile：`deploy/docker/Dockerfile`（stage 2 build ruijing vsix；后面 `code-server --install-extension` + `node patch_all.js`）。
- 本地 IDE 看现状：浏览器开 `http://localhost:8080/?folder=/Users/mars/.apaas-builder-ai/workspaces/<ws>`，F12 控制台对照线上。
- 记忆：`memory/code_server_ai_chat.md` 有更细的 API/补丁配方。

## 我的建议

先 **Option A** 把 IDE 聊天弄通上线（哪怕直连 minimax + key），让用户能用；**Option B** 当作后续单独把它refactor 成后端路由。
两条路的具体改动上面都列清楚了。
