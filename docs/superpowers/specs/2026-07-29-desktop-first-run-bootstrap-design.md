# 桌面端首次初始化与本地数据根目录设计

**Spec ID**：`2026-07-29-desktop-first-run-bootstrap`
**日期**：2026-07-29
**状态**：已确认，待实施计划
**工程**：`apaas-builder-ai`
**目标端**：Windows 桌面端优先，macOS/Linux 沿用同一配置模型

## 1. 背景

当前桌面端在 Tauri 启动阶段立即使用系统 AppData 启动 Local Runtime Manager 和
sidecar，等待 sidecar 健康后才创建主窗口。登录成功后，路由守卫又要求用户配置
aPaaS 环境和 LLM 模型。这个顺序带来以下问题：

1. 用户尚未选择本地数据目录，Runtime、SQLite、会话和工作区已经写入系统 AppData。
2. Runtime Manager 或 sidecar 启动失败时，主窗口可能无法创建，用户只能看到退出、
   命令行窗口或缺少恢复入口的错误。
3. 首次初始化发生在登录后，登录服务与本地存储配置没有统一入口。
4. 旧向导要求手工配置 aPaaS 和 LLM，但桌面端实际应由所选登录服务下发租户与模型。
5. 登录模式目前由 sidecar 启动环境变量固定，客户端界面无法在首次启动时选择。

本设计把首次初始化提升到登录和完整本地 Runtime 启动之前，并把用户可见应用与内部
运行数据放到一个明确的用户根目录下。

## 2. 与既有设计的关系

本设计延续
`2026-07-28-desktop-code-local-remote-application-experience-design.md` 的本地优先原则，
并替代其中“新建本地应用默认使用桌面应用数据目录”的默认位置：

- 新建本地应用默认放在 `<根目录>/applications/<应用编码>`。
- 导入已有应用仍可选择根目录之外的任意路径。
- 本设计不改变本地应用与远程应用的生命周期边界。

本设计不退役 sidecar 或 Local Runtime Manager。用户仍只启动一个桌面客户端；sidecar
与 Runtime Manager 是由 Tauri 静默管理的内部进程，不形成第二个用户安装或启动入口。

## 3. 已确认决策

1. 初始化向导与登录页分开。
2. 首次启动先保存登录服务和本地根目录，再进入登录页。
3. 向导采用两步结构，不增加欢迎页或单独完成页。
4. 登录模式显示四项：
   - `control_plane`，界面名称为“AI中台”，默认选中并可用。
   - `apaas`，界面名称为“aPaaS平台”，可用。
   - `public_account`，界面名称为“公开账号”，首版置灰。
   - `trial_account`，界面名称为“试用账号”，首版置灰。
5. AI中台默认地址为 `https://om-demo.dfy.definesys.cn`。
6. aPaaS平台默认地址为 `https://apaas-trial.definesys.cn/backend`。
7. 地址按模式预填并允许编辑；初始化不保存账号或密码。
8. aPaaS 租户在登录后由现有租户选择流程处理，初始化不填写租户 ID。
9. AI 模型由所选登录服务下发，初始化不配置模型地址、模型名或 API Key。
10. 用户选择一个本地数据根目录，应用与内部数据分别放入 `applications/` 和
    `.appdata/`。
11. 设置页可修改登录模式和地址；首版不实现根目录自动迁移。
12. 公开账号和试用账号首版只保留可见占位，不接认证协议、不保存候选地址。

## 4. 目标

- 首次启动在完整 sidecar 和 Runtime Manager 之前展示可恢复的初始化界面。
- 让用户明确选择登录服务和本地数据根目录。
- 后续启动可以在创建窗口前确定所有本地路径和 sidecar 环境变量。
- 消除因初始化顺序导致的登录循环、空白页、命令行弹窗和
  `LOCAL_RUNTIME_MANAGER_UNAVAILABLE`。
- 保持 Web 端现有线上登录、租户和数据目录行为不变。
- 保持用户只需安装和启动一个桌面客户端。

## 5. 非目标

- 不启用公开账号或试用账号登录。
- 不实现根目录之间的应用、数据库、缓存或 Runtime 数据迁移。
- 不把导入的外部应用强制移动到默认根目录。
- 不恢复旧的手工 LLM 初始化配置。
- 不重做登录页品牌视觉、租户选择流程或 Code 工作台。
- 不移除 Tauri 内部 sidecar 进程。

## 6. 目录与配置模型

### 6.1 用户根目录

默认根目录为当前用户主目录下的 `DolphinCode`：

```text
C:\Users\<用户名>\DolphinCode\
├── applications\
│   └── <应用编码>\
└── .appdata\
    ├── desktop-config.json
    ├── app.db
    ├── jwt_secret
    ├── encryption_key
    ├── runtime\
    ├── sessions\
    ├── cache\
    └── logs\
```

macOS 和 Linux 使用同样的 `$HOME/DolphinCode` 语义。用户可以通过原生目录选择器改为
其他绝对路径。

### 6.2 系统 AppData 引导指针

Tauri 的 `app_data_dir()` 仅保留一个小型 `bootstrap.json`：

```json
{
  "schema_version": 1,
  "root_dir": "C:\\Users\\Administrator\\DolphinCode"
}
```

该文件只解决“客户端下次启动时如何找到用户根目录”，不保存登录凭据、Runtime token、
会话或应用数据。

### 6.3 根目录配置

`<根目录>/.appdata/desktop-config.json` 是桌面初始化配置的事实源：

```json
{
  "schema_version": 1,
  "root_dir": "C:\\Users\\Administrator\\DolphinCode",
  "login": {
    "mode": "control_plane",
    "base_url": "https://om-demo.dfy.definesys.cn"
  }
}
```

约束：

- `root_dir` 必须是规范化绝对路径，并与配置文件所在根目录一致。
- `login.mode` 首版只接受 `control_plane` 或 `apaas`。
- `base_url` 只接受带 `http` 或 `https` scheme 的绝对 URL，不允许用户名、密码或
  fragment。
- 配置先写同目录临时文件，刷新并原子替换；根配置成功后才更新系统 AppData 指针。
- 任一步失败都不得留下指向半成品根目录的有效 `bootstrap.json`。

## 7. 首次初始化界面

### 7.1 第一步：登录服务

页面使用紧凑的四项选择列表：

- AI中台：可选，默认选中。
- aPaaS平台：可选。
- 公开账号：置灰，显示“暂未开放”。
- 试用账号：置灰，显示“暂未开放”。

选择可用模式后显示一个“服务地址”输入框。切换模式时填入对应默认地址；用户已编辑
当前模式地址后，不因失焦或其他普通交互覆盖输入。

“测试连接”是可选操作。下一步只阻塞非法 URL，不因临时断网阻塞初始化。网络问题在
测试连接和后续登录时显示明确错误。

### 7.2 第二步：本地存储

页面显示：

- 根目录输入框，预填平台默认值。
- 文件夹按钮，调用 Tauri 原生目录选择器。
- 只读目录预览：`applications/` 和 `.appdata/`。
- 返回上一步和“保存并进入登录”操作。

提交前检查：

- 路径为绝对路径。
- 根目录可创建或已存在。
- 可以在根目录创建、写入并删除一个临时探测文件。
- `applications/` 和 `.appdata/` 可创建。
- 目标不是普通文件，也不是无法访问的目录。

目录探测不扫描、移动或删除已有应用。

### 7.3 保存后的状态

用户点击“保存并进入登录”后，按钮进入单一启动状态，依次显示：

1. 保存配置。
2. 启动本地环境。
3. 打开登录页。

这是第二步内的短暂状态，不创建第三个完成页面，不弹出额外确认框。

## 8. Tauri 启动状态机

```text
应用启动
  |
  v
读取 AppData/bootstrap.json
  |-- 不存在 ----------------------> packaged setup WebView
  |-- 无效/根目录不可用 -----------> setup repair WebView
  '-- 有效
        |
        v
读取 <root>/.appdata/desktop-config.json
        |-- 无效 -------------------> setup repair WebView
        '-- 有效
              |
              v
启动 Local Runtime Manager
              |
              v
启动 sidecar 并等待健康
              |-- 失败 ------------> in-app recovery view
              '-- 成功 ------------> sidecar WebView / 登录页
```

首次初始化时，Tauri 使用 `frontend/dist-desktop` 中的内置前端创建 setup WebView。该页面
只调用 Tauri 命令完成配置读取、目录选择和保存，不依赖 sidecar API。配置保存成功后，
Tauri 在同一应用进程中启动 Runtime Manager 和 sidecar；健康后把主窗口导航到稳定的
sidecar origin。

后续启动不先打开登录页再重定向向导，而是在创建业务 WebView 前完成配置和本地进程
决议。

## 9. sidecar 与 Runtime 参数映射

Tauri 以 `<根目录>/.appdata` 作为桌面数据目录：

- `--data-dir=<根目录>/.appdata`
- `DOLPHIN_DESKTOP_DATA_DIR=<根目录>/.appdata`
- `SIDECAR_DATA_DIR=<根目录>/.appdata`
- `APAAS_WORKSPACE_ROOT=<根目录>/applications`
- Local Runtime Manager 数据目录为 `<根目录>/.appdata/runtime`

AI中台模式：

```text
AUTH_PROVIDER=control_plane
DOLPHIN_WORKSPACE_BASE_URL=<login.base_url>
PUBLIC_ACCOUNT_BASE_URL=
```

aPaaS平台模式：

```text
AUTH_PROVIDER=apaas
APAAS_BASE_URL=<login.base_url>
PUBLIC_ACCOUNT_BASE_URL=
```

Runtime Manager 必须先成功启动并返回 URL/token，sidecar 才能启动。Tauri 保存并持有两个
生命周期对象：进程内的 Runtime Manager server state，以及 sidecar child handle。退出时
先关闭 Runtime Manager 管理的本地实例和 server，再终止 sidecar。Windows 下 sidecar 和
Runtime 子进程都使用无控制台窗口启动标志。

## 10. 登录页与设置页

登录页只包含账号、密码和服务端按需返回的验证码。标题区域补充当前服务摘要，例如：

```text
AI中台 · om-demo.dfy.definesys.cn
```

登录页提供“更改登录服务”入口。该入口只返回初始化第一步，保留已选根目录，不要求用户
再次选择目录。Tauri 必须先把窗口导航到 packaged setup WebView，再停止旧 sidecar；保存
新服务后清理现有认证候选状态，重启 sidecar 并返回登录页，过程中不能暴露失效的
sidecar 页面或空白窗口。

登录后的设置页增加桌面环境区域：

- 查看并修改登录模式和服务地址。
- 查看本地数据根目录。
- 打开根目录或日志目录。
- 首版不提供“自动迁移根目录”。

修改登录模式或地址后必须退出当前登录并重启 sidecar，不能在旧身份会话中热切换认证
事实源。Local Runtime Manager 使用的根目录未变化，因此不随登录服务修改而重启。

## 11. 失败恢复与诊断

初始化与启动错误在应用窗口内显示，不能直接退出、循环刷新或弹出命令行窗口。

稳定诊断至少包括：

| 错误码 | 含义 | 用户操作 |
| --- | --- | --- |
| `DESKTOP_SETUP_ROOT_REQUIRED` | 未选择根目录 | 选择目录 |
| `DESKTOP_SETUP_ROOT_UNWRITABLE` | 根目录不可创建或不可写 | 更换目录、重试 |
| `DESKTOP_SETUP_CONFIG_INVALID` | 引导指针或根配置无效 | 修复初始化 |
| `DESKTOP_SETUP_RUNTIME_START_FAILED` | Runtime Manager 启动失败 | 重试、打开日志、重新选择目录 |
| `DESKTOP_SETUP_SIDECAR_START_FAILED` | sidecar 启动或健康检查失败 | 重试、打开日志 |

规则：

- 初始化未完成时不得把 Runtime 启动失败折叠为
  `LOCAL_RUNTIME_MANAGER_UNAVAILABLE`。
- sidecar 未就绪时不进入登录路由，避免登录页循环请求不可用后端。
- 根目录临时不可用时不删除配置或旧数据，用户可以重新挂载目录后重试。
- “重新选择目录”只切换到新根目录，不自动删除或搬动旧根目录内容。
- 日志不得输出账号密码、token、加密密钥或完整认证响应。

## 12. 兼容与迁移

已有桌面安装可能已经在系统 AppData 中包含 `app.db`、密钥、Runtime 数据和本地应用。
首版升级不得自动移动或删除这些内容。

兼容策略：

1. 没有 `bootstrap.json` 时一律进入新初始化向导。
2. 新向导不把旧系统 AppData 路径伪装成用户根目录，也不自动导入旧数据库或应用。
3. 选择新根目录后，旧系统 AppData 内容保持原状，不被扫描、移动或删除。
4. 后续如需要旧数据导入或根目录迁移，另写独立规格，包含复制、文件数量、逻辑字节数和 SHA-256
   校验，再决定是否删除源数据。

## 13. 实现边界

预计修改范围：

- `src-tauri/src/`：桌面配置模型、Tauri 命令、启动状态机、进程生命周期和错误投影。
- `backend/desktop_sidecar.py`：从 Tauri 注入的登录与目录参数构造环境。
- `frontend/src/views/DesktopSetupWizard.vue`：替换旧 aPaaS/LLM 登录后向导。
- `frontend/src/router/`：初始化路由前移到登录和业务守卫之前。
- `frontend/src/views/Login.vue`：显示当前服务和更改服务入口。
- 桌面设置界面：登录服务修改和目录只读展示。

不新增独立部署程序，不引入新的数据库迁移框架，不重写现有认证实现。

## 14. 验证策略

验证保持精简，不增加大批测试文件：

- Rust：覆盖配置解析、路径推导、原子保存和启动状态转换。
- 前端：覆盖四种模式的启用状态、两步切换和目录字段规则。
- Python：覆盖 Tauri 配置到 sidecar 环境变量的映射。
- 构建 Windows 桌面安装包，确认用户只需启动一个客户端入口。

不为每个错误文案建立独立测试文件；相近状态放入同一现有测试模块或少量聚焦测试中。

## 15. 验收标准

- 全新安装首次启动直接显示两步初始化向导，不先显示登录页或空白页。
- AI中台默认选中，aPaaS平台可选；公开账号和试用账号可见但不可操作。
- 初始化不要求账号、密码、租户 ID、模型地址、模型名或 API Key。
- 用户可以选择本地根目录，并看到 `applications/` 与 `.appdata/` 目录预览。
- 保存成功后静默启动 Runtime Manager 和 sidecar，再进入登录页。
- Windows 不弹出 sidecar 或 Runtime 命令行窗口。
- 登录页显示当前服务，验证码只在服务端要求时出现。
- aPaaS 登录后继续使用现有租户选择流程。
- 新建本地应用默认位于 `<根目录>/applications/<应用编码>`。
- Runtime、SQLite、会话、缓存和日志位于 `<根目录>/.appdata/`。
- 配置损坏、目录不可写或进程启动失败时，应用窗口内提供可操作的恢复入口。
- 首次初始化过程不再出现登录循环、固定超时空白页或无上下文的
  `LOCAL_RUNTIME_MANAGER_UNAVAILABLE`。
- Web 构建和远程租户登录行为不受影响。
