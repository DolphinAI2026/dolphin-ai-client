# DolphinAI 桌面品牌与 GitHub 正式发布设计

**Spec ID**: 2026-08-15-dolphin-ai-desktop-release

## 背景

当前桌面客户端的用户可见名称、Tauri 标识、sidecar 名称和发布产物仍混用
`Dolphin Code`、`睿鲸` 与 `ruijing`。Windows 已有本地打包脚本和手动 GitHub
Actions 工作流，但正式发布仍依赖人工选择版本、收集产物和整理下载地址，macOS、
Linux 也没有统一的公开更新出口。

本次将桌面产品作为全新应用发布，不迁移 `com.ruijing.builder` 的历史本地数据。

## 目标

1. 桌面产品的用户可见名称统一为 `DolphinAI`。
2. Tauri 应用标识改为 `com.definesys.dolphin-ai`。
3. sidecar 可执行文件及 Tauri 注册名改为 `dolphin-ai-sidecar`。
4. 设置中提供“关于 DolphinAI”弹窗，展示版本、构建提交和更新状态。
5. Git 标签是正式发布版本的唯一来源。
6. 推送 `vX.Y.Z` 标签后，私有源码仓库的 GitHub Actions 自动构建 Windows、macOS 和
   Linux 正式包，并发布到公开二进制仓库。
7. 发布完成后在工作流输出中返回 Release 页面及各平台下载直链。
8. 客户端 updater 只读取公开二进制仓库，安装包和更新清单不依赖用户登录 GitHub。

## 非目标

- 不迁移旧版 `com.ruijing.builder` 的配置、登录状态、本地模型或应用记录。
- 不修改登录、租户、Builder、Code、Runtime manager 或沙箱业务协议。
- 不在本次重命名 `.ruijing/PROJECT.md`、`ruijing-preview` 等已有工程或消息协议字段。
- 不把绿色 ZIP 作为正式 GitHub Release 的默认交付物。
- 不在仓库中保存代码签名证书、私钥、密码或平台账号。
- 不兼容或迁移旧 `ruijing` updater 密钥、旧安装包或旧自动更新渠道；旧用户通过一次手动安装迁移。

## 方案选择

### 方案 A：只修改显示名称

风险最低，但安装目录、数据目录、进程和发布文件仍保留旧品牌，不满足全新产品身份要求。
不采用。

### 方案 B：私有源码仓库构建，公开二进制仓库发布

同步修改用户可见品牌、Tauri identifier、sidecar、正式产物名和自动发布工作流。私有
`DolphinAI2026/dolphin-ai-client` 以标签驱动三个系统的构建，公开
`DolphinAI2026/dolphin-ai-releases` 只承载安装包、更新清单和下载地址。采用此方案。

### 方案 C：分别维护三个系统的发布流程

可以逐个平台调试，但版本、品牌、签名和下载地址容易漂移，后续维护成本高。不采用。

## 设计

### 1. 品牌与应用身份

统一使用以下值：

| 项目 | 值 |
| --- | --- |
| 产品显示名 | `DolphinAI` |
| Tauri identifier | `com.definesys.dolphin-ai` |
| sidecar 名称 | `dolphin-ai-sidecar` |
| 默认本地根目录名 | `DolphinAI` |
| 发布文件前缀 | `dolphin-ai` |

Tauri 配置、窗口标题、设置文案、安装包显示名、开始菜单项和卸载入口都使用
`DolphinAI`。Rust sidecar 启动、Tauri ACL、PyInstaller、Windows PowerShell 构建脚本、
Linux/macOS Shell 构建脚本及包门禁统一使用 `dolphin-ai-sidecar`。

旧版 identifier 不再作为数据回退来源。新客户端首次启动时按现有初始化流程创建新的配置。
历史目录不会自动删除，避免误删用户文件。

为降低无关回归，本次不批量改写协议字段、Python 模块名、测试 fixture 或项目内隐藏元数据；
只有安装身份、进程身份、产品文案和发布身份进入重命名范围。

### 2. 版本与关于弹窗

正式发布标签必须满足 `vX.Y.Z`，工作流去掉前缀后得到应用版本 `X.Y.Z`。构建脚本在构建期
将该版本写入 Tauri 配置，并继续由 Vite 注入 `__APP_VERSION__`。构建结束后恢复工作区配置，
避免一次构建污染源码。

新增独立的“关于 DolphinAI”弹窗，至少展示：

- `DolphinAI` 产品名；
- 当前版本 `vX.Y.Z`；
- 构建提交短 SHA；
- 当前系统与架构；
- 更新状态和“检查更新”操作。

设置页面的“关于与更新”作为弹窗入口。Web 预览可以查看版本，但更新按钮明确禁用；桌面客户端
继续调用现有 Tauri updater。检查失败只在弹窗内展示可理解的错误，不用系统级弹窗反复打扰。

### 3. 正式发布产物

GitHub Release 默认发布以下文件：

```text
dolphin-ai-X.Y.Z-windows-x86_64-setup.exe
dolphin-ai-X.Y.Z-windows-x86_64-updater.nsis.zip
dolphin-ai-X.Y.Z-windows-x86_64-updater.nsis.zip.sig
dolphin-ai-X.Y.Z-macos-aarch64.dmg
dolphin-ai-X.Y.Z-macos-aarch64-updater.app.tar.gz
dolphin-ai-X.Y.Z-macos-aarch64-updater.app.tar.gz.sig
dolphin-ai-X.Y.Z-linux-x86_64.AppImage
dolphin-ai-X.Y.Z-linux-x86_64.deb
dolphin-ai-X.Y.Z-linux-x86_64-updater.AppImage.tar.gz
dolphin-ai-X.Y.Z-linux-x86_64-updater.AppImage.tar.gz.sig
latest.json
SHA256SUMS.txt
```

Windows 使用 NSIS 安装包，提供标准安装、卸载和后续更新能力。绿色 ZIP 继续保留为手动调试
构建目标，但 GitHub 正式发布工作流不上传它。macOS 以 Apple Silicon DMG 为首个正式架构；
Linux 同时提供 AppImage 与 Deb。

所有产物必须通过现有 Runtime 资源门禁，并增加品牌门禁：正式发布目录不得包含旧主程序名、
旧 sidecar 文件名或 `ruijing-*` 发布文件名。

`latest.json` 中三端 URL 必须分别指向上表中的 updater 载荷；用户安装包、updater 载荷、
`.sig`、manifest 和 checksum 都是公开仓库的唯一附件 allowlist。发布后回读必须拒绝缺失、
重复或不在 allowlist 的同名附件。

### 4. 私有构建与公开发布流程

源码仓库 `DolphinAI2026/dolphin-ai-client` 保持私有，公开仓库
`DolphinAI2026/dolphin-ai-releases` 不提交业务源码，只创建 Release 和二进制附件。统一
桌面发布工作流在私有源码仓库中运行，触发方式为推送 `v*` 标签，也保留带版本参数的手动
执行入口用于发布排障。

公开仓库先初始化一个仅含 `README.md` 和 `.gitignore` 的 `main` 提交。公开 Release 的 tag
固定锚定该仓库 `main`，不引用私有源码 commit；Release body 记录不可变的
`source_repository`、`source_revision`、`updater_public_key_fingerprint` 和构建时间。公开仓库
不得包含 `frontend/`、`backend/`、`src-tauri/`、运行时资源或其他业务源码目录。初始化和每次发布
都检查该限制。

Tauri 配置中的 endpoint、manifest 生成的 repository、公开 Release 创建/回读 API 和工作流输出
全部固定使用 `DolphinAI2026/dolphin-ai-releases`。工作流只在创建、上传、校验、发布和回读公开
Release 的步骤注入 `RELEASES_GITHUB_TOKEN`；其他 job 只使用本仓库的只读 token。工作流包含以下阶段：

1. 校验标签格式并生成 `X.Y.Z`、Git SHA 和 Release 名称。
2. Windows runner 构建 NSIS 安装包并运行 Windows 包专项门禁。
3. macOS runner 构建 aarch64 DMG 并核对 app、sidecar 和 Runtime 资源。
4. Linux runner 构建 AppImage、Deb 并执行最终包内 Runtime 校验。
5. 汇总全部产物，生成 `SHA256SUMS.txt` 和 Tauri updater 使用的 `latest.json`。
6. 使用仅具备公开发布仓库 `Contents: write` 权限的跨仓库 Token，在公开仓库创建或更新同标签
   GitHub Release，上传全部正式产物。
7. 从公开仓库 GitHub Release API 回读实际附件 URL，输出 Release 页面和各平台下载地址。

私有源码仓库工作流使用最小权限：本仓库 `contents: read`，跨仓库 Token 仅允许公开发布仓库
`Contents: write`。推送 tag 时以该 tag commit 构建；手动 `publish=true` 只接受已存在的
`vX.Y.Z` tag，并校验版本、tag 和目标 commit 一致，绝不由工作流创建、推送或移动源码 tag。
依赖缓存只缓存 npm、Cargo 和构建工具，不缓存最终 Tauri resources 或 release 目录，防止旧包内容
混入新版本。

#### 发布状态与重试

推送正式 `vX.Y.Z` 标签时发布模式固定为 `publish`。手动入口新增 `publish` 布尔输入，默认
`false`：未打开时只构建和执行包/manifest 静态门禁，不创建源码标签、不写公开仓库、不触发 Release。
本次初始化只允许该 dry-run 验证；创建公开仓库、写入 Secrets 和更新源码配置不等于发布。

生产发布遵循以下不可跳过状态，并使用公开发布 job 级全局并发组串行化：

```text
absent -> draft -> assets_verified -> published_latest
```

1. 仅在公开仓库创建 draft Release；draft 对匿名 updater 不可见，上一公开 latest 保持不变。
2. 上传完整附件 allowlist 后，回读每个附件的名称、大小、SHA-256、manifest URL 和三端 `.sig`。
3. 使用 Tauri 配置中的新公钥验证三个 updater 载荷签名，并把公钥指纹与 source revision 写入 draft 元数据。
4. 在推进前回读当前公开 latest。候选版本必须严格高于 current latest；不满足时失败，避免较慢的旧
   tag 覆盖新版本。串行 job 中再次确认 latest 未变化后，单次将 draft 发布并设为 latest；任一步失败
   都不得推进 latest。

已发布的同一 tag 一律失败，要求使用新版本号，避免不同构建混用附件。已有 draft 只允许同一
`source_revision` 重试；工作流先删除该 draft 内的 expected allowlist 附件再重传，任一已存在
附件的 SHA-256 不一致时失败。上传/校验失败的 draft 保留给管理员排查或删除，公开 latest 不变。
人工回退通过在公开仓库将上一完整 Release 设置为 latest 后，再回读其 `latest.json` 和附件集合确认。

### 5. 签名和发布保护

Tauri updater 签名是正式标签发布的硬门槛。GitHub 仓库需要配置：

```text
TAURI_SIGNING_PRIVATE_KEY
TAURI_SIGNING_PRIVATE_KEY_PASSWORD
DEFINESYS_GIT_USERNAME
DEFINESYS_GIT_TOKEN
RELEASES_GITHUB_TOKEN
```

本次生成新的 DolphinAI updater 密钥对：私钥和密码只保存在私有源码仓库的 GitHub Secrets
及权限受限的离线备份中，公钥写入 Tauri 配置。旧 updater 私钥不参与迁移。缺少任一发布
必需 Secret 时，标签工作流直接失败，不创建不完整 Release。

`RELEASES_GITHUB_TOKEN` 必须是仅授权 `DolphinAI2026/dolphin-ai-releases` 的 fine-grained
Token，并只具有 `Contents: write`。初始化时记录新 updater 公钥指纹；metadata job 检查所有
必需 Secret 名称存在且非空，构建 job 在签名后验证“载荷 + .sig”能够被该公钥验证。任何密钥、
密码、Token 或私钥正文都不得进入 Job Summary、Release body、日志或源码。

Windows Authenticode 与 macOS Developer ID/公证不属于本次发布渠道初始化范围。正式包拥有
Tauri updater 签名，但在证书尚未配置前，Windows 可能显示 SmartScreen 提示，macOS 可能显示
Gatekeeper 提示。证书、私钥和密码不得写入日志、源码或发布产物。

### 6. 下载地址回传

公开 Release 上传完成后，工作流使用 GitHub API 回读附件列表，不根据文件名手工拼接未经验证的 URL。
结果写入 GitHub Actions Job Summary，并作为工作流输出保留：

```text
release_url
windows_setup_url
macos_dmg_url
linux_appimage_url
linux_deb_url
latest_json_url
checksums_url
```

发布执行者可以在工作流完成页直接复制地址；后续自动化也可以通过 GitHub API 或工作流输出读取。
任一必需附件缺失时 Release Job 失败，不输出“发布成功”。

### 7. 错误处理

- 标签不是合法 SemVer：构建前失败。
- 标签版本与生成包版本不一致：包门禁失败。
- 旧品牌文件残留：包门禁失败。
- Runtime、Builder 前端或 sidecar 缺失：对应平台构建失败。
- updater 签名或 `latest.json` 不完整：Release 创建前失败。
- 公开 Release 上传成功但回读不到必需附件：保持 draft，发布判定失败，上一 latest 保持不变。
- 新 tag 已存在且是 published Release：失败并要求新版本号；同 source revision 的 draft 可以重试。
- `RELEASES_GITHUB_TOKEN` 无权访问公开仓库：在 draft 创建前失败，不回退到源码仓库或旧仓库。
- 单个平台失败时不创建正式 Release，避免用户下载到不完整版本。

## 验证

### 静态专项检查

- Tauri 配置包含 `DolphinAI` 和 `com.definesys.dolphin-ai`。
- Tauri ACL、Rust 启动逻辑和构建脚本引用 `dolphin-ai-sidecar`。
- GitHub workflow 只在合法标签或显式 `publish=true` 的手动已有标签下发布；手动 dry-run 不创建 tag 或 Release。
- `tauri.conf.json`、manifest URL、Release API repository 和回读 repository 都是
  `DolphinAI2026/dolphin-ai-releases`，不得保留旧仓库地址。
- 正式产物名不包含 `ruijing` 或 `Dolphin Code`。

### 构建专项检查

- Windows NSIS 包通过现有 Runtime、Python、Codex、能力包和长路径门禁。
- macOS DMG 包含正确 app 名、sidecar 和 Runtime 资源。
- Linux AppImage 与 Deb 包含正确 app 名、sidecar、Codex 和 Builder 前端。
- 前端桌面构建显示正确版本，关于弹窗能执行检查更新。

### 发布检查

- 手动 dry-run 能完整构建并校验产物，但 GitHub API 记录中没有新增 tag、Release 或公开附件。
- 经过明确发布授权的测试标签在公开二进制仓库产生一个 draft Release，完整校验后才成为 latest。
- 公开 Release 包含完整附件 allowlist、SHA-256 和三端 updater 签名。
- Job Summary 中的下载链接可以直接访问对应附件。
- `latest.json` 的版本、URL 和签名与 Release 附件一致。

## 验收标准

1. 安装后系统显示的应用名、窗口名、开始菜单和卸载项均为 `DolphinAI`。
2. 运行进程为 `DolphinAI` 主程序和 `dolphin-ai-sidecar`。
3. 新版使用 `com.definesys.dolphin-ai`，且不读取旧版本地配置。
4. 关于弹窗展示真实版本和构建信息，并可检查更新。
5. 推送正式标签后，私有源码仓库自动生成三个系统的正式包，并在公开二进制仓库创建 Release。
6. 工作流完成页返回公开 Release 页面与各平台真实下载地址，未登录用户可读取 `latest.json`。
7. 首发前手动 dry-run 不创建或修改任何公开 Release；首发后任一失败不会替换上一版本的 latest。
