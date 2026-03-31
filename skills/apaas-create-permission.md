# aPaaS Configure Form Permission

## 用途
为应用下的一个或多个表单配置功能权限和数据权限，用于给不同角色设置新增、导入、审批、查看、编辑、删除等权限，以及数据范围。

## API 端点

### 配置表单权限
```
POST /xdap-app/common/resource/formPermission
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

### 单个表单权限配置
```json
[
  {
    "formCode": "form_customer",
    "appId": "825120213669249024",
    "tenantId": "",
    "formId": "69c4b4b5cfa50072690bc753",
    "operationPermissionGroups": [
      {
        "permissionName": "系统管理员操作权限",
        "permissionDescribe": "",
        "permissionObjects": [
          {
            "permissionObjectDisplayName": "系统管理员",
            "permissionObjectType": "ROLE",
            "permissionObjectValue": "R_system_admin",
            "permissionRange": {
              "rangeType": "ALL"
            }
          }
        ],
        "permissionOperationType": {
          "addPermission": true,
          "batchAgreePermission": true,
          "batchDeletePermission": true,
          "batchRejectPermission": true,
          "copyAddPermission": true,
          "importPermission": true,
          "shareFormPermission": false,
          "temporaryStoragePermission": true
        }
      }
    ],
    "dataPermissionGroups": [
      {
        "permissionName": "系统管理员数据权限",
        "permissionDescribe": "",
        "permissionObjects": [
          {
            "permissionObjectDisplayName": "系统管理员",
            "permissionObjectType": "ROLE",
            "permissionObjectValue": "R_system_admin",
            "permissionRange": {
              "rangeType": "ALL"
            }
          }
        ],
        "permissionOperationType": {
          "queryPermission": true,
          "deletePermission": true,
          "updatePermission": true
        }
      }
    ]
  }
]
```

### 多个表单批量配置
```json
[
  {
    "formCode": "form_customer",
    "appId": "825120213669249024",
    "tenantId": "",
    "formId": "69c4b4b5cfa50072690bc753",
    "operationPermissionGroups": [],
    "dataPermissionGroups": []
  },
  {
    "formCode": "form_contract",
    "appId": "825120213669249024",
    "tenantId": "",
    "formId": "69c4b4bccfa50072690bc775",
    "operationPermissionGroups": [],
    "dataPermissionGroups": []
  }
]
```

## 请求参数

### 顶层对象字段
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| formCode | string | 是 | 表单编码 |
| appId | string | 是 | 应用 ID |
| tenantId | string | 否 | 租户 ID，当前代码通常传空字符串 |
| formId | string | 是 | 表单 ID |
| operationPermissionGroups | array | 是 | 功能权限组列表 |
| dataPermissionGroups | array | 是 | 数据权限组列表 |

### permissionObjects 字段
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| permissionObjectDisplayName | string | 是 | 权限对象显示名称 |
| permissionObjectType | string | 是 | 权限对象类型，如 `ROLE`、`ALL_USER` |
| permissionObjectValue | string | 否 | 权限对象值，角色时通常为平台角色编码 |
| permissionRange | object | 是 | 数据范围配置 |

### permissionRange 字段
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| rangeType | string | 是 | 数据范围类型 |

### rangeType 可选值
| 值 | 说明 |
|------|------|
| ALL | 全部数据 |
| SELF | 仅本人数据 |
| CURRENT_USER_DEPT | 当前部门数据 |
| CURRENT_USER_DEPT_LOW_LEVEL | 当前部门及下级部门数据 |

## 功能权限字段

### operationPermissionType 字段
| 字段 | 类型 | 说明 |
|------|------|------|
| addPermission | boolean | 新增权限 |
| batchAgreePermission | boolean | 批量同意/审批权限 |
| batchDeletePermission | boolean | 批量删除权限 |
| batchRejectPermission | boolean | 批量拒绝权限 |
| copyAddPermission | boolean | 复制新增权限 |
| importPermission | boolean | 导入权限 |
| shareFormPermission | boolean | 分享表单权限 |
| temporaryStoragePermission | boolean | 暂存权限 |

## 数据权限字段

### dataPermissionType 字段
| 字段 | 类型 | 说明 |
|------|------|------|
| queryPermission | boolean | 查看权限 |
| deletePermission | boolean | 删除权限 |
| updatePermission | boolean | 编辑权限 |
| commentPermission | boolean | 评论权限 |
| dataSharePermission | boolean | 数据分享权限 |
| exportPermission | boolean | 导出权限 |
| logPermission | boolean | 日志权限 |
| printPermission | boolean | 打印权限 |
| queryApprovalInfoPermission | boolean | 查询审批信息权限 |

## 响应格式
```json
{
  "code": "ok",
  "message": "操作成功",
  "data": {}
}
```

## 响应字段说明
| 字段 | 类型 | 说明 |
|------|------|------|
| code | string | `ok` 表示成功 |
| message | string | 响应消息 |
| data | object | 返回数据，通常为空对象 |

## Python 调用示例

### 为单个表单配置权限
```python
from app.apaas_client import APaaSClient

async def configure_form_permission(
    client: APaaSClient,
    app_id: str,
    form_id: str,
    form_code: str,
    role_code: str,
    role_name: str,
):
    payload = [
        {
            "formCode": form_code,
            "appId": app_id,
            "tenantId": "",
            "formId": form_id,
            "operationPermissionGroups": [
                {
                    "permissionName": f"{role_name}操作权限",
                    "permissionDescribe": "",
                    "permissionObjects": [
                        {
                            "permissionObjectDisplayName": role_name,
                            "permissionObjectType": "ROLE",
                            "permissionObjectValue": role_code,
                            "permissionRange": {
                                "rangeType": "ALL"
                            }
                        }
                    ],
                    "permissionOperationType": {
                        "addPermission": True,
                        "batchAgreePermission": False,
                        "batchDeletePermission": False,
                        "batchRejectPermission": False,
                        "copyAddPermission": False,
                        "importPermission": False,
                        "shareFormPermission": False,
                        "temporaryStoragePermission": True
                    }
                }
            ],
            "dataPermissionGroups": [
                {
                    "permissionName": f"{role_name}数据权限",
                    "permissionDescribe": "",
                    "permissionObjects": [
                        {
                            "permissionObjectDisplayName": role_name,
                            "permissionObjectType": "ROLE",
                            "permissionObjectValue": role_code,
                            "permissionRange": {
                                "rangeType": "SELF"
                            }
                        }
                    ],
                    "permissionOperationType": {
                        "queryPermission": True,
                        "deletePermission": False,
                        "updatePermission": True
                    }
                }
            ]
        }
    ]

    return await client.create_form_permissions(app_id, payload)
```

### 为多个表单批量配置权限
```python
async def batch_configure_form_permissions(client: APaaSClient, app_id: str, payloads: list):
    """批量配置多个表单权限"""
    return await client.create_form_permissions(app_id, payloads)
```

### 给表单设置默认权限
```python
async def set_default_form_permission(client: APaaSClient, app_id: str, form_id: str, form_code: str):
    payload = [
        {
            "formCode": form_code,
            "appId": app_id,
            "tenantId": "",
            "formId": form_id,
            "operationPermissionGroups": [
                {
                    "permissionName": "默认操作权限",
                    "permissionDescribe": "全部人员可操作",
                    "permissionObjects": [
                        {
                            "permissionObjectDisplayName": "全部人员",
                            "permissionObjectType": "ALL_USER",
                            "permissionObjectValue": "",
                            "permissionRange": {
                                "rangeType": "ALL"
                            }
                        }
                    ],
                    "permissionOperationType": {
                        "addPermission": True,
                        "batchAgreePermission": False,
                        "batchDeletePermission": False,
                        "batchRejectPermission": False,
                        "copyAddPermission": False,
                        "importPermission": False,
                        "shareFormPermission": False,
                        "temporaryStoragePermission": False
                    }
                }
            ],
            "dataPermissionGroups": [
                {
                    "permissionName": "默认数据权限",
                    "permissionDescribe": "全部人员可查看全部数据",
                    "permissionObjects": [
                        {
                            "permissionObjectDisplayName": "全部人员",
                            "permissionObjectType": "ALL_USER",
                            "permissionObjectValue": "",
                            "permissionRange": {
                                "rangeType": "ALL"
                            }
                        }
                    ],
                    "permissionOperationType": {
                        "queryPermission": True,
                        "deletePermission": False,
                        "updatePermission": False
                    }
                }
            ]
        }
    ]

    return await client.create_form_permissions(app_id, payload)
```

## cURL 示例
```bash
curl 'https://apaas-dev8.dfy.definesys.cn/backend/xdap-app/common/resource/formPermission' \
  -H 'accept: application/json, text/plain, */*' \
  -H 'content-type: application/json' \
  -H 'appid: <APP_ID>' \
  -H 'xdaptenantid: <TENANT_ID>' \
  -H 'xdaptimestamp: <TIMESTAMP>' \
  -H 'xdaptoken: <XDAP_TOKEN>' \
  --data-raw '[
    {
      "formCode": "<FORM_CODE>",
      "appId": "<APP_ID>",
      "tenantId": "",
      "formId": "<FORM_ID>",
      "operationPermissionGroups": [
        {
          "permissionName": "系统管理员操作权限",
          "permissionDescribe": "",
          "permissionObjects": [
            {
              "permissionObjectDisplayName": "系统管理员",
              "permissionObjectType": "ROLE",
              "permissionObjectValue": "R_system_admin",
              "permissionRange": {
                "rangeType": "ALL"
              }
            }
          ],
          "permissionOperationType": {
            "addPermission": true,
            "batchAgreePermission": true,
            "batchDeletePermission": true,
            "batchRejectPermission": true,
            "copyAddPermission": true,
            "importPermission": true,
            "shareFormPermission": false,
            "temporaryStoragePermission": true
          }
        }
      ],
      "dataPermissionGroups": [
        {
          "permissionName": "系统管理员数据权限",
          "permissionDescribe": "",
          "permissionObjects": [
            {
              "permissionObjectDisplayName": "系统管理员",
              "permissionObjectType": "ROLE",
              "permissionObjectValue": "R_system_admin",
              "permissionRange": {
                "rangeType": "ALL"
              }
            }
          ],
          "permissionOperationType": {
            "queryPermission": true,
            "deletePermission": true,
            "updatePermission": true
          }
        }
      ]
    }
  ]'
```

## 注意事项

### 请求体是数组
- 即使只配置一个表单，也要传数组
- 每个数组元素对应一个表单的权限配置

### 权限对象字段名必须是 permissionObjects
- 正确字段名是 `permissionObjects`
- 不要写成 `PermissionObjects`

### 角色权限对象
- `permissionObjectType` 为 `ROLE` 时
- `permissionObjectValue` 应传平台上的角色编码，如 `R_system_admin`

### 全员权限对象
- `permissionObjectType` 为 `ALL_USER` 时
- `permissionObjectValue` 通常传空字符串

### appId 和 formId 都要匹配
- `appid` 请求头
- 请求体中的 `appId`
- 请求体中的 `formId`
- 这三者要和目标应用、目标表单对应一致

### SECURITY_INFO 不是当前代码链路必需参数
- 当前项目后端调用这个接口时没有带 `SECURITY_INFO`
- 仅使用 `appid + xdaptenantid + xdaptimestamp + xdaptoken` 即可

### tenantId 字段
- 当前项目代码里 `tenantId` 在请求体中固定传空字符串
- 平台租户信息主要通过请求头 `xdaptenantid` 识别
