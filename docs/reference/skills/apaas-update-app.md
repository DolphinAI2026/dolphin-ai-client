# aPaaS Update Application

## 用途
修改已有应用的基础信息（名称、描述、图标等）

## 流程
修改应用信息需要**两步操作**：先查询完整应用数据，修改后回写。不能只传部分字段，否则其他字段会被清空。

```
1. GET  /apaasApplications/queryAppById?id={appId}   → 获取完整应用数据
2. POST /apaasApplications/saveApp                    → 修改字段后回写
```

## API 端点

### 步骤 1: 查询应用详情
```
GET /xdap-app/apaasApplications/queryAppById
```

### 步骤 2: 保存应用信息
```
POST /xdap-app/apaasApplications/saveApp
```

## 请求头
```json
{
  "Content-Type": "application/json",
  "xdaptenantid": "<tenant_id>",
  "xdaptimestamp": "<millisecond_timestamp>",
  "xdaptoken": "<auth_token>"
}
```

## 步骤 1: 查询应用详情

### 请求参数
| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|------|------|
| id | query | string | 是 | 应用 ID |

### 响应格式
```json
{
  "code": "ok",
  "message": "操作成功",
  "data": {
    "owner": "100304959793993351168",
    "createdBy": "100304959793993351168",
    "lastUpdatedBy": "100169876816012509184",
    "creationDate": "2025-09-15 17:47:08",
    "lastUpdateDate": "2026-03-15 17:23:00",
    "objectVersionNumber": 10,
    "tenantId": "743906758237356033",
    "id": "755484864311984128",
    "appCode": "uss",
    "appName": "AI场景演示",
    "appKey": "e7ab8a5c-d1d9-42cc-b032-1154b09e1aa8",
    "appSecret": "7dad8442-e63e-4667-be23-6a3c75306341",
    "status": "RUNNING",
    "createName": "陈明",
    "currentVersion": "1.0.1",
    "appTheme": "#027AFF",
    "port": 31212,
    "accessUrl": "https://apaas-poc.definesys.cn/app/ai-live/uss/",
    "backendUrl": "https://apaas-poc.definesys.cn/apaas/backend/ai-live/uss",
    "accessMobileUrl": "https://apaas-poc.definesys.cn/m/ai-live/uss/",
    "customIconStatus": "DISABLE",
    "innerIcon": "userInfo",
    "customThemeButton": "DISABLE",
    "customThemeColor": "#027AFF",
    "customBackgroundStatus": "ENABLE",
    "customBackground": "https://...downloadFile?file=...",
    "modalDefaultStyle": "small",
    "drawerDefaultStyle": "small",
    "homePageDisplayPc": "FIRST_MENU",
    "homePageDisplayMobile": "MENU_HOME_PAGE",
    "mobileNavBarStatus": false,
    "appAdmins": [],
    "remarks": null,
    "saveStatus": true,
    "jobStatus": "ENABLE",
    "domainTypes": "custom",
    "oauthScope": "user_info",
    "oauthRedirectUrl": "https://...callback/oauth/app/index.html",
    "appNameI18nAssociated": false,
    "remarksI18nAssociated": false
  }
}
```

## 步骤 2: 保存应用信息

### 请求格式
将步骤 1 返回的完整 `data` 对象修改目标字段后，作为请求体 POST 回去。

## 全部字段说明

### 可修改字段 — 基础信息

| 字段 | 类型 | 界面位置 | 说明 | 示例值 |
|------|------|---------|------|--------|
| `appName` | string | 应用名称 | 应用显示名称 | `"AI场景演示"` |
| `remarks` | string | 备注 | 应用描述文本 | `"这是一个演示应用"` |
| `appAdmins` | string[] | 应用管理员 | 管理员用户 ID 数组 | `["100169876816012509184"]` |

### 可修改字段 — 应用主题

| 字段 | 类型 | 界面位置 | 说明 | 可选值 |
|------|------|---------|------|--------|
| `customThemeButton` | string | 开启自定义主题（开关） | 是否启用自定义主题色 | `"ENABLE"` / `"DISABLE"` |
| `appTheme` | string | 主题色选择 | 预设主题色（关闭自定义时生效） | 见下方预设色表 |
| `customThemeColor` | string | 自定义主题色 | 开启自定义主题后的颜色选择器 | 任意颜色值如 `"#FF5733"` |

#### 预设主题色（9 种，`customThemeButton = "DISABLE"` 时使用 `appTheme`）
| 颜色 | 值 | 说明 |
|------|------|------|
| 白/默认 | `"#FFFFFF"` 或默认 | 第一个（带 ✓） |
| 蓝 | `"#027AFF"` | 默认蓝色 |
| 粉红 | `"#E94560"` | |
| 绿 | `"#49CC90"` | |
| 黄 | `"#FADB14"` | |
| 橙 | `"#FCA130"` | |
| 紫 | `"#9B59B6"` | |
| 棕 | `"#8B6914"` | |
| 深蓝 | `"#1A1A2E"` | |

#### 交互行为
- `customThemeButton = "DISABLE"`：显示 9 个预设色块供选择，值存入 `appTheme`
- `customThemeButton = "ENABLE"`：预设色块隐藏，显示颜色选择器，值存入 `customThemeColor`

### 可修改字段 — 应用图标

| 字段 | 类型 | 界面位置 | 说明 | 可选值 |
|------|------|---------|------|--------|
| `customIconStatus` | string | 开启自定义图标（开关） | 是否使用自定义上传图标 | `"ENABLE"` / `"DISABLE"` |
| `innerIcon` | string | 内置图标选择 | 关闭自定义时，从 48 个预置图标中选择 | `"userInfo"` 等图标标识符 |
| `appIcon` | string | 应用图标 | 开启自定义后的上传图标 URL | 图片 URL |
| `smallIcon` | string | 缩略图 | 开启自定义后的缩略图 URL | 图片 URL |
| `phoneIcon` | string | 移动端图标 | 开启自定义后的移动端图标 URL | 图片 URL |

#### 交互行为
- `customIconStatus = "DISABLE"`：显示 48 个内置图标网格（6行 × 8列），选中的图标标识符存入 `innerIcon`
- `customIconStatus = "ENABLE"`：内置图标网格隐藏，显示 3 个上传区域（应用图标、缩略图、移动端图标），URL 分别存入 `appIcon`、`smallIcon`、`phoneIcon`

### 可修改字段 — 应用登录页

| 字段 | 类型 | 界面位置 | 说明 | 可选值 |
|------|------|---------|------|--------|
| `customBackgroundStatus` | string | 是否开启自定义背景 | 登录页背景图开关 | `"ENABLE"` / `"DISABLE"` |
| `customBackground` | string | 自定义背景图 | 登录页背景图 URL，开启后显示预览和更换按钮 | 图片 URL |

#### 交互行为
- `customBackgroundStatus = "ENABLE"`：显示背景图预览，可点击"预览"查看效果
- `customBackgroundStatus = "DISABLE"`：使用系统默认登录页背景

### 可修改字段 — 弹窗/抽屉样式

| 字段 | 类型 | 界面位置 | 说明 | 可选值 |
|------|------|---------|------|--------|
| `modalDefaultStyle` | string | 弹窗默认样式 | 表单弹窗大小（单选按钮） | `"small"`（正常）/ `"large"`（全屏） |
| `drawerDefaultStyle` | string | 抽屉默认样式 | 表单抽屉大小（单选按钮） | `"small"`（正常）/ `"large"`（全屏） |

### 可修改字段 — 应用首页

| 字段 | 类型 | 界面位置 | 说明 | 可选值 |
|------|------|---------|------|--------|
| `homePageDisplayPc` | string | 电脑端首页（下拉选择） | PC 端打开应用时的默认页面 | 见下方选项表 |
| `homePageDisplayMobile` | string | 移动端首页（下拉选择） | 移动端打开应用时的默认页面 | 见下方选项表 |
| `mobileNavBarStatus` | boolean | 启动移动端导航栏（开关） | 移动端底部导航栏是否显示 | `true` / `false` |

#### 电脑端首页选项（`homePageDisplayPc`）
| 值 | 显示名称 |
|------|------|
| `"FIRST_MENU"` | 第一个菜单 |
| 其他值 | 我的待办、我的待阅、我发起的、我的已办、流程待办管理、流程授权、流程转办、异步任务管理，以及应用内已创建的表单菜单 |

#### 移动端首页选项（`homePageDisplayMobile`）
| 值 | 显示名称 |
|------|------|
| `"MENU_HOME_PAGE"` | 菜单页面 |
| 其他值 | 与电脑端类似（我的待办、我的待阅等），但第一项为"菜单页面"而非"第一个菜单" |

### 只读字段 — 访问地址（系统自动生成）

| 字段 | 类型 | 界面位置 | 说明 |
|------|------|---------|------|
| `accessUrl` | string | 电脑端访问地址 | 系统生成，不要修改 |
| `accessMobileUrl` | string | 移动端访问地址 | 系统生成，不要修改 |
| `backendUrl` | string | 后端地址 | 系统生成，不要修改 |

### 只读字段 — 系统字段（不应修改）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 应用 ID |
| `appCode` | string | 应用编码，创建后不可变 |
| `appKey` | string | 应用 Key（OAuth 认证） |
| `appSecret` | string | 应用 Secret（OAuth 认证） |
| `status` | string | 应用状态：`"RUNNING"` / `"SHUTDOWN"`，用专门的状态更新接口修改 |
| `port` | integer | 应用端口号 |
| `currentVersion` | string | 当前版本号 |
| `objectVersionNumber` | integer | 乐观锁版本号，每次保存自动 +1 |
| `owner` | string | 创建者用户 ID |
| `createdBy` | string | 创建者用户 ID |
| `lastUpdatedBy` | string | 最后修改者用户 ID |
| `creationDate` | string | 创建时间 |
| `lastUpdateDate` | string | 最后修改时间 |
| `createName` | string | 创建者姓名 |
| `tenantId` | string | 租户 ID |
| `saveStatus` | boolean | 保存状态 |
| `jobStatus` | string | 定时任务状态 |
| `domainTypes` | string | 域名类型 |
| `oauthScope` | string | OAuth 授权范围 |
| `oauthRedirectUrl` | string | OAuth 回调地址 |
| `appNameI18nAssociated` | boolean | 应用名称是否关联国际化 |
| `remarksI18nAssociated` | boolean | 备注是否关联国际化 |

### 响应格式
```json
{
  "code": "ok",
  "message": "保存成功",
  "data": {
    "（完整应用对象，同查询返回的结构）"
  }
}
```

## Python 调用示例

### 修改应用名称
```python
from app.apaas_client import APaaSClient

async def update_app_name(client: APaaSClient, app_id: str, new_name: str):
    """修改应用名称"""
    # 1. 查询完整应用数据
    app_data = await client.request(
        "GET",
        f"/xdap-app/apaasApplications/queryAppById?id={app_id}"
    )

    # 2. 修改名称
    app_data["appName"] = new_name

    # 3. 回写
    result = await client.request(
        "POST",
        "/xdap-app/apaasApplications/saveApp",
        json=app_data
    )

    print(f"应用名称已更新为: {result.get('appName')}")
    return result
```

### 修改多个字段
```python
async def update_app_info(
    client: APaaSClient,
    app_id: str,
    app_name: str = None,
    remarks: str = None,
    app_theme: str = None
):
    """修改应用基础信息（名称、描述、主题色）"""
    # 1. 查询
    app_data = await client.request(
        "GET",
        f"/xdap-app/apaasApplications/queryAppById?id={app_id}"
    )

    # 2. 按需修改
    if app_name is not None:
        app_data["appName"] = app_name
    if remarks is not None:
        app_data["remarks"] = remarks
    if app_theme is not None:
        app_data["appTheme"] = app_theme

    # 3. 回写
    result = await client.request(
        "POST",
        "/xdap-app/apaasApplications/saveApp",
        json=app_data
    )

    return result
```

## 注意事项

### 必须传完整对象
- `saveApp` 接口要求传入**完整的应用对象**
- 只传 `id` + `appName` 会导致其他字段被清空
- 正确做法：先查询 → 修改目标字段 → 整体回写

### 不要修改的字段
以下字段不应修改，否则可能导致应用异常：
- `id` — 应用 ID
- `appCode` — 应用编码（创建后不可变）
- `appKey` / `appSecret` — 应用密钥
- `status` — 应用状态（用专门的状态更新接口）
- `accessUrl` / `backendUrl` — 系统生成的访问地址
- `port` — 应用端口
- `objectVersionNumber` — 乐观锁版本号

### objectVersionNumber 乐观锁
- 每次保存后 `objectVersionNumber` 会自动 +1
- 如果传入的版本号与服务端不一致，可能保存失败
- 所以必须先查询获取最新版本号再修改

### appName 与 appCode 的区别
- `appName` 是显示名称，可以随时修改
- `appCode` 是应用编码，创建后不可修改

## 常见错误

| 错误码 | 错误信息 | 原因 | 解决方法 |
|--------|---------|------|---------|
| 7003 | 应用不存在 | id 不正确，或使用了错误的 API 路径 | 确认使用 `/apaasApplications/` 路径 |
| - | 保存失败 | objectVersionNumber 不一致 | 重新查询后再修改 |
| 401 | 未授权 | token 过期 | 重新登录 |

## 相关 Skills
- `apaas-create-app` — 创建应用
- `apaas-query-model` — 查询应用下的模型
