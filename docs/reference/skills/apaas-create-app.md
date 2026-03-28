# aPaaS Create Application

## 用途
在得帆云 aPaaS 平台创建一个新应用

## API 端点
```
POST /xdap-app/apaasApplications/addApp
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

## 请求格式
```json
{
  "appName": "应用名称",
  "appCode": "app-code",
  "appDesc": "应用描述",
  "appType": "CUSTOM"
}
```

## 参数说明

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| appName | string | 是 | 应用名称，1-32 字符 |
| appCode | string | 是 | 应用编码，必须符合 `^[A-Za-z][A-Za-z0-9-]*$`（只能用字母、数字、连字符，不能用下划线） |
| appDesc | string | 否 | 应用描述 |
| appType | string | 是 | 应用类型，固定值 "CUSTOM" |

## 响应格式
```json
{
  "code": "ok",
  "data": {
    "id": "123456789",
    "appName": "应用名称",
    "appCode": "app-code",
    ...
  }
}
```

返回的 `data.id` 即为 `appId`，后续创建模型、字典、表单等资源时需要使用。

## Python 调用示例

### 使用 APaaSClient
```python
from app.apaas_client import APaaSClient

async def create_app_example():
    client = APaaSClient()

    # 登录
    await client.login("account", "password")

    # 创建应用
    result = await client.create_app(
        app_name="客户管理系统",
        app_code="crm-system",
        description="CRM 应用"
    )

    app_id = str(result.get("id", ""))
    print(f"应用创建成功，ID: {app_id}")
    return app_id
```

### 直接 HTTP 调用
```python
import httpx
import time

async def create_app_direct(token, tenant_id):
    headers = {
        "Content-Type": "application/json",
        "xdaptenantid": tenant_id,
        "xdaptimestamp": str(int(time.time() * 1000)),
        "xdaptoken": token
    }

    payload = {
        "appName": "客户管理系统",
        "appCode": "crm-system",
        "appDesc": "CRM 应用",
        "appType": "CUSTOM"
    }

    async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
        response = await client.post(
            "https://apaas-poc.definesys.cn/backend/xdap-app/apaasApplications/addApp",
            headers=headers,
            json=payload
        )
        data = response.json()
        if data.get("code") == "ok":
            return data.get("data", {})
        else:
            raise Exception(f"创建应用失败: {data.get('message')}")
```

## 注意事项

### appCode 编码规则
- **必须以字母开头**
- **只能包含字母、数字、连字符（-）**
- **不能包含下划线（_）**，否则会报错 "appCode不正确 (7012)"
- 示例：
  - ✅ `customer-management`
  - ✅ `crm-v2`
  - ❌ `customer_management`（包含下划线）
  - ❌ `123-app`（数字开头）

### 时间戳验证
- `xdaptimestamp` 必须是毫秒级时间戳
- 必须在服务器时间 ±5 分钟内，否则会返回 500 错误
- Python 生成方式：`str(int(time.time() * 1000))`

### 应用重复
- 如果 `appCode` 已存在，会返回错误 "应用编码已存在"
- 建议在 appCode 后添加随机后缀避免冲突：
  ```python
  import random, string
  suffix = ''.join(random.choices(string.ascii_lowercase, k=4))
  app_code = f"crm-{suffix}"
  ```

### 返回值处理
- 成功时 `code` 为 `"ok"`
- `data` 可能是对象或字符串（appId）
- 安全提取 appId：
  ```python
  app_id = str(result) if isinstance(result, str) else str(result.get("id", result.get("appId", "")))
  ```

## 常见错误

| 错误码 | 错误信息 | 原因 | 解决方法 |
|--------|---------|------|---------|
| 7012 | appCode不正确 | appCode 包含下划线或不符合格式 | 使用连字符代替下划线 |
| - | 应用编码已存在 | appCode 重复 | 添加随机后缀或查询已有应用复用 |
| 500 | 时间戳验证失败 | xdaptimestamp 超出 5 分钟范围 | 使用当前时间戳 |
| 401 | 未授权 | token 过期或无效 | 重新登录获取新 token |

## 相关 Skills
- `apaas-create-model` — 在应用下创建数据模型
- `apaas-create-dict` — 在应用下创建数据字典
- `apaas-create-role` — 在应用下创建角色
