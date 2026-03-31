# aPaaS Deploy App

## 用途
部署/上线应用，将应用发布到运行环境。部署后应用状态变为 PUBLISHING（发布中），最终变为 RUNNING（运行中）

## API 端点
```
POST /xdap-app/deploy/deployApplication
```

## 请求头
```json
{
  "xdaptenantid": "<tenant_id>",
  "xdaptimestamp": "<millisecond_timestamp>",
  "xdaptoken": "<auth_token>"
}
```

## 请求参数
| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|------|------|
| appId | body | string | 是 | 应用 ID |
| appVersion | body | string | 是 | 版本号（如 1.2.73） |
| appAbstract | body | string | 否 | 应用描述/摘要 |

### 请求示例
```json
POST /backend/xdap-app/deploy/deployApplication?timestamp=1774611534718

{
  "appId": "702184667326971904",
  "appVersion": "1.2.73",
  "appAbstract": ""
}
```

## 响应格式
```json
{
  "code": "ok",
  "message": "应用上线成功",
  "data": {
    "owner": "100618744775138344960",
    "createdBy": "100618744775138344960",
    "lastUpdatedBy": "100618764048091054080",
    "creationDate": "2029-04-21 15:51:11",
    "lastUpdateDate": "2026-03-27 19:39:02",
    "objectVersionNumber": 606,
    "tenantId": "618517491999571969",
    "id": "702184667326971904",
    "appCode": "new-2025408-app",
    "appName": "4.0.8应用(新)----111",
    "appKey": "ef5b322f-a95d-4c49-84ab-34fdf30a77f8",
    "appSecret": "a903da1b-4439-4966-bd00-07ec5cda9364",
    "status": "PUBLISHING",
    "appTheme": "#7ED321",
    "port": 30944,
    "accessUrl": "https://apaas-rc.dfy.definesys.cn/app/tenant408/new-2025408-app/",
    "backendUrl": "https://apaas-rc.dfy.definesys.cn/apaas/backend/tenant408/new-2025408-app",
    "customIconStatus": "ENABLE",
    "appIcon": "https://apaas-rc.dfy.definesys.cn/backend//xdap-admin/attachments/downloadFile?file=d57bdd80-055f-4a7c-9e53-7bce6c15d649",
    "smallIcon": "https://apaas-rc.dfy.definesys.cn/backend//xdap-admin/attachments/downloadFile?file=bc5c7d21-f097-4910-967c-3b44f2d9b9a0",
    "phoneIcon": "https://apaas-rc.dfy.definesys.cn/backend//xdap-admin/attachments/downloadFile?file=1deecc00-7b49-4c4d-a790-a1794ffd2892",
    "innerIcon": "userInfo",
    "saveStatus": true,
    "oauthScope": "user_info",
    "oauthRedirectUrl": "https://apaas-rc.dfy.definesys.cn/app/tenant408/new-2025408-app/callback/oauth/app/index.html",
    "accessMobileUrl": "https://apaas-rc.dfy.definesys.cn/m/tenant408/new-2025408-app/",
    "modalDefaultStyle": "small",
    "drawerDefaultStyle": "small",
    "customThemeButton": "DISABLE",
    "customThemeColor": "#B4F1E9",
    "appNameI18nAssociated": true,
    "appNameI18nResourceCode": "i18n_SfNxRxDT",
    "remarksI18nAssociated": false,
    "jobStatus": "ENABLE",
    "customBackgroundStatus": "DISABLE",
    "homePageDisplayPc": "702184667767373824",
    "homePageDisplayMobile": "MENU_HOME_PAGE",
    "mobileNavBarStatus": false
  }
}
```

### 响应字段说明
响应返回应用详情对象，主要关注以下字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| code | string | 状态码：ok 表示成功 |
| message | string | 操作结果消息 |
| data | object | 应用详情对象 |
| data.status | string | 应用状态：PUBLISHING（发布中）/ RUNNING（运行中） |
| data.id | string | 应用 ID |
| data.appCode | string | 应用编码 |
| data.appName | string | 应用名称 |
| data.accessUrl | string | PC 端访问地址 |
| data.accessMobileUrl | string | 移动端访问地址 |

完整字段说明请参考 `apaas-query-app` skill。

## Python 调用示例

### 使用 APaaSClient
```python
from app.apaas_client import APaaSClient

async def deploy_app(client: APaaSClient, app_id: str, version: str, description: str = ""):
    """部署/上线应用"""
    import time
    timestamp = str(int(time.time() * 1000))

    result = await client.request(
        "POST",
        "/backend/xdap-app/deploy/deployApplication",
        params={"timestamp": timestamp},
        json={
            "appId": app_id,
            "appVersion": version,
            "appAbstract": description
        },
        app_id=app_id
    )

    if result.get("code") == "ok":
        app_data = result.get("data", {})
        print(f"应用 {app_data.get('appName')} 部署成功")
        print(f"当前状态: {app_data.get('status')}")
        print(f"PC 访问地址: {app_data.get('accessUrl')}")
        return app_data

    return None
```

### 部署并等待状态变更
```python
import asyncio
from app.apaas_client import APaaSClient

async def deploy_and_wait(client: APaaSClient, app_id: str, version: str, description: str = ""):
    """部署应用并等待状态变为 RUNNING"""
    import time

    # 1. 执行部署
    timestamp = str(int(time.time() * 1000))
    result = await client.request(
        "POST",
        "/backend/xdap-app/deploy/deployApplication",
        params={"timestamp": timestamp},
        json={
            "appId": app_id,
            "appVersion": version,
            "appAbstract": description
        },
        app_id=app_id
    )

    if result.get("code") != "ok":
        print(f"部署失败: {result.get('message')}")
        return None

    print(f"应用部署中，状态: {result.get('data', {}).get('status')}")

    # 2. 轮询等待状态变为 RUNNING
    max_retries = 30  # 最多等待 30 次（每次 5 秒，共 2.5 分钟）
    retry_count = 0

    while retry_count < max_retries:
        await asyncio.sleep(5)

        # 查询应用状态
        timestamp = str(int(time.time() * 1000))
        query_result = await client.request(
            "GET",
            "/backend/xdap-app/apaasApplications/queryAppById",
            params={"id": app_id, "timestamp": timestamp},
            app_id=app_id
        )

        if query_result.get("code") == "ok":
            app_data = query_result.get("data", {})
            status = app_data.get("status")

            print(f"当前状态: {status}")

            if status == "RUNNING":
                print(f"应用已上线: {app_data.get('accessUrl')}")
                return app_data
            elif status in ["STOPPED", "FAILED"]:
                print(f"应用部署失败，状态: {status}")
                return None

        retry_count += 1

    print("部署超时")
    return None
```

### 自动递增版本号部署
```python
async def deploy_with_auto_version(client: APaaSClient, app_id: str, description: str = ""):
    """自动获取当前版本并递增后部署"""
    import time
    import re

    # 1. 查询当前版本
    timestamp = str(int(time.time() * 1000))
    query_result = await client.request(
        "GET",
        "/backend/xdap-app/apaasApplications/queryAppById",
        params={"id": app_id, "timestamp": timestamp},
        app_id=app_id
    )

    if query_result.get("code") != "ok":
        print("无法获取应用信息")
        return None

    current_version = query_result.get("data", {}).get("currentVersion", "1.0.0")

    # 2. 递增版本号（增加最后一位）
    major, minor, patch = current_version.split(".")
    new_version = f"{major}.{minor}.{int(patch) + 1}"

    print(f"当前版本: {current_version}, 新版本: {new_version}")

    # 3. 执行部署
    timestamp = str(int(time.time() * 1000))
    result = await client.request(
        "POST",
        "/backend/xdap-app/deploy/deployApplication",
        params={"timestamp": timestamp},
        json={
            "appId": app_id,
            "appVersion": new_version,
            "appAbstract": description
        },
        app_id=app_id
    )

    return result.get("data") if result.get("code") == "ok" else None
```

## 使用场景

### 场景 1: 首次部署新应用
```python
await deploy_app(client, "702184667326971904", "1.0.0", "首次上线")
```

### 场景 2: 更新后重新部署
```python
# 在完成模型/表单/字典等更新后部署
await deploy_app(
    client,
    app_id="702184667326971904",
    version="1.2.73",
    description="新增客户管理模块"
)
```

### 场景 3: 自动化部署流程
```python
async def full_deploy_workflow(client: APaaSClient, app_id: str):
    """完整的部署流程"""

    # 1. 创建/更新模型
    # await create_model(...)

    # 2. 创建/更新表单
    # await create_form(...)

    # 3. 部署应用
    result = await deploy_and_wait(
        client,
        app_id=app_id,
        version="1.0.1",
        description="初始化部署"
    )

    if result:
        print(f"部署成功，访问地址: {result['accessUrl']}")
```

## 注意事项

### 应用状态流转
```
DRAFT（草稿） -> PUBLISHING（发布中） -> RUNNING（运行中）
                                    -> FAILED（失败）
```

### 版本号格式
- 必须遵循语义化版本格式：`X.Y.Z`
- 如：`1.0.0`、`1.2.73`、`2.0.15`
- 每次部署建议递增版本号

### 部署时长
- 小型应用部署通常需要 10-30 秒
- 大型应用可能需要 1-2 分钟
- 建议实现轮询机制等待部署完成

### 部署前保存
- 确保所有更改已保存
- 未保存的更改不会被部署

### 重复部署
- 应用处于 PUBLISHING 状态时可以再次部署
- 会终止之前的部署任务，开始新的部署

## 常见错误

| 错误码 | 错误信息 | 原因 | 解决方法 |
|--------|---------|------|---------|
| 401 | 未授权 | token 过期 | 重新登录 |
| 500 | 版本号格式错误 | appVersion 格式不正确 | 使用 X.Y.Z 格式 |
| 500 | 应用不存在 | appId 错误 | 检查应用 ID |
| 500 | 无内容可发布 | 应用无任何内容 | 先创建模型/表单等 |

## 相关 Skills

### 应用管理
- `apaas-query-app` — 查询应用详情
- `apaas-create-app` — 创建应用
- `apaas-update-app` — 更新应用

### 其他部署相关
- `apaas-create-model` — 创建数据模型
- `apaas-create-form` — 创建表单
- `apaas-publish-form` — 发布表单
