# aPaaS Create Role

## 用途
在应用下批量创建角色（用于权限控制和流程审批）

## API 端点
```
POST /xdap-app/common/resource/appRole
```

## 请求头
```json
{
  "Content-Type": "application/json",
  "xdaptenantid": "<tenant_id>",
  "xdaptimestamp": "<millisecond_timestamp>",
  "xdaptoken": "<auth_token>",
  "appid": "<app_id>"
}
```

## 请求格式
```json
[
  {
    "appId": "123456789",
    "roleCode": "R_manager_a1b2",
    "roleName": "经理"
  },
  {
    "appId": "123456789",
    "roleCode": "R_engineer_a1b2",
    "roleName": "工程师"
  }
]
```

## 参数说明

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| appId | string | 是 | 应用 ID |
| roleCode | string | 是 | 角色编码，建议格式 `R_{code}_{suffix}` |
| roleName | string | 是 | 角色名称（中文） |

## 响应格式
```json
{
  "code": "ok",
  "data": {}
}
```

## Python 调用示例

### 使用 config_transformer
```python
from app.config_transformer import transform_roles
from app.apaas_client import APaaSClient

async def create_roles_example(client: APaaSClient, app_id: str):
    # 预览格式的角色定义
    roles = [
        {"name": "经理", "code": "manager"},
        {"name": "工程师", "code": "engineer"},
        {"name": "客服", "code": "customer_service"}
    ]

    # 转换为 API 格式（自动添加 R_ 前缀和随机后缀）
    payload = transform_roles(app_id, roles)

    # 调用 API
    try:
        await client.create_roles(app_id, payload)
        print(f"创建了 {len(payload)} 个角色")
    except Exception as e:
        if "已存在" in str(e) or "重复" in str(e):
            print(f"角色已存在，跳过: {e}")
        else:
            raise
```

### transform_roles 实现
```python
from typing import List, Dict
import random, string

def _rand(n: int = 4) -> str:
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))

def transform_roles(app_id: str, roles: List[Dict]) -> List[Dict]:
    """构建 /common/resource/appRole 请求体"""
    return [
        {
            "appId": app_id,
            "roleCode": f"R_{r.get('code', r['name'])}_{_rand()}",
            "roleName": r["name"]
        }
        for r in roles
    ]
```

### 直接调用示例
```python
async def create_roles_direct(client: APaaSClient, app_id: str):
    payload = [
        {
            "appId": app_id,
            "roleCode": "R_manager_a1b2",
            "roleName": "经理"
        },
        {
            "appId": app_id,
            "roleCode": "R_engineer_a1b2",
            "roleName": "工程师"
        }
    ]

    await client.create_roles(app_id, payload)
```

## 注意事项

### roleCode 命名规范
- **建议格式**: `R_{业务code}_{随机后缀}`
- 前缀 `R_` 是约定俗成的角色编码前缀
- 随机后缀避免重复冲突
- 示例：
  - `R_manager_a1b2`
  - `R_engineer_x9y3`
  - `R_customer_service_m5n7`

### 角色重复处理
- 如果 `roleCode` 已存在，API 会返回错误
- 在生成管线中，角色创建失败**不应阻断流程**
- 建议使用 try-catch 捕获并跳过：
  ```python
  try:
      await client.create_roles(app_id, payload)
  except Exception as e:
      if "已存在" in str(e) or "重复" in str(e):
          print(f"角色跳过（已存在）: {e}")
      else:
          raise  # 其他错误仍然抛出
  ```

### 角色用途
- **权限控制**: 在表单权限配置中使用（formPermission）
- **流程审批**: 在流程节点中指定审批人角色（processConfig）
- **数据范围**: 控制用户可见的数据范围

### 随机后缀策略
```python
import random, string

suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
role_code = f"R_manager_{suffix}"  # R_manager_a1b2
```

## 常见错误

| 错误码 | 错误信息 | 原因 | 解决方法 |
|--------|---------|------|---------|
| - | 角色编码已存在 | roleCode 重复 | 添加随机后缀或跳过错误 |
| - | 角色编码格式错误 | roleCode 包含非法字符 | 只使用字母、数字、下划线 |

## 在生成管线中的使用

### Stage 1: 公共资源创建
```python
# 在 generator.py 中
yield {"stage": 1, "status": "running", "step": "开始创建公共资源..."}

try:
    if roles:
        try:
            payload = transform_roles(app_id, roles)
            await client.create_roles(app_id, payload)
            names = '、'.join(r['name'] for r in roles)
            yield {"stage": 1, "status": "running", "step": f"创建角色: {names}"}
        except Exception as e:
            # 角色重复不阻断流程
            yield {"stage": 1, "status": "running", "step": f"角色跳过（已存在）: {e}"}
except Exception as e:
    yield {"stage": 1, "status": "error", "step": f"公共资源创建失败: {e}"}
    return
```

## 相关 Skills
- `apaas-create-app` — 创建应用（获取 appId）
- `apaas-create-form` — 创建表单配置（权限设置中使用角色）
