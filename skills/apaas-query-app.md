# aPaaS Query App

## 用途
根据应用 ID 查询应用详情，用于获取应用的完整信息，包括应用编码、名称、状态、管理员列表、访问地址等

## API 端点
```
GET /xdap-app/apaasApplications/queryAppById
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
| id | query | string | 是 | 应用 ID |

### 请求示例
```
GET /xdap-app/apaasApplications/queryAppById?id=702184667326971904
```

## 响应格式
```json
{
  "code": "ok",
  "message": "操作成功",
  "data": {
    "owner": "100618744775138344960",
    "createdBy": "100618744775138344960",
    "lastUpdatedBy": "100618520843076501504",
    "creationDate": "2029-04-21 15:51:11",
    "lastUpdateDate": "2026-03-27 16:09:31",
    "objectVersionNumber": 604,
    "tenantId": "618517491999571969",
    "id": "702184667326971904",
    "appCode": "new-2025408-app",
    "appName": "4.0.8应用(新)----111",
    "appKey": "ef5b322f-a95d-4c49-84ab-34fdf30a77f8",
    "appSecret": "a903da1b-4439-4966-bd00-07ec5cda9364",
    "status": "RUNNING",
    "createName": "Apifox接口测试专用",
    "currentVersion": "1.2.71",
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
    "appAdmins": [
      {
        "id": "100618518477874921472",
        "appId": "702184667326971904",
        "username": "胡晨",
        "account": "15026982450"
      }
    ],
    "accessMobileUrl": "https://apaas-rc.dfy.definesys.cn/m/tenant408/new-2025408-app/",
    "modalDefaultStyle": "small",
    "drawerDefaultStyle": "small",
    "customThemeButton": "DISABLE",
    "customThemeColor": "#B4F1E9",
    "domainTypes": "custom",
    "appNameI18nAssociated": true,
    "appNameI18nResourceCode": "i18n_SfNxRxDT",
    "appNameI18n": {
      "resourceCode": "i18n_SfNxRxDT",
      "zhCN": "4.0.8应用(新)----111",
      "enUS": "TEST",
      "jaJP": "",
      "es": "",
      "ar": "",
      "languageText": "4.0.8应用(新)----111"
    },
    "remarksI18nAssociated": false,
    "powerJobEffectiveStatus": "ENABLE",
    "jobStatus": "ENABLE",
    "customBackgroundStatus": "DISABLE",
    "homePageDisplayPc": "702184667767373824",
    "homePageDisplayMobile": "MENU_HOME_PAGE",
    "mobileNavBarStatus": false,
    "homePageDisplayPcName": "我的待办",
    "homePageDisplayMobileName": "菜单页面",
    "homePageDisplayPcMenu": {
      "owner": "100618744775138344960",
      "createdBy": "100618744775138344960",
      "lastUpdatedBy": "100618520790798696448",
      "creationDate": "2025-04-21 15:51:11",
      "lastUpdateDate": "2025-08-22 16:21:24",
      "objectVersionNumber": 7,
      "id": "702184667767373824",
      "appId": "702184667326971904",
      "parentId": "707599084881444864",
      "menuName": "我的待办",
      "menuIcon": "shenpi",
      "menuType": "TODO",
      "menuOrder": 0,
      "cusIconStatus": "DISABLE",
      "newWindowStatus": "DISABLE",
      "cusModelPageStatus": "DISABLE",
      "menuDisplay": "ALL",
      "menuNameI18nAssociated": true,
      "menuNameI18nResourceCode": "i18n_i9BF7TE9",
      "isEffective": true,
      "iconColor": "#027AFF"
    }
  }
}
```

### 响应字段说明

#### 应用基础信息
| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 应用 ID |
| appCode | string | 应用编码 |
| appName | string | 应用名称 |
| appKey | string | 应用 Key（用于 API 鉴权） |
| appSecret | string | 应用密钥（用于 API 鉴权） |
| status | string | 应用状态：RUNNING / STOPPED |
| currentVersion | string | 当前版本号 |
| tenantId | string | 租户 ID |

#### 访问地址
| 字段 | 类型 | 说明 |
|------|------|------|
| accessUrl | string | PC 端访问地址 |
| accessMobileUrl | string | 移动端访问地址 |
| backendUrl | string | 后端 API 地址 |
| port | integer | 应用端口 |

#### 应用外观
| 字段 | 类型 | 说明 |
|------|------|------|
| appTheme | string | 主题色（如 #7ED321） |
| customThemeColor | string | 自定义主题色 |
| appIcon | string | 应用图标 URL |
| smallIcon | string | 小图标 URL |
| phoneIcon | string | 手机端图标 URL |
| innerIcon | string | 内置图标名称 |
| customIconStatus | string | 自定义图标状态：ENABLE / DISABLE |

#### 应用管理员
| 字段 | 类型 | 说明 |
|------|------|------|
| appAdmins | array | 应用管理员列表 |
| appAdmins[].id | string | 管理员用户 ID |
| appAdmins[].username | string | 管理员姓名 |
| appAdmins[].account | string | 管理员账号 |

#### 首页设置
| 字段 | 类型 | 说明 |
|------|------|------|
| homePageDisplayPc | string | PC 端首页菜单 ID |
| homePageDisplayPcName | string | PC 端首页名称 |
| homePageDisplayMobile | string | 移动端首页标识 |
| homePageDisplayMobileName | string | 移动端首页名称 |
| homePageDisplayPcMenu | object | PC 端首页菜单详情 |

#### 国际化
| 字段 | 类型 | 说明 |
|------|------|------|
| appNameI18nAssociated | boolean | 是否关联国际化 |
| appNameI18nResourceCode | string | 国际化资源编码 |
| appNameI18n | object | 国际化文本对象（zhCN / enUS / jaJP / es / ar） |

#### 其他配置
| 字段 | 类型 | 说明 |
|------|------|------|
| modalDefaultStyle | string | 弹窗默认样式：small / medium / large |
| drawerDefaultStyle | string | 抽屉默认样式：small / medium / large |
| powerJobEffectiveStatus | string | 定时任务状态：ENABLE / DISABLE |
| mobileNavBarStatus | boolean | 移动端导航栏状态 |
| oauthScope | string | OAuth 授权范围 |
| oauthRedirectUrl | string | OAuth 回调地址 |

#### 审计字段
| 字段 | 类型 | 说明 |
|------|------|------|
| owner | string | 所有者用户 ID |
| createdBy | string | 创建者用户 ID |
| lastUpdatedBy | string | 最后更新者用户 ID |
| creationDate | string | 创建时间 |
| lastUpdateDate | string | 最后更新时间 |
| objectVersionNumber | integer | 乐观锁版本号 |

## Python 调用示例

### 使用 APaaSClient
```python
from app.apaas_client import APaaSClient

async def query_app_by_id(client: APaaSClient, app_id: str):
    """根据 ID 查询应用详情"""
    import time
    timestamp = str(int(time.time() * 1000))

    result = await client.request(
        "GET",
        "/backend/xdap-app/apaasApplications/queryAppById",
        params={"id": app_id, "timestamp": timestamp},
        app_id=app_id
    )

    if result.get("code") == "ok":
        app_data = result.get("data", {})
        print(f"应用名称: {app_data.get('appName')}")
        print(f"应用编码: {app_data.get('appCode')}")
        print(f"应用状态: {app_data.get('status')}")
        print(f"PC 访问地址: {app_data.get('accessUrl')}")
        print(f"移动端访问地址: {app_data.get('accessMobileUrl')}")
        print(f"管理员数量: {len(app_data.get('appAdmins', []))}")

        return app_data

    return None
```

### 获取应用访问地址
```python
async def get_app_access_urls(client: APaaSClient, app_id: str):
    """获取应用的访问地址"""
    import time
    timestamp = str(int(time.time() * 1000))

    result = await client.request(
        "GET",
        "/backend/xdap-app/apaasApplications/queryAppById",
        params={"id": app_id, "timestamp": timestamp},
        app_id=app_id
    )

    if result.get("code") == "ok":
        data = result.get("data", {})
        return {
            "pc_url": data.get("accessUrl"),
            "mobile_url": data.get("accessMobileUrl"),
            "backend_url": data.get("backendUrl")
        }

    return None
```

### 获取应用管理员列表
```python
async def get_app_admins(client: APaaSClient, app_id: str):
    """获取应用管理员列表"""
    import time
    timestamp = str(int(time.time() * 1000))

    result = await client.request(
        "GET",
        "/backend/xdap-app/apaasApplications/queryAppById",
        params={"id": app_id, "timestamp": timestamp},
        app_id=app_id
    )

    if result.get("code") == "ok":
        admins = result.get("data", {}).get("appAdmins", [])
        return [
            {
                "id": admin.get("id"),
                "username": admin.get("username"),
                "account": admin.get("account")
            }
            for admin in admins
        ]

    return []
```

### 检查应用状态
```python
async def check_app_status(client: APaaSClient, app_id: str):
    """检查应用状态"""
    import time
    timestamp = str(int(time.time() * 1000))

    result = await client.request(
        "GET",
        "/backend/xdap-app/apaasApplications/queryAppById",
        params={"id": app_id, "timestamp": timestamp},
        app_id=app_id
    )

    if result.get("code") == "ok":
        data = result.get("data", {})
        return {
            "status": data.get("status"),  # RUNNING / STOPPED
            "version": data.get("currentVersion"),
            "is_running": data.get("status") == "RUNNING"
        }

    return None
```

## 使用场景

### 场景 1: 验证应用是否存在
```python
app = await query_app_by_id(client, "702184667326971904")
if app:
    print(f"应用存在: {app['appName']}")
else:
    print("应用不存在")
```

### 场景 2: 获取应用 API 认证信息
```python
app = await query_app_by_id(client, app_id)
api_credentials = {
    "app_key": app.get("appKey"),
    "app_secret": app.get("appSecret"),
    "backend_url": app.get("backendUrl")
}
```

### 场景 3: 获取应用首页配置
```python
app = await query_app_by_id(client, app_id)
home_page_config = {
    "pc_home_page_id": app.get("homePageDisplayPc"),
    "pc_home_page_name": app.get("homePageDisplayPcName"),
    "mobile_home_page": app.get("homePageDisplayMobile"),
    "mobile_home_page_name": app.get("homePageDisplayMobileName")
}
```

## 注意事项

### appid 请求头
- 请求头中的 `appid` 必须与查询的应用 ID 一致
- 这是接口鉴权的关键参数

### 应用密钥安全
- `appSecret` 是敏感信息，获取后应妥善保管
- 用于外部 API 调用的鉴权

## 常见错误

| 错误码 | 错误信息 | 原因 | 解决方法 |
|--------|---------|------|---------|
| 401 | 未授权 | token 过期 | 重新登录 |
| 404 | 应用不存在 | 应用 ID 错误 | 检查应用 ID |
| 500 | Internal Server Error | 请求参数错误 | 检查 timestamp 和 appid 请求头 |

## 相关 Skills

### 应用管理
- `apaas-create-app` — 创建应用
- `apaas-update-app` — 更新应用
- `apaas-delete-app` — 删除应用

### 其他资源查询
- `apaas-query-model` — 查询数据模型
- `apaas-query-role` — 查询角色
- `apaas-query-dict` — 查询字典
