# AI Coding 托管构建故障分析与上线排障手册

> 更新时间: 2026-04-05
> 适用范围: AI Coding 模块内由服务端托管执行的 `npm install` / `npm run build`

## 1. 背景

AI Coding 中模型执行的命令并不是直接在 IDE 终端里跑。

当模型调用：

- `npm install`
- `npm run build`
- `npm install && npm run build`

后端会在 `backend/app/coding/tools.py` 中拦截这些命令，再转到：

- `WorkspaceManager.install_deps()`
- `WorkspaceManager.build_project()`

也就是说，IDE 终端能跑通，不代表 AI Coding 托管构建一定能跑通；两者依赖的进程环境可能不同。

## 2. 本次问题现象

在多个 workspace 的 AI Coding 回放中，模型声称执行了构建，但最终没有生成可用产物，或者直接报错退出。

典型表现：

- `Error: [Errno 2] No such file or directory`
- `/bin/sh: npm: command not found`
- 构建步骤在“依赖安装开始”后立即失败

关键证据：

- `workspaces/form-page-data-table__1_75248129/.vscode/chat-replay.json`
  - 先显示“已切换为兼容构建流程”，随后立刻报 `[Errno 2] No such file or directory`
- `workspaces/form-component-star-rating__1_2a55efef/.vscode/chat-replay.json`
  - `npm install` 后立刻出错
  - 随后直接出现 `/bin/sh: npm: command not found`

这说明失败点发生在“启动 npm 子进程”之前或之时，而不是打包产物拷贝阶段。

## 3. 根因结论

### 3.1 主根因

AI Coding 托管构建依赖后端服务进程自身的 PATH。

旧逻辑只额外假设：

- `/usr/local/bin`
- `~/.npm-global/bin`

如果线上机器的 Node.js / npm / df-apaas-cli 实际安装在以下任一位置，就可能触发故障：

- `/opt/homebrew/bin`
- `~/.nvm/versions/node/*/bin`
- `~/.fnm/node-versions/*/installation/bin`
- `~/.volta/bin`
- `~/.asdf/shims`

结果就是：

1. 终端里 `npm` 可用
2. 但后端托管子进程里 `npm` 不可用
3. `create_subprocess_exec("npm", ...)` 直接抛 `FileNotFoundError`
4. AI Coding 展示为 `[Errno 2] No such file or directory`

### 3.2 为什么会和人工终端表现不一致

因为线上服务通常由：

- `systemd`
- `supervisor`
- 容器入口脚本
- CI/CD 启动脚本

拉起，这些环境的 PATH 往往比人工登录 shell 更短，不会自动加载 `.zshrc` / `.bashrc` / nvm 初始化脚本。

## 4. 影响范围

受影响的是 AI Coding 的托管执行链路，不仅仅是某一个 workspace：

- `backend/app/coding/tools.py`
- `backend/app/coding/workspace.py`

具体受影响的能力：

- 托管 `npm install`
- 托管 `npm run build`
- 托管 `df-apaas-cli` 自动安装
- 托管构建前的 registry 解析

不直接受影响的能力：

- 用户自己在终端里手工执行 `npm run build`
- 已经存在构建产物的 workspace 预览

## 5. 本次代码修复

### 5.1 新增统一运行时探测

新增文件：

- `backend/app/coding/runtime_env.py`

职责：

- 探测常见 Node.js 二进制目录
- 统一补全 PATH
- 统一解析 `npm` / `node` / `df-apaas-cli`

当前覆盖：

- `/usr/local/bin`
- `/opt/homebrew/bin`
- `~/.npm-global/bin`
- `~/.volta/bin`
- `~/.asdf/shims`
- `~/.local/share/pnpm`
- `~/.nvm/versions/node/*/bin`
- `~/.fnm/node-versions/*/installation/bin`

### 5.2 接入点

已接入：

- `backend/app/coding/workspace.py`
  - `_resolve_default_npm_registry()`
  - `_build_npm_env()`
  - `_ensure_df_apaas_cli()`
  - `_install_cache_miss()`
  - `_run_build_process()`
- `backend/app/coding/tools.py`
  - `_resolve_default_npm_registry()`
  - `_build_command_env()`

### 5.3 行为改进

修复后：

- 不再只依赖 `/usr/local/bin`
- 服务端即使在精简 PATH 下也能补回 Node 工具链
- 如果仍然找不到 `npm`，会返回明确错误：
  - `未检测到 npm，请检查 Node.js 安装或后端服务 PATH 配置`

这比之前的 `[Errno 2] No such file or directory` 更容易定位。

## 6. 上线前检查清单

部署到线上前，至少检查以下几项。

### 6.1 Node 工具链

在服务运行用户下确认：

```bash
which node
which npm
which df-apaas-cli
node -v
npm -v
df-apaas-cli --version
```

期望：

- 三个命令都有路径
- `node` / `npm` 版本可正常输出

### 6.2 私有 registry

确认服务用户下：

```bash
npm config get registry
```

期望输出为公司私有源，或由环境变量显式指定：

- `APAAS_NPM_REGISTRY`
- `npm_config_registry`
- `NPM_CONFIG_REGISTRY`

### 6.3 后端服务环境

如果线上通过 systemd / supervisor 启动，必须确认服务环境变量中 PATH 不会丢失 Node 安装目录。

虽然本次代码已做运行时探测，但仍建议在服务配置中显式加 PATH，避免后续第三方命令继续踩坑。

### 6.4 目录权限

确认服务用户可写：

- workspace 根目录
- `.dependency-cache`
- `.npm-cache`

否则会在安装依赖阶段出现另一类失败。

## 7. 上线后验证步骤

建议上线后用一个最小前端 workspace 做一次真实回归。

推荐验证链路：

1. 创建一个最小 `FORM_COMPONENT` 或 `MENU_PAGE` workspace
2. 在 AI Coding 面板里让模型执行 `npm install && npm run build`
3. 确认回放里出现：
   - `依赖安装完成`
   - `构建成功`
4. 确认 workspace 中出现产物目录或 zip
5. 走一次预览或下载构建产物

## 8. 如果线上再次出现“没有产物”

先按下面顺序判断，不要一上来就怀疑模板有问题。

### 8.1 先看回放里是不是 PATH / npm 问题

重点搜：

- `npm: command not found`
- `[Errno 2] No such file or directory`
- `未检测到 npm`

如果命中，优先看服务环境。

### 8.2 再看是不是 registry / 私包问题

重点搜：

- `@x-apaas/df-apaas-cli ... Not found`
- `404 Not Found`

这通常是 registry 没指到得帆私源，或者 `.npmrc` / 环境变量没生效。

### 8.3 最后再看是不是源码真实编译失败

重点搜：

- `Module not found`
- `Failed to compile`
- `eslint`

这种才是前端代码本身的问题。

## 9. 这次事件的经验结论

1. AI Coding 的托管执行环境不能等同于人工终端环境。
2. 任何依赖 Node 工具链的服务端子进程，都不应写死单一安装路径。
3. 线上部署时，Node PATH、registry、缓存目录权限要和数据库、JWT、LLM 配置一样当成一等配置项。
4. 对外展示的报错信息必须可操作，不能只暴露 `[Errno 2]` 这种底层异常。

## 10. 关联代码

- `backend/app/coding/runtime_env.py`
- `backend/app/coding/workspace.py`
- `backend/app/coding/tools.py`

## 11. 关联案例

- `workspaces/form-page-data-table__1_75248129/.vscode/chat-replay.json`
- `workspaces/form-component-star-rating__1_2a55efef/.vscode/chat-replay.json`

如果线上再次出现 AI Coding 构建无产物，可优先按本文的第 8 节排查。
