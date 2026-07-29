# 桌面端 ACL 修复与 Windows 绿色版设计

**Spec ID**：`2026-07-29-desktop-acl-portable-windows`
**日期**：2026-07-29
**状态**：已确认，待实施计划
**工程**：`apaas-builder-ai`
**目标端**：Windows 桌面端

## 1. 背景与根因

当前 Windows 安装包启动后在前端首次调用 `desktop_get_state` 时报告：

```text
Command desktop_get_state not allowed by ACL
```

`src-tauri/src/lib.rs` 已注册全部桌面自定义命令，但
`src-tauri/capabilities/default.json` 只授权 Tauri core 和插件权限。业务页面由 sidecar
通过 `http://127.0.0.1:<port>/` 提供，属于 capability 中声明的 remote origin；没有应用
命令 permission 时，Tauri 2 ACL 会拒绝这些调用。因此该故障发生在前端初始化第一步，
不是登录、sidecar 或 Local Runtime Manager 的业务错误。

当前 Windows 构建脚本只支持 NSIS/MSI 安装包，不提供解压即运行的交付物。

## 2. 目标

1. 授权桌面前端实际使用的全部 `desktop_*` Tauri 命令，消除初始化 ACL 拒绝。
2. 增加 Windows 绿色 ZIP，用户解压后直接运行，不需要安装程序。
3. 绿色版继续使用 `%APPDATA%\com.ruijing.builder` 保存配置、日志和 Runtime 数据。
4. 先从解压目录真实启动并通过桌面启动烟测，再生成最终交付物。

## 3. 非目标

- 不修改登录模式、租户、工作台入口或本地应用交互。
- 不重构 sidecar、Local Runtime Manager 或现有目录模型。
- 不实现把用户数据写入绿色版目录的完全便携模式。
- 不移除 NSIS/MSI 能力，但本次只交付绿色 ZIP。
- 不增加分散的端到端测试工程或大批测试文件。

## 4. ACL 设计

在 `src-tauri/permissions/` 增加一个聚合应用 permission，明确允许当前
`tauri::generate_handler!` 注册的八个命令：

- `desktop_get_state`
- `desktop_save_setup`
- `desktop_test_service`
- `desktop_enter_login_setup`
- `desktop_retry_start`
- `desktop_update_login`
- `desktop_update_workspace_entry_scope`
- `desktop_open_path`

`src-tauri/capabilities/default.json` 只引用这一个 permission 标识。现有 remote URL 范围
保持为本机 loopback 地址，不扩大到外部站点。后续新增桌面命令时，必须同时加入聚合
permission；构建检查负责发现注册列表与授权列表不一致。

## 5. 绿色版布局

Windows 构建脚本增加 `portable` 输出模式。它复用现有前端、PyInstaller sidecar、
Runtime appliance 和 Tauri release 构建步骤，不再运行 NSIS/MSI bundler。

最终 ZIP 解压后结构为：

```text
Dolphin Code/
├── Dolphin Code.exe
├── ruijing-sidecar.exe
└── resources/
    └── agent-runtime/
        └── ...
```

主程序可从 Rust release 输出的 `app.exe` 重命名为 `Dolphin Code.exe`。sidecar 和
`resources/agent-runtime` 的相对位置必须与现有 Tauri 运行时查找逻辑一致。输出文件名为：

```text
ruijing-<version>-windows-x86_64-portable.zip
```

绿色目录不包含源码、构建缓存、Python 虚拟环境、安装器或重复 Runtime 副本。

## 6. 构建与错误处理

- 构建脚本在压缩前检查主程序、sidecar 和 Runtime 关键文件均存在。
- 任一必需文件缺失时构建失败，不产生看似成功的不完整 ZIP。
- 重新生成绿色目录前只删除该版本对应的输出目录，不清理用户数据或其他构建产物。
- ZIP 生成后输出文件大小和 SHA-256，便于确认用户运行的是最新包。

## 7. 验收

只保留与本次故障直接相关的检查：

1. ACL 清单覆盖 `generate_handler!` 中全部八个桌面命令。
2. 绿色目录包含主程序、sidecar 和 Runtime appliance 关键文件。
3. 在一个新的解压目录启动 `Dolphin Code.exe`，进程正常运行且不会再次报告
   `Command desktop_get_state not allowed by ACL`。
4. 主窗口越过 Tauri 初始化页，进入现有初始化、登录或业务页面流程。
5. sidecar 和 Local Runtime Manager 按现有配置启动；如果后续业务失败，日志必须保留
   精确错误，不能再被 ACL 初始化错误遮蔽。
6. 验收通过后才把绿色 ZIP 复制到 `dist-desktop/windows/` 作为交付物。
