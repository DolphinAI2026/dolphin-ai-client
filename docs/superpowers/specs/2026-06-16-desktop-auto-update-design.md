# 桌面端自动更新(Tauri updater)设计

> 日期:2026-06-16 · 状态:设计已确认,待写实现计划
> 关联:`docs/superpowers/specs/2026-06-16-account-service-design.md`(复用 account-service 托管 + 平台管理员鉴权)

## 1. 背景与目标

睿鲸 Builder 桌面端目前靠手动发 dmg 给每个人,改一次就要重新分发一遍。目标:做成 Claude/Codex 那样的**应用内自动更新** —— app 启动检测到新版本就提示用户,点一下后台下载、验签、原地替换、重启。从此发版只需开发者跑一条命令,用户自助升级。

**核心约束(已确认):**
- 方案 = **完整 Tauri updater**(应用内一键原地安装),不是"提示+跳下载"的轻量版。
- 托管在 **agent.dfy**,并入已部署的 account-service(同域、可控、不引入新基建)。
- 发版上传走**平台管理员鉴权的管理端点**(不用 kubectl cp 手动塞)。
- 检查时机 = **启动时自动检查 + 一个手动「检查更新」入口**;不加定时轮询。

## 2. 架构与数据流

```
发版(开发者本机):
  build(arm + x64,开启 updater 产物)
    → 用私钥签名,生成每架构的 .app.tar.gz + .sig
    → 拼 latest.json(两架构条目)
    → curl 上传到 account-service 管理端点(平台管理员 token)

升级(用户 app):
  启动 → 拉 latest.json → 版本比当前新?
    → Tauri 原生对话框「发现新版本 vX」→ 用户点更新
    → 下载对应架构 .app.tar.gz → 内嵌公钥验签
    → 原地替换 .app → 重启
```

托管 URL(account-service 经 ingress `/account-api`):
- manifest:`https://agent.dfy.definesys.cn/account-api/desktop-updates/latest.json`
- 包:`https://agent.dfy.definesys.cn/account-api/desktop-updates/{filename}`

## 3. 组件设计

### 3.1 App 端(Tauri + 前端)

**Rust 依赖(`src-tauri/Cargo.toml`):**
- `tauri-plugin-updater = "2"`
- `tauri-plugin-process = "2"`(更新后重启)

**插件注册(`src-tauri/src/lib.rs`):**
```rust
.plugin(tauri_plugin_updater::Builder::new().build())
.plugin(tauri_plugin_process::init())
```

**`src-tauri/tauri.conf.json`:**
```jsonc
"bundle": {
  "createUpdaterArtifacts": true   // 产出 .app.tar.gz + .sig
},
"plugins": {
  "updater": {
    "endpoints": ["https://agent.dfy.definesys.cn/account-api/desktop-updates/latest.json"],
    "pubkey": "<base64 公钥,由 tauri signer generate 生成>"
  }
}
```

**capability(`src-tauri/capabilities/default.json`)** 追加:
- `updater:default`
- `process:allow-restart`

**JS 依赖:** `@tauri-apps/plugin-updater`、`@tauri-apps/plugin-process`。

**检查逻辑(前端,仅 `__DESKTOP__`):** 新增 `frontend/src/utils/desktopUpdate.ts`
- `checkAndPromptUpdate(opts: { silentIfNone: boolean })`:
  - `const update = await check()`(plugin-updater)
  - 有新版 → Tauri 原生 `ask()` 对话框:「发现新版本 {version},是否现在更新?\n\n{notes}」
  - 用户确认 → `await update.downloadAndInstall()`(可带进度回调)→ `await relaunch()`(plugin-process)
  - 无新版:`silentIfNone=true` 时静默(启动检查用),`false` 时提示「已是最新版」(手动检查用)。
  - 出错:启动检查静默吞(不打扰),手动检查给可读提示。
- 启动时:app 根组件 `onMounted` 调一次 `checkAndPromptUpdate({ silentIfNone: true })`(仅 `__DESKTOP__`)。
- 手动入口:侧栏/设置区一个「检查更新」按钮 → `checkAndPromptUpdate({ silentIfNone: false })`。在线版不渲染该按钮。

### 3.2 服务端(并入 account-service)

新增 `backend/app/routes/desktop_updates.py`(一个 `APIRouter(prefix="/desktop-updates")`),**仅在 account-service 的 `main.py` 挂载**(`app.include_router(...)`);桌面 sidecar 是更新的消费方,不挂这个路由。两个 GET 端点**不鉴权**(更新产物是公开物,靠签名防篡改),只有 POST 上传需平台管理员。

- `GET /desktop-updates/latest.json` → 读 PVC 上的 `latest.json` 原样返回(`application/json`)。文件不存在 → 返回 404(updater 容忍 404 = 无更新)。
- `GET /desktop-updates/{filename}` → 下发 PVC 上的包文件(`FileResponse`)。**文件名白名单校验**(只允许 `^[\w.\-]+\.app\.tar\.gz$`,防路径穿越)。
- `POST /admin/desktop-updates`(**仅 `is_platform_admin`**)→ 发版上传:
  - multipart:`manifest`(latest.json 文本)+ 一个或多个包文件。
  - 原子落 PVC:先写临时文件再 rename,避免半截 manifest 被拉到。
  - 校验:manifest 是合法 JSON 且含 `version` + `platforms`;包文件名匹配白名单。
  - 返回写入的文件清单。

**存储:** account-service 的 PVC(MySQL 迁移后空出的那块),挂载到 `/data/desktop-updates`。Deployment 加 volumeMount。

**鉴权复用:** `POST /admin/desktop-updates` 用与 `desktop_auth.py` 现有 admin 端点相同的 `get_auth_context` + `ctx.user.is_platform_admin` 守卫。**前提:公网 account-service 上存在至少一个平台管理员账号**(管理后台用的那个);发版脚本用它登录拿 token。

### 3.3 发版脚本 `scripts/release-desktop.sh`

一条命令发版,参数:版本号 + 发布说明。
1. 读 `src-tauri/tauri.conf.json` 当前 `version`(或入参指定),校验比线上 manifest 新。
2. 设 `TAURI_SIGNING_PRIVATE_KEY` + `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`(从本机密钥文件 + 环境读)。
3. arm build(`build-desktop.sh` 等价)+ x64 build(`build-desktop-x86.sh` 等价),均开 `createUpdaterArtifacts`。
4. 收集每架构产物:`*.app.tar.gz` + `*.app.tar.gz.sig`。
5. 拼 `latest.json`(见 §4),`signature` 字段填 `.sig` 文件内容,`url` 指向 `/account-api/desktop-updates/{filename}`。
6. 平台管理员登录拿 token → `curl POST /account-api/admin/desktop-updates`(manifest + 两个包)。
7. 打印结果 + 校验线上 manifest 已更新。

私钥**不进脚本、不进仓库**;脚本从本机固定路径 + 环境变量读。

## 4. Manifest 格式(Tauri v2 静态 JSON)

```json
{
  "version": "0.2.0",
  "notes": "本次更新内容……",
  "pub_date": "2026-06-16T12:00:00Z",
  "platforms": {
    "darwin-aarch64": {
      "signature": "<.sig 文件内容>",
      "url": "https://agent.dfy.definesys.cn/account-api/desktop-updates/ruijing-builder-0.2.0-aarch64.app.tar.gz"
    },
    "darwin-x86_64": {
      "signature": "<.sig 文件内容>",
      "url": "https://agent.dfy.definesys.cn/account-api/desktop-updates/ruijing-builder-0.2.0-x86_64.app.tar.gz"
    }
  }
}
```

> `version` 用语义化版本;updater 按 semver 比较。`pub_date` 由发版脚本在本机生成后传入(脚本环境可用系统时间)。

## 5. 签名密钥管理(安全)

- `tauri signer generate -w <私钥路径>` 生成密钥对,私钥用密码加密。
- **私钥**(+ 密码)只存在构建机(大明哥本机),gitignore,**必须离线备份**(如密码管理器)。私钥丢失 = 无法再推被已装 app 接受的更新(已装 app 内嵌的是旧公钥),只能手动重发带新公钥的新包。
- **公钥**编进 `tauri.conf.json`(提交进仓库,公开无害)。
- 密钥**只签名,不参与传输**;服务端不持有私钥。

## 6. 首次落地的两个关键点

1. **updater 只对"内置 updater 的版本"生效。** 当前已安装的所有包(含刚修好的 openExternal 包)都没有 updater。因此:
   - **合体出最终包** = openExternal 修复 + updater,作为**最后一次手动分发**的包,发给所有人装上。
   - 从这版起所有后续更新自动。**一次手动,终身自动。**
   - (若需先救急,可先单独发 openExternal 包;代价是多一次手动安装。由用户定。)

2. **macOS Gatekeeper(无 Apple 公证):**
   - **首次安装**仍需右键打开绕过一次(无法避免,除非购买 Apple 开发者公证 + notarize)。
   - **自动更新反而更顺**:updater 原地替换的文件不带"浏览器下载"隔离标记(`com.apple.quarantine`),不会再触发 Gatekeeper。所以自动升级体验优于手动下 dmg。
   - Apple 公证为**未来可选增强**,不在本期范围。

## 7. 测试

- **服务端单测:** 上传端点权限(非平台管理员 403)、manifest 合法性校验、文件名白名单(路径穿越被拒)、latest.json/包下发 200、原子写。
- **端到端(本机):** 装当前 app → 起一个 version 调高的假 manifest + 真签名包 → 验证 app 能检测到、下载、验签通过、替换、重启进新版本;验签失败(改坏 signature)→ 拒绝安装。

## 8. 范围与分期

- **本期(P1):** updater 插件接线 + account-service 三个端点 + 发版脚本 + 合体最终包 + 端到端验证。
- **不做(YAGNI):** 定时轮询、灰度/分批发布、强制更新、回滚 UI、Apple 公证、Windows/Linux(当前只 macOS arm+x64)。
- **未来可选:** Apple 公证消除首装 Gatekeeper;发布说明富文本;更新进度条 UI。

## 9. 已锁定决策

| 决策点 | 选择 |
|---|---|
| 更新方式 | 完整 Tauri updater(应用内一键原地安装) |
| 托管 | agent.dfy / account-service,PVC 存文件 |
| 发版上传 | 平台管理员鉴权的 `POST /admin/desktop-updates` 端点 |
| 检查时机 | 启动自动 + 手动按钮,无轮询 |
| 平台 | macOS arm + x64 |
| 首发 | openExternal 修复 + updater 合体,最后一次手动分发 |
